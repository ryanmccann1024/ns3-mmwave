#include "src/query/child-process.h"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <poll.h>
#include <sys/wait.h>
#include <unistd.h>

namespace mesh_sim::query
{
using Clock = std::chrono::steady_clock;
volatile std::sig_atomic_t g_activeChild = 0;

void
ForwardTermination(int sig)
{
    const pid_t child = static_cast<pid_t>(g_activeChild);
    if (child > 0)
    {
        kill(child, SIGKILL);
    }
    std::signal(sig, SIG_DFL);
    std::raise(sig);
}

void
InstallTerminationForwarding()
{
    struct sigaction sa;
    std::memset(&sa, 0, sizeof(sa));
    sa.sa_handler = ForwardTermination;
    sigemptyset(&sa.sa_mask);
    for (int sig : {SIGTERM, SIGINT, SIGHUP})
    {
        sigaction(sig, &sa, nullptr);
    }
    // An inherited SIG_IGN would auto-reap children and break waitpid.
    std::signal(SIGCHLD, SIG_DFL);
}

bool
WriteAll(int fd, const std::string& data)
{
    std::size_t off = 0;
    while (off < data.size())
    {
        const ssize_t n = write(fd, data.data() + off, data.size() - off);
        if (n < 0)
        {
            if (errno == EINTR)
            {
                continue;
            }
            return false;
        }
        off += static_cast<std::size_t>(n);
    }
    return true;
}

[[noreturn]] void
ChildMain(const std::function<std::string()>& evaluate, const QueryConfig& policy, int fd)
{
    for (int sig : {SIGTERM, SIGINT, SIGHUP, SIGPIPE})
    {
        std::signal(sig, SIG_DFL);
    }
    alarm(
        static_cast<unsigned>(std::ceil(policy.child_deadline_s + policy.terminate_grace_s + 5.0)));
    const int devNull = open("/dev/null", O_RDONLY);
    if (devNull >= 0)
    {
        dup2(devNull, STDIN_FILENO);
        if (devNull != STDIN_FILENO)
        {
            close(devNull);
        }
    }
    // Stray stdout writes must never reach the parent's NDJSON stream.
    dup2(STDERR_FILENO, STDOUT_FILENO);

    std::string body;
    try
    {
        body = evaluate();
    }
    catch (const std::exception& e)
    {
        std::cerr << "query child failed: " << e.what() << "\n";
        close(fd);
        _exit(3);
    }
    const bool written = WriteAll(fd, body);
    close(fd);
    std::clog.flush();
    std::cout.flush();
    std::fflush(nullptr);
    _exit(written ? 0 : 3);
}

bool
ReapUntil(pid_t pid, Clock::time_point deadline, int& status)
{
    for (;;)
    {
        const pid_t r = waitpid(pid, &status, WNOHANG);
        if (r == pid)
        {
            return true;
        }
        if (r < 0 && errno != EINTR)
        {
            return false;
        }
        if (Clock::now() >= deadline)
        {
            return false;
        }
        usleep(1000);
    }
}

bool
TerminateAndReap(pid_t pid, int& status, double grace_s)
{
    kill(pid, SIGTERM);
    const auto grace = Clock::now() + std::chrono::duration_cast<Clock::duration>(
                                          std::chrono::duration<double>(grace_s));
    if (ReapUntil(pid, grace, status))
    {
        return true;
    }
    kill(pid, SIGKILL);
    for (;;)
    {
        const pid_t r = waitpid(pid, &status, 0);
        if (r == pid)
        {
            return true;
        }
        if (r < 0 && errno != EINTR)
        {
            return false;
        }
    }
}

// Forks one child, drains its pipe while it runs, and always reaps it.
bool
RunChild(const std::function<std::string()>& evaluate,
         const QueryConfig& policy,
         std::ostream& out,
         std::string& body,
         std::string& failure)
{
    out.flush();
    std::cout.flush();
    std::clog.flush();
    std::cerr.flush();
    std::fflush(nullptr);

    int fds[2];
    if (pipe(fds) != 0)
    {
        failure = std::string("pipe failed: ") + std::strerror(errno);
        return false;
    }
    const pid_t pid = fork();
    if (pid < 0)
    {
        failure = std::string("fork failed: ") + std::strerror(errno);
        close(fds[0]);
        close(fds[1]);
        return false;
    }
    if (pid == 0)
    {
        close(fds[0]);
        ChildMain(evaluate, policy, fds[1]);
    }
    close(fds[1]);
    g_activeChild = static_cast<std::sig_atomic_t>(pid);

    const auto deadline =
        Clock::now() + std::chrono::duration_cast<Clock::duration>(
                           std::chrono::duration<double>(policy.child_deadline_s));
    bool timedOut = false;
    bool oversize = false;
    std::string readError;
    char buf[65536];
    for (;;)
    {
        const auto remaining =
            std::chrono::duration_cast<std::chrono::milliseconds>(deadline - Clock::now()).count();
        if (remaining <= 0)
        {
            timedOut = true;
            break;
        }
        pollfd pfd{fds[0], POLLIN, 0};
        const int rc = poll(&pfd, 1, static_cast<int>(std::min<long long>(remaining, 1000)));
        if (rc < 0)
        {
            if (errno == EINTR)
            {
                continue;
            }
            readError = std::strerror(errno);
            break;
        }
        if (rc == 0)
        {
            continue;
        }
        const ssize_t n = read(fds[0], buf, sizeof(buf));
        if (n < 0)
        {
            if (errno == EINTR || errno == EAGAIN)
            {
                continue;
            }
            readError = std::strerror(errno);
            break;
        }
        if (n == 0)
        {
            break;
        }
        if (body.size() + static_cast<std::size_t>(n) > policy.max_child_response_bytes)
        {
            oversize = true;
            break;
        }
        body.append(buf, static_cast<std::size_t>(n));
    }
    close(fds[0]);

    int status = 0;
    const bool aborted = timedOut || oversize || !readError.empty();
    bool reaped = !aborted && ReapUntil(pid, deadline, status);
    if (!reaped)
    {
        timedOut = timedOut || (!oversize && readError.empty());
        reaped = TerminateAndReap(pid, status, policy.terminate_grace_s);
    }
    g_activeChild = 0;

    if (timedOut)
    {
        failure = "child exceeded the " + std::to_string(policy.child_deadline_s) + " s deadline";
    }
    else if (oversize)
    {
        failure =
            "child response exceeds " + std::to_string(policy.max_child_response_bytes) + " bytes";
    }
    else if (!readError.empty())
    {
        failure = "reading child output failed: " + readError;
    }
    else if (!reaped)
    {
        failure = "could not reap child process";
    }
    else if (WIFSIGNALED(status))
    {
        failure = "child terminated by signal " + std::to_string(WTERMSIG(status));
    }
    else if (!WIFEXITED(status) || WEXITSTATUS(status) != 0)
    {
        failure = "child exited with status " +
                  std::to_string(WIFEXITED(status) ? WEXITSTATUS(status) : -1);
    }
    return failure.empty();
}

} // namespace mesh_sim::query

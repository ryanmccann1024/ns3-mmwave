/* -*- Mode: C++; c-file-style: "gnu"; indent-tabs-mode:nil; -*- */
/**
 * @file loader-test.cc
 * @brief Unit tests for the INI parser, string/path helpers, ConfigLoader
 *        defaults and JSON parsing, and domain struct defaults.
 *
 * Standalone binary, no ns-3 dependency. Every fixture is written at runtime
 * into a unique temp directory that is removed afterwards.
 * Build and run: `make -C tests/unit/loader test`.
 */

#include "src/config/config-loader.h"
#include "src/domain/sim-config.h"
#include "src/util/ini-parser.h"
#include "src/util/string-utils.h"
#include "third_party/json.hpp"

#include <chrono>
#include <cmath>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <random>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <sys/wait.h>
#include <unistd.h>

using namespace mesh_sim;
namespace fs = std::filesystem;

// ---- helpers ----

static int g_pass = 0;
static int g_fail = 0;

static void
check(bool cond, const std::string& name)
{
    if (cond)
    {
        ++g_pass;
    }
    else
    {
        ++g_fail;
        std::cerr << "FAIL: " << name << "\n";
    }
}

static bool
near(double a, double b)
{
    return std::fabs(a - b) < 1e-9;
}

/// Runs @p fn and reports whether it threw an exception of type @p E.
template <typename E>
static bool
throwsType(const std::function<void()>& fn, std::string* what = nullptr)
{
    try
    {
        fn();
    }
    catch (const E& e)
    {
        if (what)
        {
            *what = e.what();
        }
        return true;
    }
    catch (...)
    {
        return false;
    }
    return false;
}

namespace
{

/// Unique temp directory removed on destruction.
class TempDir
{
  public:
    TempDir()
    {
        static int                counter = 0;
        static std::random_device rd;
        static const auto         salt = rd();
        m_dir = fs::temp_directory_path() /
                ("mesh-sim-loader-test-" + std::to_string(::getpid()) + "-" +
                 std::to_string(salt) + "-" + std::to_string(++counter));
        fs::remove_all(m_dir);
        fs::create_directories(m_dir);
    }

    ~TempDir()
    {
        std::error_code ec;
        fs::remove_all(m_dir, ec);
    }

    const fs::path& path() const { return m_dir; }

    /// Writes @p content to @p rel (creating parent dirs); returns the full path.
    std::string write(const std::string& rel, const std::string& content) const
    {
        fs::path p = m_dir / rel;
        fs::create_directories(p.parent_path());
        std::ofstream f(p, std::ios::binary);
        f << content;
        return p.string();
    }

  private:
    fs::path m_dir;
};

const char* kOneNode = R"([{"id":"n0"}])";

/// Writes run.ini (with an explicit output dir unless @p ini sets one) and nodes.json.
std::string
writeScenario(const TempDir& d, const std::string& ini, const std::string& nodes = kOneNode)
{
    d.write("nodes.json", nodes);
    return d.write("run.ini", ini);
}

}  // namespace

// ===========================================================================
// ini-parser
// ===========================================================================

static void
test_ini_missing_file_throws()
{
    TempDir d;
    std::string what;
    bool threw = throwsType<std::runtime_error>(
        [&] { parseIni((d.path() / "nope.ini").string()); }, &what);
    check(threw, "parseIni on missing file throws std::runtime_error");
    check(what.find("nope.ini") != std::string::npos,
          "parseIni missing-file message names the path");
}

static void
test_ini_empty_file()
{
    TempDir d;
    auto p = d.write("e.ini", "");
    check(parseIni(p).empty(), "empty file yields empty IniMap");
    auto q = d.write("c.ini", "# only comments\n; another\n\n   \n");
    check(parseIni(q).empty(), "comment/blank-only file yields empty IniMap");
}

static void
test_ini_sections_and_trimming()
{
    TempDir d;
    auto p = d.write("a.ini",
                     "[  channel  ]\n"
                     "  frequency_ghz   =   28.5  \n"
                     "\tscenario\t=\tUMa\t\n"
                     "[Scenario]\n"
                     "Name = Mixed\n");
    auto ini = parseIni(p);
    check(ini.count("channel") == 1, "section name trimmed of whitespace");
    check(iniGet(ini, "channel", "frequency_ghz") == "28.5", "key and value trimmed (spaces)");
    check(iniGet(ini, "channel", "scenario") == "UMa", "key and value trimmed (tabs)");
    check(ini.count("Scenario") == 1 && ini.count("scenario") == 0,
          "section names stored case-sensitively");
    check(iniGet(ini, "Scenario", "Name") == "Mixed", "key stored case-sensitively");
    check(iniGet(ini, "Scenario", "name", "absent") == "absent",
          "lookup is case-sensitive (different case -> default)");
}

static void
test_ini_keys_before_section()
{
    TempDir d;
    auto p = d.write("g.ini", "top = 1\n[s]\nk = v\n");
    auto ini = parseIni(p);
    check(iniGet(ini, "", "top") == "1", "key before any section stored under \"\"");
    check(iniGet(ini, "s", "top", "none") == "none", "global key not leaked into later section");
}

static void
test_ini_split_on_first_equals()
{
    TempDir d;
    auto p = d.write("eq.ini", "[s]\nexpr = a=b=c\nempty =\n= novalue_key\n");
    auto ini = parseIni(p);
    check(iniGet(ini, "s", "expr") == "a=b=c", "value keeps '=' after the first one");
    check(ini["s"].count("empty") == 1 && iniGet(ini, "s", "empty", "def") == "",
          "present key with empty value stored as empty string (not default)");
    check(ini["s"].count("") == 1 && iniGet(ini, "s", "") == "novalue_key",
          "'= v' line stores an empty key");
}

static void
test_ini_duplicate_keys_and_sections()
{
    TempDir d;
    auto p = d.write("dup.ini", "[a]\nx = 1\nx = 2\n[b]\ny = 3\n[a]\nz = 4\nx = 5\n");
    auto ini = parseIni(p);
    check(iniGet(ini, "a", "x") == "5", "repeated key keeps the last value");
    check(iniGet(ini, "a", "z") == "4", "re-opened section merges keys");
    check(iniGet(ini, "b", "y") == "3", "other section unaffected by reopen");
    check(ini.size() == 2, "re-opened section does not create a duplicate entry");
}

static void
test_ini_comments_stripped()
{
    TempDir d;
    auto p = d.write("cm.ini",
                     "[s] # header comment\n"
                     "a = value # trailing hash\n"
                     "b = value ; trailing semicolon\n"
                     "c = x;y#z\n"
                     "# d = commented\n"
                     "; e = commented\n"
                     "f = Low Loss\n");
    auto ini = parseIni(p);
    check(ini.count("s") == 1, "comment after section header stripped");
    check(iniGet(ini, "s", "a") == "value", "'#' comment stripped and value trimmed");
    check(iniGet(ini, "s", "b") == "value", "';' comment stripped and value trimmed");
    check(iniGet(ini, "s", "c") == "x", "value truncated at first '#'/';'");
    check(ini["s"].count("d") == 0 && ini["s"].count("e") == 0, "full-line comments skipped");
    check(iniGet(ini, "s", "f") == "Low Loss", "interior whitespace in value preserved");
}

static void
test_ini_lines_without_equals_skipped()
{
    TempDir d;
    auto p = d.write("ne.ini", "[s]\njunk line\n[unterminated\nk = v\n");
    auto ini = parseIni(p);
    check(ini.size() == 1 && ini.count("s") == 1,
          "unterminated '[' line is neither a section nor a key");
    check(ini["s"].size() == 1 && iniGet(ini, "s", "k") == "v",
          "lines without '=' are skipped; following key stays in current section");
}

static void
test_ini_crlf_line_endings()
{
    TempDir d;
    auto p = d.write("crlf.ini", "[s]\r\nk = v\r\nb = true\r\n[t]\r\nx=1\r\n");
    auto ini = parseIni(p);
    check(ini.count("s") == 1 && ini.count("t") == 1, "CRLF section headers recognised");
    check(iniGet(ini, "s", "k") == "v", "CRLF value has no trailing '\\r'");
    check(iniGetBool(ini, "s", "b", false), "CRLF bool parses as true");
    check(iniGet(ini, "t", "x") == "1", "CRLF compact key=value parsed");
}

static void
test_ini_no_trailing_newline()
{
    TempDir d;
    auto p = d.write("nt.ini", "[s]\nk = last");
    check(iniGet(parseIni(p), "s", "k") == "last", "last line without newline parsed");
}

static void
test_ini_get_defaults()
{
    IniMap ini;
    ini["s"]["k"] = "v";
    check(iniGet(ini, "s", "k", "d") == "v", "iniGet returns stored value");
    check(iniGet(ini, "missing", "k", "d") == "d", "iniGet missing section -> default");
    check(iniGet(ini, "s", "missing", "d") == "d", "iniGet missing key -> default");
    check(iniGet(ini, "s", "missing") == "", "iniGet default argument is empty string");
}

static void
test_ini_get_bool()
{
    IniMap ini;
    const char* truthy[] = {"true", "TRUE", "True", "1", "yes", "YES", "Yes"};
    const char* falsy[]  = {"false", "0", "no", "on", "2", "", "y", "t", "truee"};
    for (const char* v : truthy)
    {
        ini["s"]["k"] = v;
        check(iniGetBool(ini, "s", "k", false), std::string("iniGetBool '") + v + "' is true");
    }
    for (const char* v : falsy)
    {
        ini["s"]["k"] = v;
        check(!iniGetBool(ini, "s", "k", true),
              std::string("iniGetBool '") + v + "' is false even with def=true");
    }
    check(iniGetBool(ini, "s", "absent", true), "iniGetBool absent key honours def=true");
    check(!iniGetBool(ini, "s", "absent", false), "iniGetBool absent key honours def=false");
    check(iniGetBool(ini, "nosec", "k", true), "iniGetBool absent section honours def=true");
}

// ===========================================================================
// string-utils
// ===========================================================================

static void
test_trim_str()
{
    check(trimStr("") == "", "trimStr empty");
    check(trimStr(" \t\r\n ") == "", "trimStr all-whitespace -> empty");
    check(trimStr(" \t\r\n a b \n\r\t ") == "a b", "trimStr strips all four chars, keeps interior");
    check(trimStr("abc") == "abc", "trimStr no-op");
    check(trimStr("\va\v") == "\va\v", "trimStr leaves vertical tab (not in documented set)");
}

static void
test_split_tab()
{
    check(splitTab("").empty(), "splitTab empty -> empty vector");
    auto one = splitTab("abc");
    check(one.size() == 1 && one[0] == "abc", "splitTab no tab -> single token");
    auto t = splitTab("a\t\tb");
    check(t.size() == 3 && t[0] == "a" && t[1] == "" && t[2] == "b",
          "splitTab consecutive tabs -> empty middle token");
    auto tr = splitTab("a\tb\t");
    check(tr.size() == 2 && tr[1] == "b", "splitTab trailing tab -> no trailing empty token");
    auto ld = splitTab("\ta");
    check(ld.size() == 2 && ld[0] == "" && ld[1] == "a", "splitTab leading tab -> leading empty");
    auto sp = splitTab("a b\tc");
    check(sp.size() == 2 && sp[0] == "a b", "splitTab does not split on spaces");
}

static void
test_to_iso8601()
{
    using namespace std::chrono;
    system_clock::time_point epoch{};
    check(toIso8601(epoch) == "1970-01-01T00:00:00Z", "toIso8601 epoch");
    check(toIso8601(system_clock::from_time_t(1774621800)) == "2026-03-27T14:30:00Z",
          "toIso8601 doc example 2026-03-27T14:30:00Z");
    check(toIso8601(system_clock::from_time_t(1709208000)) == "2024-02-29T12:00:00Z",
          "toIso8601 leap day");
    check(toIso8601(epoch + milliseconds(999)) == "1970-01-01T00:00:00Z",
          "toIso8601 discards sub-second precision");

    // Always UTC, regardless of the local TZ.
    const char* old = std::getenv("TZ");
    std::string saved = old ? old : "";
    setenv("TZ", "JST-9", 1);
    tzset();
    check(toIso8601(system_clock::from_time_t(1774621800)) == "2026-03-27T14:30:00Z",
          "toIso8601 ignores local TZ (JST-9)");
    if (old)
    {
        setenv("TZ", saved.c_str(), 1);
    }
    else
    {
        unsetenv("TZ");
    }
    tzset();

    std::regex fmt(R"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)");
    check(std::regex_match(toIso8601(system_clock::now()), fmt), "toIso8601 now matches format");
}

static void
test_resolve_path()
{
    check(resolvePath("/base", "") == "", "resolvePath empty path unchanged");
    check(resolvePath("/base", "/abs/x.json") == "/abs/x.json", "resolvePath absolute unchanged");
    check(resolvePath("/base", "rel/x.json") == "/base/rel/x.json", "resolvePath relative joined");
    check(resolvePath("/base/", "x.json") == "/base/x.json", "resolvePath trailing-slash base");
    check(resolvePath("rel", "x.json") == "rel/x.json", "resolvePath relative base stays relative");
    check(resolvePath("/base", "../x.json") == "/base/../x.json",
          "resolvePath does not canonicalise");
    check(resolvePath("/base", "missing/file.json") == "/base/missing/file.json",
          "resolvePath does not check existence");
}

static void
test_dir_of()
{
    check(dirOf("run.ini") == ".", "dirOf bare filename -> '.'");
    check(dirOf("") == ".", "dirOf empty -> '.'");
    check(dirOf("a/b/run.ini") == "a/b", "dirOf relative path");
    check(dirOf("/a/b/run.ini") == "/a/b", "dirOf absolute path");
    check(dirOf("/run.ini") == "/", "dirOf file at root -> '/'");
    check(dirOf("./run.ini") == ".", "dirOf ./file -> '.'");
}

namespace
{

struct ChildResult
{
    bool        exited = false;
    int         code   = -1;
    std::string out;
    std::string err;
};

/// Runs parseSeedList(arg) in a forked child so std::exit(1) can be observed.
/// The child prints the parsed seeds comma-separated on stdout and exits 0.
ChildResult
runSeedListInChild(const std::string& arg)
{
    std::cout.flush();
    std::cerr.flush();
    int outp[2];
    int errp[2];
    ChildResult r;
    if (pipe(outp) != 0 || pipe(errp) != 0)
    {
        return r;
    }
    pid_t pid = fork();
    if (pid == 0)
    {
        dup2(outp[1], STDOUT_FILENO);
        dup2(errp[1], STDERR_FILENO);
        close(outp[0]);
        close(errp[0]);
        auto seeds = parseSeedList(arg);
        std::ostringstream ss;
        for (size_t i = 0; i < seeds.size(); ++i)
        {
            ss << (i ? "," : "") << seeds[i];
        }
        std::cout << ss.str();
        std::cout.flush();
        _exit(0);
    }
    close(outp[1]);
    close(errp[1]);
    auto drain = [](int fd) {
        std::string s;
        char        buf[256];
        ssize_t     n;
        while ((n = read(fd, buf, sizeof(buf))) > 0)
        {
            s.append(buf, static_cast<size_t>(n));
        }
        close(fd);
        return s;
    };
    r.out = drain(outp[0]);
    r.err = drain(errp[0]);
    int status = 0;
    waitpid(pid, &status, 0);
    r.exited = WIFEXITED(status);
    r.code   = r.exited ? WEXITSTATUS(status) : -1;
    return r;
}

}  // namespace

static void
test_seed_list_invalid_exits()
{
    auto r = runSeedListInChild("abc");
    check(r.exited && r.code == 1, "parseSeedList non-numeric token exits with code 1");
    check(r.err.find("Error: invalid seed value 'abc'") != std::string::npos,
          "parseSeedList prints 'Error: invalid seed value' naming the token");
    check(r.out.empty(), "parseSeedList exits before returning on bad token");

    r = runSeedListInChild("1,x,3");
    check(r.exited && r.code == 1, "parseSeedList bad middle token exits with code 1");
}

static void
test_seed_list_boundaries()
{
    auto r = runSeedListInChild("0,4294967295");
    check(r.exited && r.code == 0 && r.out == "0,4294967295",
          "parseSeedList accepts 0 and UINT32_MAX");

    r = runSeedListInChild(",,,");
    check(r.exited && r.code == 0 && r.out.empty(), "parseSeedList only commas -> empty");

    r = runSeedListInChild("3,1,2");
    check(r.out == "3,1,2", "parseSeedList preserves order (no sorting)");

    r = runSeedListInChild("5,5");
    check(r.out == "5,5", "parseSeedList keeps duplicates");
}

static void
test_seed_list_out_of_uint32_range()
{
    // string-utils.h: an out-of-uint32_t-range token exits 1 instead of wrapping.
    auto r = runSeedListInChild("4294967296");
    check(r.exited && r.code == 1,
          "parseSeedList 4294967296 (UINT32_MAX+1) exits 1 [got code " +
              std::to_string(r.code) + ", out '" + r.out + "']");

    // A signed token is not a valid seed.
    r = runSeedListInChild("-1");
    check(r.exited && r.code == 1,
          "parseSeedList -1 (out of uint32 range) exits 1 [got code " +
              std::to_string(r.code) + ", out '" + r.out + "']");
}

// ===========================================================================
// domain defaults
// ===========================================================================

static void
test_max_speed_for_type()
{
    check(MaxSpeedForType("vehicle") == 15.0, "MaxSpeedForType vehicle = 15 m/s");
    check(MaxSpeedForType("pedestrian") == 1.5, "MaxSpeedForType pedestrian = 1.5 m/s");
    check(MaxSpeedForType("drone") == 20.0, "MaxSpeedForType drone = 20 m/s");
    check(MaxSpeedForType("") == 20.0, "MaxSpeedForType empty -> drone default");
    check(MaxSpeedForType("Vehicle") == 20.0, "MaxSpeedForType is case-sensitive");
}

static void
test_rl_resolved_defaults()
{
    RlConfig rl;
    check(rl.control_mode == "legacy", "RlConfig control_mode default legacy");
    check(rl.controlled_indices.empty(), "RlConfig controlled_indices default empty");
    check(rl.num_slots == 0, "RlConfig num_slots default 0");
    check(rl.decision_interval_ticks == 1, "RlConfig decision_interval_ticks default 1");
    check(rl.num_ticks == 0, "RlConfig num_ticks default 0");
    TimingInfo ti;
    check(ti.elapsed_s == 0.0, "TimingInfo elapsed_s default 0");
}

// ===========================================================================
// ConfigLoader: defaults
// ===========================================================================

/// Minimal run.ini: only an output dir (so auto-path discovery is not needed).
static SimConfig
loadMinimal(const TempDir& d, const std::string& nodes = kOneNode)
{
    return ConfigLoader::Load(writeScenario(d, "[output]\ndir = out\n", nodes));
}

static void
test_loader_documented_defaults()
{
    TempDir d;
    SimConfig c = loadMinimal(d);
    // Values from the config-loader.h key table / run-ini-reference.md.
    check(c.scenario_name == "unnamed", "default name=unnamed");
    check(c.seed == 42 && c.run_id == 1, "default seed=42 run_id=1");
    check(near(c.duration_s, 10.0) && near(c.warmup_s, 0.0) && near(c.tick_s, 0.1),
          "default duration_s=10 warmup_s=0 tick_s=0.1");
    check(c.viz_tick_ms == 100, "default viz_tick_ms=100");
    const auto& ch = c.channel;
    check(near(ch.frequency_ghz, 28.0) && near(ch.tx_power_dbm, 30.0),
          "default frequency_ghz=28 tx_power_dbm=30");
    check(ch.scenario == "UMi" && ch.channel_model == "3gpp" && ch.condition_model == "auto",
          "default scenario=UMi channel_model=3gpp condition_model=auto");
    check(ch.blockage_enabled && ch.beamforming_model == "svd" && ch.amc_model == "shannon",
          "default blockage_enabled=true beamforming_model=svd amc_model=shannon");
    check(near(ch.noise_figure_db, 5.0) && near(ch.bandwidth_mhz, 400.0),
          "default noise_figure_db=5 bandwidth_mhz=400");
    check(near(ch.tx_array_gain_dbi, 12.0) && near(ch.rx_array_gain_dbi, 12.0),
          "default tx/rx_array_gain_dbi=12");
    const auto& n = ch.nyu;
    check(near(n.rf_bandwidth_mhz, 800.0) && n.shadowing_enabled &&
              near(n.pressure_mbar, 1013.25) && near(n.humidity_pct, 50.0) &&
              near(n.temperature_c, 20.0) && near(n.rain_rate_mm_hr, 0.0) &&
              !n.atmospheric_loss_enabled && !n.foliage_loss_enabled &&
              near(n.foliage_loss_db_m, 0.4) && n.o2i_loss_type == "Low Loss",
          "default [nyu_channel] values");
    const auto& t = c.mesh.traffic;
    check(t.model == "constant" && near(t.demand_mbps, 10.0) && near(t.arrival_rate_hz, 1.0) &&
              near(t.on_time_s, 1.0) && near(t.off_time_s, 1.0) &&
              near(t.holding_time_s, 0.0) && t.flow_topology == "all_pairs" &&
              t.random_pair_count == 3 && t.gateway_node_id.empty(),
          "default [traffic] values");
    check(c.mesh.routing.algorithm == "shortest_path" && c.mesh.routing.max_hops == 5,
          "default [routing] values");
    const auto& rl = c.rl;
    check(!rl.enabled && rl.controlled_node_id.empty() && rl.action_type == "discrete" &&
              rl.reward_type == "throughput" && rl.reward_type_alias.empty(),
          "default [rl] enabled/selector/action/reward");
    check(near(rl.step_size_m, 50.0) && near(rl.arrival_threshold_m, 1.0),
          "default step_size_m=50 arrival_threshold_m=1");
    check(near(rl.x_min, -1000) && near(rl.x_max, 2000) && near(rl.y_min, -1000) &&
              near(rl.y_max, 1000) && near(rl.z_min, 0) && near(rl.z_max, 100),
          "default [rl] bounds");
    check(rl.controlled_nodes.empty() && !rl.controlled_nodes_set &&
              rl.max_controlled_nodes == 0 && rl.action_profile == "move_2d" &&
              near(rl.decision_interval_s, 0.0),
          "default [rl] centralized keys");
    check(c.band == "mmwave" && c.band_source == "default", "default band mmwave/default");
    check(c.baseline.algorithm == "none", "default baseline algorithm none");
    check(c.jammers.empty() && c.buildings.empty(), "no jammers/buildings by default");
    check(c.nodes.size() == 1, "one node loaded");
}

static void
test_loader_defaults_match_simconfig_struct()
{
    // src/domain/CLAUDE.md: "Defaults in the structs must match the fallbacks in
    // ConfigLoader::Load ... the two can drift silently."
    TempDir   d;
    SimConfig c = loadMinimal(d);
    SimConfig s;

    // scenario_name is not compared: the struct default is "" by design and
    // the loader supplies "unnamed" (confirmed intentional).
    check(c.seed == s.seed && c.run_id == s.run_id, "struct seed/run_id match loader");
    check(c.duration_s == s.duration_s && c.warmup_s == s.warmup_s && c.tick_s == s.tick_s,
          "struct timing defaults match loader");
    check(c.viz_tick_ms == s.viz_tick_ms, "struct viz_tick_ms matches loader");
    check(c.band == s.band && c.band_source == s.band_source, "struct band matches loader");

    const auto &lc = c.channel, &sc = s.channel;
    check(lc.frequency_ghz == sc.frequency_ghz && lc.tx_power_dbm == sc.tx_power_dbm &&
              lc.scenario == sc.scenario && lc.channel_model == sc.channel_model &&
              lc.condition_model == sc.condition_model &&
              lc.blockage_enabled == sc.blockage_enabled &&
              lc.beamforming_model == sc.beamforming_model && lc.amc_model == sc.amc_model &&
              lc.noise_figure_db == sc.noise_figure_db && lc.bandwidth_mhz == sc.bandwidth_mhz &&
              lc.tx_array_gain_dbi == sc.tx_array_gain_dbi &&
              lc.rx_array_gain_dbi == sc.rx_array_gain_dbi,
          "struct ChannelConfig defaults match loader");
    const auto &ln = lc.nyu, &sn = sc.nyu;
    check(ln.rf_bandwidth_mhz == sn.rf_bandwidth_mhz &&
              ln.shadowing_enabled == sn.shadowing_enabled &&
              ln.pressure_mbar == sn.pressure_mbar && ln.humidity_pct == sn.humidity_pct &&
              ln.temperature_c == sn.temperature_c && ln.rain_rate_mm_hr == sn.rain_rate_mm_hr &&
              ln.atmospheric_loss_enabled == sn.atmospheric_loss_enabled &&
              ln.foliage_loss_enabled == sn.foliage_loss_enabled &&
              ln.foliage_loss_db_m == sn.foliage_loss_db_m &&
              ln.o2i_loss_type == sn.o2i_loss_type,
          "struct NyuChannelConfig defaults match loader");
    const auto &lt = c.mesh.traffic, &st = s.mesh.traffic;
    check(lt.model == st.model && lt.demand_mbps == st.demand_mbps &&
              lt.arrival_rate_hz == st.arrival_rate_hz && lt.on_time_s == st.on_time_s &&
              lt.off_time_s == st.off_time_s && lt.holding_time_s == st.holding_time_s &&
              lt.flow_topology == st.flow_topology &&
              lt.random_pair_count == st.random_pair_count &&
              lt.gateway_node_id == st.gateway_node_id,
          "struct TrafficConfig defaults match loader");
    check(c.mesh.routing.algorithm == s.mesh.routing.algorithm &&
              c.mesh.routing.max_hops == s.mesh.routing.max_hops,
          "struct RoutingConfig defaults match loader");
    const auto &lr = c.rl, &sr = s.rl;
    check(lr.enabled == sr.enabled && lr.controlled_node_id == sr.controlled_node_id &&
              lr.action_type == sr.action_type && lr.reward_type == sr.reward_type &&
              lr.reward_type_alias == sr.reward_type_alias &&
              lr.step_size_m == sr.step_size_m &&
              lr.arrival_threshold_m == sr.arrival_threshold_m && lr.x_min == sr.x_min &&
              lr.x_max == sr.x_max && lr.y_min == sr.y_min && lr.y_max == sr.y_max &&
              lr.z_min == sr.z_min && lr.z_max == sr.z_max &&
              lr.controlled_nodes == sr.controlled_nodes &&
              lr.controlled_nodes_set == sr.controlled_nodes_set &&
              lr.max_controlled_nodes == sr.max_controlled_nodes &&
              lr.action_profile == sr.action_profile &&
              lr.decision_interval_s == sr.decision_interval_s,
          "struct RlConfig INI-backed defaults match loader");
    check(lr.control_mode == sr.control_mode && lr.num_slots == sr.num_slots &&
              lr.decision_interval_ticks == sr.decision_interval_ticks &&
              lr.num_ticks == sr.num_ticks && lr.controlled_indices.empty(),
          "loader leaves RlConfig resolved fields at struct defaults");
    check(c.baseline.algorithm == s.baseline.algorithm, "struct BaselineConfig matches loader");
}

static void
test_loader_node_defaults_match_nodespec_struct()
{
    TempDir  d;
    SimConfig c = loadMinimal(d);
    const NodeSpec& l = c.nodes.at(0);
    NodeSpec        s;

    check(l.id == "n0", "node id parsed");
    check(l.role == "peer" && l.mobility == "fixed" && l.node_type == "drone",
          "loader node fallbacks role=peer mobility=fixed node_type=drone");

    // role/mobility/node_type are not compared with NodeSpec{}: the struct
    // leaves them "" by design and the loader supplies the defaults above
    // (confirmed intentional).

    check(l.position.x == s.position.x && l.position.y == s.position.y &&
              l.position.z == s.position.z,
          "absent position -> struct default (0,0,0)");
    check(l.velocity.vx == s.velocity.vx && l.velocity.vy == s.velocity.vy &&
              l.velocity.vz == s.velocity.vz,
          "absent velocity -> struct default (0,0,0)");
    check(l.random_walk.x_min == s.random_walk.x_min && l.random_walk.x_max == s.random_walk.x_max &&
              l.random_walk.y_min == s.random_walk.y_min &&
              l.random_walk.y_max == s.random_walk.y_max &&
              l.random_walk.speed_mps == s.random_walk.speed_mps,
          "absent random_walk -> struct default");
    check(l.waypoints.empty() && !l.tx_array_gain_dbi && !l.rx_array_gain_dbi,
          "absent waypoints/gains -> empty / nullopt");
}

// ===========================================================================
// ConfigLoader: every documented key is read
// ===========================================================================

static void
test_loader_all_keys_parsed()
{
    TempDir d;
    const std::string ini =
        "[scenario]\n"
        "name = full test\nseed = 7\nrun_id = 3\nduration_s = 20.5\nwarmup_s = 1.5\n"
        "tick_s = 0.25\nnodes_file = nodes.json\n"
        "[output]\ndir = out\nviz_tick_ms = 250\n"
        "[channel]\nband = sub-6\nfrequency_ghz = 2.4\ntx_power_dbm = 20\nscenario = RMa\n"
        "channel_model = nyu\ncondition_model = static_los\nblockage_enabled = false\n"
        "beamforming_model = analog\namc_model = silvus\nnoise_figure_db = 7.5\n"
        "bandwidth_mhz = 20\ntx_array_gain_dbi = 3\nrx_array_gain_dbi = 4\n"
        "[nyu_channel]\nrf_bandwidth_mhz = 100\nshadowing_enabled = no\npressure_mbar = 900\n"
        "humidity_pct = 80\ntemperature_c = -5\nrain_rate_mm_hr = 12.5\n"
        "atmospheric_loss_enabled = yes\nfoliage_loss_enabled = 1\nfoliage_loss_db_m = 0.9\n"
        "o2i_loss_type = High Loss\n"
        "[traffic]\nmodel = on_off\ndemand_mbps = 2.5\narrival_rate_hz = 4\non_time_s = 3\n"
        "off_time_s = 6\nholding_time_s = 9\nflow_topology = gateway\nrandom_pair_count = 11\n"
        "gateway_node_id = n0\n"
        "[routing]\nalgorithm = min_hop\nmax_hops = 0\n"
        "[rl]\nenabled = TRUE\ncontrolled_node_id = n0\naction_type = continuous\n"
        "reward_type = all_links_los\nstep_size_m = 5\narrival_threshold_m = 2\n"
        "x_min = -1\nx_max = 1\ny_min = -2\ny_max = 2\nz_min = 3\nz_max = 4\n"
        "controlled_nodes = n0\nmax_controlled_nodes = 8\naction_profile = move_2d\n"
        "decision_interval_s = 0.5\n"
        "[baseline]\nalgorithm = geometric\n";
    SimConfig c = ConfigLoader::Load(writeScenario(d, ini));

    check(c.scenario_name == "full test" && c.seed == 7 && c.run_id == 3,
          "[scenario] name/seed/run_id parsed");
    check(near(c.duration_s, 20.5) && near(c.warmup_s, 1.5) && near(c.tick_s, 0.25),
          "[scenario] duration/warmup/tick parsed");
    check(c.viz_tick_ms == 250, "[output] viz_tick_ms parsed");
    check(c.band == "sub-6" && c.band_source == "run.ini", "[channel] band parsed");
    const auto& ch = c.channel;
    check(near(ch.frequency_ghz, 2.4) && near(ch.tx_power_dbm, 20) && ch.scenario == "RMa",
          "[channel] frequency/power/scenario parsed");
    check(ch.channel_model == "nyu" && ch.condition_model == "static_los",
          "[channel] channel_model/condition_model parsed");
    check(!ch.blockage_enabled, "[channel] blockage_enabled=false parsed");
    check(ch.beamforming_model == "analog", "[channel] beamforming_model parsed");
    check(ch.amc_model == "silvus" && near(ch.noise_figure_db, 7.5) &&
              near(ch.bandwidth_mhz, 20),
          "[channel] amc/noise/bandwidth parsed");
    check(near(ch.tx_array_gain_dbi, 3) && near(ch.rx_array_gain_dbi, 4),
          "[channel] array gains parsed");
    const auto& n = ch.nyu;
    check(near(n.rf_bandwidth_mhz, 100) && !n.shadowing_enabled && near(n.pressure_mbar, 900) &&
              near(n.humidity_pct, 80) && near(n.temperature_c, -5) &&
              near(n.rain_rate_mm_hr, 12.5),
          "[nyu_channel] numeric + shadowing parsed");
    check(n.atmospheric_loss_enabled && n.foliage_loss_enabled && near(n.foliage_loss_db_m, 0.9),
          "[nyu_channel] loss toggles parsed (yes / 1)");
    check(n.o2i_loss_type == "High Loss", "[nyu_channel] o2i_loss_type with space parsed");
    const auto& t = c.mesh.traffic;
    check(t.model == "on_off" && near(t.demand_mbps, 2.5) && near(t.arrival_rate_hz, 4) &&
              near(t.on_time_s, 3) && near(t.off_time_s, 6) && near(t.holding_time_s, 9),
          "[traffic] model and timing parsed");
    check(t.flow_topology == "gateway" && t.random_pair_count == 11 && t.gateway_node_id == "n0",
          "[traffic] topology parsed");
    check(c.mesh.routing.algorithm == "min_hop" && c.mesh.routing.max_hops == 0,
          "[routing] parsed (max_hops 0 kept)");
    const auto& rl = c.rl;
    check(rl.enabled && rl.controlled_node_id == "n0" && rl.action_type == "continuous" &&
              rl.reward_type == "all_links_los" && rl.reward_type_alias.empty(),
          "[rl] enabled/selector/action/reward parsed");
    check(near(rl.step_size_m, 5) && near(rl.arrival_threshold_m, 2), "[rl] step/arrival parsed");
    check(near(rl.x_min, -1) && near(rl.x_max, 1) && near(rl.y_min, -2) && near(rl.y_max, 2) &&
              near(rl.z_min, 3) && near(rl.z_max, 4),
          "[rl] bounds parsed");
    check(rl.controlled_nodes == "n0" && rl.controlled_nodes_set &&
              rl.max_controlled_nodes == 8 && rl.action_profile == "move_2d" &&
              near(rl.decision_interval_s, 0.5),
          "[rl] centralized keys parsed");
    check(c.baseline.algorithm == "geometric", "[baseline] algorithm parsed");
}

static void
test_loader_crlf_run_ini()
{
    TempDir d;
    SimConfig c = ConfigLoader::Load(writeScenario(
        d,
        "[scenario]\r\nname = crlf\r\nseed = 9\r\n[output]\r\ndir = out\r\n"
        "[channel]\r\nchannel_model = nyu\r\nblockage_enabled = false\r\n"));
    check(c.scenario_name == "crlf" && c.seed == 9, "CRLF run.ini string/int parsed");
    check(c.channel.channel_model == "nyu", "CRLF channel_model has no '\\r' (no throw)");
    check(!c.channel.blockage_enabled, "CRLF bool parsed");
    check(c.output_dir == (d.path() / "out").string(), "CRLF output dir has no '\\r'");
}

static void
test_loader_misplaced_and_unknown_keys()
{
    TempDir d;
    SimConfig c = ConfigLoader::Load(writeScenario(
        d,
        "seed = 99\n"                           // before any section
        "[output]\ndir = out\n"
        "[bogus]\nfoo = bar\n"                  // unknown section
        "[channel]\nseed = 5\naction_set = x\n" // known key in the wrong section
        "[rl]\ndimensions = 3\nnum_slots = 9\ncontrol_mode = centralized\n"
        "[scenario]\nmax_hops = 1\ncontrolled_nodes = all\n"));
    check(c.seed == 42, "seed outside [scenario] ignored");
    check(c.mesh.routing.max_hops == 5, "routing key in [scenario] ignored");
    check(!c.rl.controlled_nodes_set && c.rl.controlled_nodes.empty(),
          "controlled_nodes outside [rl] does not select centralized mode");
    check(c.rl.num_slots == 0 && c.rl.control_mode == "legacy",
          "resolved RL fields never read from INI");
}

static void
test_loader_duplicate_key_last_wins()
{
    TempDir d;
    SimConfig c = ConfigLoader::Load(
        writeScenario(d, "[output]\ndir = out\n[scenario]\nseed = 1\nseed = 2\n"));
    check(c.seed == 2, "duplicate seed key: last value wins");
}

static void
test_loader_bool_semantics()
{
    TempDir d;
    SimConfig c = ConfigLoader::Load(writeScenario(
        d,
        "[output]\ndir = out\n"
        "[channel]\nblockage_enabled = on\n"
        "[nyu_channel]\nshadowing_enabled =\natmospheric_loss_enabled = Yes\n"
        "[rl]\nenabled = 1\n"));
    check(!c.channel.blockage_enabled, "blockage_enabled 'on' -> false (unrecognised)");
    check(!c.channel.nyu.shadowing_enabled,
          "shadowing_enabled present-but-empty -> false, not the default true");
    check(c.channel.nyu.atmospheric_loss_enabled, "atmospheric_loss_enabled 'Yes' -> true");
    check(c.rl.enabled, "rl enabled '1' -> true");
}

static void
test_loader_controlled_nodes_presence()
{
    {
        TempDir d;
        SimConfig c = ConfigLoader::Load(
            writeScenario(d, "[output]\ndir = out\n[rl]\ncontrolled_nodes =\n"));
        check(c.rl.controlled_nodes_set && c.rl.controlled_nodes.empty(),
              "empty controlled_nodes key still sets controlled_nodes_set");
    }
    {
        TempDir d;
        SimConfig c = ConfigLoader::Load(
            writeScenario(d, "[output]\ndir = out\n[rl]\nenabled = true\n"));
        check(!c.rl.controlled_nodes_set, "[rl] without controlled_nodes leaves it unset");
    }
    {
        TempDir d;
        SimConfig c = ConfigLoader::Load(
            writeScenario(d, "[output]\ndir = out\n[rl]\ncontrolled_nodes = all # c\n"));
        check(c.rl.controlled_nodes_set && c.rl.controlled_nodes == "all",
              "controlled_nodes = all (inline comment stripped)");
    }
}

static void
test_loader_band_and_baseline_blank()
{
    TempDir d;
    SimConfig c = ConfigLoader::Load(writeScenario(
        d, "[output]\ndir = out\n[channel]\nband =   sub-6   \n[baseline]\nalgorithm =\n"));
    check(c.band == "sub-6", "band value trimmed");
    // run-ini-reference.md: "the binary also treats a blank value as none".
    check(c.baseline.algorithm == "none", "blank [baseline] algorithm -> none");
}

static void
test_loader_no_range_checks()
{
    // config-loader.h: "does not range-check values (see ValidateConfig)".
    TempDir d;
    SimConfig c = ConfigLoader::Load(writeScenario(
        d,
        "[scenario]\nduration_s = -5\ntick_s = 0\nwarmup_s = 100\n[output]\ndir = out\n"
        "[channel]\nbandwidth_mhz = -1\nscenario = Mars\namc_model = bogus\n"
        "[traffic]\nmodel = nonsense\n"
        "[rl]\nx_min = 10\nx_max = -10\nmax_controlled_nodes = -3\naction_profile = fly\n",
        "[]"));
    check(near(c.duration_s, -5) && near(c.tick_s, 0) && near(c.warmup_s, 100),
          "invalid timing loaded without throwing");
    check(near(c.channel.bandwidth_mhz, -1) && c.channel.scenario == "Mars" &&
              c.channel.amc_model == "bogus",
          "invalid channel values loaded without throwing");
    check(c.mesh.traffic.model == "nonsense", "invalid traffic model loaded");
    check(near(c.rl.x_min, 10) && near(c.rl.x_max, -10) && c.rl.max_controlled_nodes == -3 &&
              c.rl.action_profile == "fly",
          "invalid rl values loaded");
    check(c.nodes.empty(), "empty nodes array loads zero nodes without throwing");
}

static void
test_loader_channel_model_validation()
{
    for (const std::string cm : {"bogus", "NYU", "3GPP", ""})
    {
        TempDir     d;
        std::string what;
        auto        p = writeScenario(
            d, "[output]\ndir = out\n[channel]\nchannel_model = " + cm + "\n");
        bool threw = throwsType<std::runtime_error>([&] { ConfigLoader::Load(p); }, &what);
        check(threw, "channel_model '" + cm + "' throws std::runtime_error");
        check(what.find("'" + cm + "'") != std::string::npos,
              "channel_model error names the value '" + cm + "'");
    }
    TempDir d;
    auto    p = writeScenario(d, "[output]\ndir = out\n[channel]\nchannel_model = nyu\n");
    check(!throwsType<std::exception>([&] { ConfigLoader::Load(p); }), "channel_model nyu accepted");
}

static void
test_loader_bad_numbers_throw()
{
    struct Case
    {
        std::string section, key, value;
        bool        outOfRange;
    };
    const std::vector<Case> cases = {
        {"scenario", "seed", "abc", false},
        {"scenario", "seed", "", false},  // present but empty: not the default
        {"scenario", "run_id", "x1", false},
        {"scenario", "duration_s", "ten", false},
        {"scenario", "tick_s", "", false},
        {"output", "viz_tick_ms", "fast", false},
        {"output", "viz_tick_ms", "999999999999999999999999", true},
        {"channel", "frequency_ghz", "1e999", true},
        {"channel", "noise_figure_db", "n/a", false},
        {"nyu_channel", "pressure_mbar", "high", false},
        {"traffic", "random_pair_count", "many", false},
        {"routing", "max_hops", "lots", false},
        {"rl", "step_size_m", "big", false},
        {"rl", "max_controlled_nodes", "all", false},
        {"rl", "decision_interval_s", "often", false},
    };
    for (const auto& k : cases)
    {
        TempDir     d;
        std::string ini = "[output]\ndir = out\n";
        if (k.section == "output")
        {
            ini = "[output]\ndir = out\n" + k.key + " = " + k.value + "\n";
        }
        else
        {
            ini += "[" + k.section + "]\n" + k.key + " = " + k.value + "\n";
        }
        auto p = writeScenario(d, ini);
        bool ok = k.outOfRange
                      ? throwsType<std::out_of_range>([&] { ConfigLoader::Load(p); })
                      : throwsType<std::invalid_argument>([&] { ConfigLoader::Load(p); });
        check(ok, "[" + k.section + "] " + k.key + " = '" + k.value + "' throws " +
                      (k.outOfRange ? "std::out_of_range" : "std::invalid_argument"));
    }
}

static void
test_loader_missing_run_ini()
{
    TempDir d;
    check(throwsType<std::runtime_error>(
              [&] { ConfigLoader::Load((d.path() / "missing.ini").string()); }),
          "missing run.ini throws std::runtime_error");
}

// ===========================================================================
// ConfigLoader: output directory
// ===========================================================================

static void
test_loader_output_dir_relative_and_absolute()
{
    {
        TempDir d;
        SimConfig c = ConfigLoader::Load(writeScenario(d, "[output]\ndir = results/a\n"));
        check(c.output_dir == (d.path() / "results/a").string(),
              "relative [output] dir resolved against run.ini dir");
        check(!fs::exists(d.path() / "results"), "Load creates no output directory");
    }
    {
        TempDir     d;
        std::string abs = (d.path() / "abs-out").string();
        SimConfig   c   = ConfigLoader::Load(writeScenario(d, "[output]\ndir = " + abs + "\n"));
        check(c.output_dir == abs, "absolute [output] dir kept unchanged");
    }
}

/// Builds a fake mesh-sim root (sim.cc + inputs/) and returns the run.ini path at @p rel.
static std::string
fakeRootScenario(const TempDir& d, const std::string& rel)
{
    d.write("root/sim.cc", "// fake\n");
    fs::create_directories(d.path() / "root/inputs");
    d.write((fs::path("root") / rel).parent_path() / "nodes.json", kOneNode);
    return d.write((fs::path("root") / rel).string(), "[scenario]\nname = auto\n");
}

static bool
autoOutputDirOk(const std::string& out, const fs::path& root, const std::string& label)
{
    fs::path    expectBase = fs::weakly_canonical(root) / "outputs";
    std::string base       = expectBase.string() + "/";
    bool        prefix     = out.compare(0, base.size(), base) == 0;
    std::string tail       = prefix ? out.substr(base.size()) : "";
    bool fmt = std::regex_match(tail, std::regex(R"(\d{4}-\d{2}/\d{2}/\d{2}-\d{2}-\d{2})"));
    check(prefix, label + ": auto output dir under <root>/outputs/ (got '" + out + "')");
    check(fmt, label + ": auto output dir tail is YYYY-MM/DD/HH-MM-SS (got '" + tail + "')");
    return prefix && fmt;
}

static void
test_loader_output_dir_auto_three_levels()
{
    TempDir d;
    auto    p = fakeRootScenario(d, "inputs/baselines/foo/run.ini");

    std::time_t before = std::time(nullptr);
    SimConfig   c      = ConfigLoader::Load(p);
    std::time_t after  = std::time(nullptr);
    autoOutputDirOk(c.output_dir, d.path() / "root", "three levels");

    // The timestamp comes from the local clock (config-loader.h).
    auto stamp = [](std::time_t t) {
        std::ostringstream s;
        s << std::put_time(std::localtime(&t), "%Y-%m/%d/%H-%M-%S");
        return s.str();
    };
    bool matches = false;
    for (std::time_t t = before; t <= after; ++t)
    {
        matches = matches || (c.output_dir.size() >= 19 &&
                                 c.output_dir.substr(c.output_dir.size() - 19) == stamp(t));
    }
    check(matches, "auto output dir timestamp equals local time of the call");
    check(!fs::exists(d.path() / "root/outputs"), "auto output dir not created by Load");
}

static void
test_loader_output_dir_auto_deeper_nesting()
{
    // config-loader.cc:228-230: scenarios may be nested deeper than three levels;
    // the root is located by searching upwards for sim.cc + inputs/.
    TempDir d;
    auto    p = fakeRootScenario(d, "inputs/custom/calfex/06-24/1420-1430/run.ini");
    SimConfig c = ConfigLoader::Load(p);
    autoOutputDirOk(c.output_dir, d.path() / "root", "five levels");
}

static void
test_loader_output_dir_auto_without_root_throws()
{
    TempDir     d;
    auto        p = writeScenario(d, "[scenario]\nname = noroot\n");
    std::string what;
    bool threw = throwsType<std::runtime_error>([&] { ConfigLoader::Load(p); }, &what);
    check(threw, "empty [output] dir outside any mesh-sim root throws std::runtime_error");
    check(what.find("mesh-sim root") != std::string::npos,
          "no-root error mentions the mesh-sim root");

    // A blank value behaves like an absent key.
    TempDir d2;
    auto    p2 = writeScenario(d2, "[output]\ndir =\n");
    check(throwsType<std::runtime_error>([&] { ConfigLoader::Load(p2); }),
          "blank [output] dir also takes the auto path");
}

static void
test_loader_bare_relative_run_ini_path()
{
    // dirOf("run.ini") is "." so nodes.json and the output dir resolve from cwd.
    TempDir d;
    writeScenario(d, "[output]\ndir = out\n");
    fs::path  old = fs::current_path();
    fs::current_path(d.path());
    SimConfig c;
    bool      ok = !throwsType<std::exception>([&] { c = ConfigLoader::Load("run.ini"); });
    fs::current_path(old);
    check(ok && c.nodes.size() == 1, "bare 'run.ini' path loads nodes.json from cwd");
    check(c.output_dir == "./out", "bare 'run.ini' path: output dir is './out'");
}

// ===========================================================================
// ConfigLoader: nodes file
// ===========================================================================

static void
test_loader_nodes_full_entry()
{
    TempDir d;
    const char* nodes = R"([
      {"id":"a","role":"relay","mobility":"waypoint","node_type":"vehicle",
       "position":{"x":1.5,"y":-2,"z":30},
       "velocity":{"vx":1,"vy":2,"vz":-3},
       "random_walk":{"bounds":{"x_min":-5,"x_max":5,"y_min":-6,"y_max":6},"speed_mps":2.5},
       "waypoints":[{"t":0,"x":1,"y":2,"z":3},{"t":10.5,"x":4,"y":5,"z":6}],
       "tx_array_gain_dbi":7.5,"rx_array_gain_dbi":0.0,
       "unknown_field":"ignored"},
      {"id":"b","node_type":"pedestrian"}
    ])";
    SimConfig c = loadMinimal(d, nodes);
    check(c.nodes.size() == 2 && c.nodes[0].id == "a" && c.nodes[1].id == "b",
          "nodes loaded in file order");
    const NodeSpec& a = c.nodes[0];
    check(a.role == "relay" && a.mobility == "waypoint" && a.node_type == "vehicle",
          "node role/mobility/node_type parsed");
    check(near(a.position.x, 1.5) && near(a.position.y, -2) && near(a.position.z, 30),
          "node position parsed (int and float JSON numbers)");
    check(near(a.velocity.vx, 1) && near(a.velocity.vy, 2) && near(a.velocity.vz, -3),
          "node velocity parsed");
    check(near(a.random_walk.x_min, -5) && near(a.random_walk.x_max, 5) &&
              near(a.random_walk.y_min, -6) && near(a.random_walk.y_max, 6) &&
              near(a.random_walk.speed_mps, 2.5),
          "node random_walk parsed");
    check(a.waypoints.size() == 2 && near(a.waypoints[1].t, 10.5) &&
              near(a.waypoints[1].x, 4) && near(a.waypoints[1].y, 5) &&
              near(a.waypoints[1].z, 6) && near(a.waypoints[0].z, 3),
          "node waypoints parsed in order");
    check(a.tx_array_gain_dbi && near(*a.tx_array_gain_dbi, 7.5), "node tx gain parsed");
    check(a.rx_array_gain_dbi && *a.rx_array_gain_dbi == 0.0,
          "node rx gain of 0 is set (not treated as absent)");
    const NodeSpec& b = c.nodes[1];
    check(b.node_type == "pedestrian" && b.mobility == "fixed" && b.role == "peer",
          "second node gets its own fields + fallbacks");
    check(!b.tx_array_gain_dbi && !b.rx_array_gain_dbi, "unset node gains stay nullopt");
}

static void
test_loader_nodes_partial_objects()
{
    TempDir d;
    const char* nodes = R"([
      {"id":"p","position":{"x":5},"velocity":{"vy":2}},
      {"id":"r1","random_walk":{"speed_mps":3}},
      {"id":"r2","random_walk":{"bounds":{"x_min":-7}}},
      {"id":"r3","random_walk":{}},
      {"id":"w","waypoints":[{"t":1},{"x":2}],"tx_array_gain_dbi":3}
    ])";
    SimConfig c = loadMinimal(d, nodes);
    const auto& n = c.nodes;
    check(n.size() == 5, "five partial nodes loaded");
    check(near(n[0].position.x, 5) && near(n[0].position.y, 0) && near(n[0].position.z, 0),
          "partial position: missing y/z -> 0");
    check(near(n[0].velocity.vx, 0) && near(n[0].velocity.vy, 2) && near(n[0].velocity.vz, 0),
          "partial velocity: missing components -> 0");
    check(near(n[1].random_walk.speed_mps, 3) && near(n[1].random_walk.x_min, -100) &&
              near(n[1].random_walk.y_max, 100),
          "random_walk without bounds keeps default bounds");
    check(near(n[2].random_walk.x_min, -7) && near(n[2].random_walk.x_max, 100) &&
              near(n[2].random_walk.y_min, -100) && near(n[2].random_walk.y_max, 100) &&
              near(n[2].random_walk.speed_mps, 1.5),
          "partial random_walk bounds -> per-field defaults, speed 1.5");
    check(near(n[3].random_walk.speed_mps, 1.5) && near(n[3].random_walk.x_min, -100),
          "empty random_walk object -> defaults");
    check(n[4].waypoints.size() == 2 && near(n[4].waypoints[0].t, 1) &&
              near(n[4].waypoints[0].x, 0) && near(n[4].waypoints[1].t, 0) &&
              near(n[4].waypoints[1].x, 2),
          "partial waypoints: missing fields -> 0");
    check(n[4].tx_array_gain_dbi && !n[4].rx_array_gain_dbi,
          "tx gain alone leaves rx gain unset");
}

static void
test_loader_nodes_errors()
{
    auto expectJsonErr = [](const std::string& nodes, const std::string& label) {
        TempDir d;
        auto    p = writeScenario(d, "[output]\ndir = out\n", nodes);
        check(throwsType<nlohmann::json::exception>([&] { ConfigLoader::Load(p); }),
              label + " throws nlohmann::json::exception");
    };
    expectJsonErr(R"([{"role":"peer"}])", "node without id");
    expectJsonErr(R"([{"id":5}])", "node with numeric id");
    expectJsonErr(R"([{"id":"a",)", "truncated nodes JSON");
    expectJsonErr("", "empty nodes file");
    expectJsonErr(R"([{"id":"a","tx_array_gain_dbi":"high"}])", "non-numeric node gain");

    TempDir d;
    auto    p = d.write("run.ini", "[output]\ndir = out\n[scenario]\nnodes_file = none.json\n");
    std::string what;
    check(throwsType<std::runtime_error>([&] { ConfigLoader::Load(p); }, &what),
          "missing nodes file throws std::runtime_error");
    check(what.find("Cannot open nodes file") != std::string::npos &&
              what.find((d.path() / "none.json").string()) != std::string::npos,
          "missing nodes file message names the resolved path");
}

static void
test_loader_nodes_file_resolution()
{
    {
        TempDir d;
        d.write("sub/my-nodes.json", R"([{"id":"x"},{"id":"y"}])");
        auto p = d.write("run.ini", "[output]\ndir = out\n[scenario]\nnodes_file = sub/my-nodes.json\n");
        // Load from a different cwd to prove resolution is against the run.ini dir.
        SimConfig c = ConfigLoader::Load(p);
        check(c.nodes.size() == 2 && c.nodes[1].id == "y",
              "relative nodes_file resolved against run.ini dir");
    }
    {
        TempDir     d;
        TempDir     other;
        std::string abs = other.write("abs-nodes.json", R"([{"id":"z"}])");
        auto        p   = d.write("run.ini", "[output]\ndir = out\n[scenario]\nnodes_file = " + abs + "\n");
        SimConfig   c   = ConfigLoader::Load(p);
        check(c.nodes.size() == 1 && c.nodes[0].id == "z", "absolute nodes_file used as-is");
    }
    {
        // run.ini in a subdir, referenced with a relative path from cwd.
        TempDir d;
        d.write("scen/nodes.json", kOneNode);
        d.write("scen/run.ini", "[output]\ndir = out\n");
        fs::path  old = fs::current_path();
        fs::current_path(d.path());
        SimConfig c;
        bool ok = !throwsType<std::exception>([&] { c = ConfigLoader::Load("scen/run.ini"); });
        fs::current_path(old);
        check(ok && c.nodes.size() == 1, "relative run.ini path resolves nodes beside it");
        check(c.output_dir == "scen/out", "relative run.ini path: output dir joined to its dir");
    }
}

// ===========================================================================
// ConfigLoader: jammers file
// ===========================================================================

static void
test_loader_jammer_defaults()
{
    TempDir d;
    d.write("jammers.json", "[{}]");
    SimConfig c = ConfigLoader::Load(writeScenario(
        d, "[output]\ndir = out\n[scenario]\njammers_file = jammers.json\n"));
    check(c.jammers.size() == 1, "one jammer loaded from empty object");
    const JammerSpec& j = c.jammers.at(0);
    // config-loader.h jammers table and src/jammer/README.md defaults.
    check(!j.enabled, "jammer enabled defaults to false");
    check(j.id.empty() && j.type == "constant", "jammer id '' type constant");
    check(j.target_freq.empty(), "jammer target_freq defaults to empty (all)");
    check(near(j.tx_power_dbm, 25.0) && near(j.tx_array_gain_dbi, 12.0),
          "jammer tx_power_dbm 25 tx_array_gain_dbi 12");
    check(near(j.duty_cycle, 1.0) && near(j.max_range_m, 0.0), "jammer duty 1 range 0");
    check(near(j.beamwidth_deg, 360.0) && near(j.azimuth_deg, 0.0) && near(j.zenith_deg, 0.0),
          "jammer beamwidth 360 azimuth 0 zenith 0");
    check(near(j.position.x, 0) && near(j.position.y, 0) && near(j.position.z, 0) &&
              near(j.velocity.vx, 0) && near(j.random_walk.x_min, -100) &&
              near(j.random_walk.speed_mps, 1.5),
          "jammer position/velocity/random_walk defaults");
    check(j.waypoints.empty() && j.intervals.empty(), "jammer waypoints/intervals empty");
}

static void
test_loader_jammer_full()
{
    TempDir d;
    d.write("j/jam.json", R"([
      {"enabled":true,"id":"J1","type":"random","target_freq":[2400,2500],
       "tx_power_dbm":33,"tx_array_gain_dbi":6,"duty_cycle":0.25,"max_range_m":500,
       "beamwidth_deg":60,"azimuth_deg":90,"zenith_deg":95,
       "position":{"x":10,"y":20,"z":2},"velocity":{"vx":1},
       "random_walk":{"bounds":{"x_max":50},"speed_mps":4},
       "waypoints":[{"t":0,"x":1},{"t":5,"x":2}],
       "intervals":[{"start":1,"end":2},{"start":3}]},
      {"id":"J2","enabled":false}
    ])");
    SimConfig c = ConfigLoader::Load(writeScenario(
        d, "[output]\ndir = out\n[scenario]\njammers_file = j/jam.json\n"));
    check(c.jammers.size() == 2 && c.jammers[1].id == "J2", "jammers loaded in order (relative path)");
    const JammerSpec& j = c.jammers.at(0);
    check(j.enabled && j.id == "J1" && j.type == "random", "jammer enabled/id/type parsed");
    check(j.target_freq.size() == 2 && near(j.target_freq[0], 2400) &&
              near(j.target_freq[1], 2500),
          "jammer target_freq parsed");
    check(near(j.tx_power_dbm, 33) && near(j.tx_array_gain_dbi, 6) && near(j.duty_cycle, 0.25) &&
              near(j.max_range_m, 500),
          "jammer power/gain/duty/range parsed");
    check(near(j.beamwidth_deg, 60) && near(j.azimuth_deg, 90) && near(j.zenith_deg, 95),
          "jammer pointing parsed");
    check(near(j.position.x, 10) && near(j.position.y, 20) && near(j.position.z, 2) &&
              near(j.velocity.vx, 1) && near(j.velocity.vy, 0),
          "jammer position/velocity parsed");
    check(near(j.random_walk.x_max, 50) && near(j.random_walk.x_min, -100) &&
              near(j.random_walk.speed_mps, 4),
          "jammer random_walk parsed with per-field defaults");
    check(j.waypoints.size() == 2 && near(j.waypoints[1].t, 5) && near(j.waypoints[1].x, 2),
          "jammer waypoints parsed");
    check(j.intervals.size() == 2 && near(j.intervals[0].start, 1) &&
              near(j.intervals[0].end, 2) && near(j.intervals[1].start, 3) &&
              near(j.intervals[1].end, 0),
          "jammer intervals parsed (missing end -> 0)");
}

static void
test_loader_jammer_errors()
{
    TempDir     d;
    auto        p = writeScenario(d, "[output]\ndir = out\n[scenario]\njammers_file = nope.json\n");
    std::string what;
    check(throwsType<std::runtime_error>([&] { ConfigLoader::Load(p); }, &what) &&
              what.find("Cannot open jammers file") != std::string::npos,
          "missing jammers file throws std::runtime_error");

    TempDir d2;
    d2.write("jammers.json", "[{]");
    auto p2 = writeScenario(d2, "[output]\ndir = out\n[scenario]\njammers_file = jammers.json\n");
    check(throwsType<nlohmann::json::exception>([&] { ConfigLoader::Load(p2); }),
          "malformed jammers JSON throws nlohmann::json::exception");

    TempDir d3;
    auto p3 = writeScenario(d3, "[output]\ndir = out\n[scenario]\njammers_file =\n");
    SimConfig c;
    check(!throwsType<std::exception>([&] { c = ConfigLoader::Load(p3); }) && c.jammers.empty(),
          "blank jammers_file means no jammers");
}

// ===========================================================================
// ConfigLoader: buildings file
// ===========================================================================

static void
test_loader_building_defaults_match_struct()
{
    TempDir d;
    d.write("b.json", "[{}]");
    SimConfig c = ConfigLoader::Load(
        writeScenario(d, "[output]\ndir = out\n[scenario]\nbuildings_file = b.json\n"));
    check(c.buildings.size() == 1, "one building loaded from empty object");
    const BuildingSpec& l = c.buildings.at(0);
    BuildingSpec        s;
    check(l.id == s.id && l.id.empty(), "building id default ''");
    check(l.x_min == s.x_min && l.x_max == s.x_max && l.y_min == s.y_min && l.y_max == s.y_max &&
              l.z_min == s.z_min && l.z_max == s.z_max && near(l.x_max, 1.0) &&
              near(l.z_min, 0.0),
          "building bounds default 0..1 and match struct");
    check(l.type == s.type && l.type == "Residential", "building type default Residential");
    check(l.ext_walls == s.ext_walls && l.ext_walls == "ConcreteWithWindows",
          "building ext_walls default ConcreteWithWindows");
    check(l.n_floors == s.n_floors && l.n_rooms_x == s.n_rooms_x && l.n_rooms_y == s.n_rooms_y &&
              l.n_floors == 1,
          "building floors/rooms default 1");
}

static void
test_loader_building_full_and_partial()
{
    TempDir d;
    d.write("b.json", R"([
      {"id":"B1","bounds":{"x_min":-10,"x_max":10,"y_min":-20,"y_max":20,"z_min":0,"z_max":30},
       "type":"Office","ext_walls":"StoneBlocks","n_floors":10,"n_rooms_x":3,"n_rooms_y":4},
      {"id":"B2","bounds":{"x_max":50}}
    ])");
    SimConfig c = ConfigLoader::Load(
        writeScenario(d, "[output]\ndir = out\n[scenario]\nbuildings_file = b.json\n"));
    check(c.buildings.size() == 2, "two buildings loaded");
    const auto& b = c.buildings[0];
    check(b.id == "B1" && near(b.x_min, -10) && near(b.x_max, 10) && near(b.y_min, -20) &&
              near(b.y_max, 20) && near(b.z_min, 0) && near(b.z_max, 30),
          "building id and bounds parsed");
    check(b.type == "Office" && b.ext_walls == "StoneBlocks" && b.n_floors == 10 &&
              b.n_rooms_x == 3 && b.n_rooms_y == 4,
          "building type/walls/floors/rooms parsed");
    const auto& p = c.buildings[1];
    check(near(p.x_max, 50) && near(p.x_min, 0) && near(p.y_max, 1) && near(p.z_max, 1),
          "partial building bounds -> per-field defaults");

    TempDir d2;
    auto p2 = writeScenario(d2, "[output]\ndir = out\n[scenario]\nbuildings_file = no.json\n");
    std::string what;
    check(throwsType<std::runtime_error>([&] { ConfigLoader::Load(p2); }, &what) &&
              what.find("Cannot open buildings file") != std::string::npos,
          "missing buildings file throws std::runtime_error");
}

// ===========================================================================
// ConfigLoader: positions override
// ===========================================================================

static const char* kThreeNodes =
    R"([{"id":"a","position":{"x":1,"y":2,"z":3}},{"id":"b","position":{"x":4,"y":5,"z":6}},)"
    R"({"id":"c"}])";

static void
test_loader_positions_override_applied()
{
    TempDir d;
    auto    ini = writeScenario(d, "[output]\ndir = out\n", kThreeNodes);
    auto    ov  = d.write("pos.json", R"({"a":[10.5,20,30],"c":[-1,-2,-3],"ghost":[9,9,9]})");
    SimConfig c = ConfigLoader::Load(ini, ov);
    check(c.nodes.size() == 3, "override ids not in nodes file are ignored (no new nodes)");
    check(near(c.nodes[0].position.x, 10.5) && near(c.nodes[0].position.y, 20) &&
              near(c.nodes[0].position.z, 30),
          "override replaces position of a matching node (integers accepted)");
    check(near(c.nodes[1].position.x, 4) && near(c.nodes[1].position.y, 5) &&
              near(c.nodes[1].position.z, 6),
          "node without override entry keeps nodes-file position");
    check(near(c.nodes[2].position.x, -1) && near(c.nodes[2].position.z, -3),
          "override applies to node with default position");

    SimConfig base = ConfigLoader::Load(ini, "");
    check(near(base.nodes[0].position.x, 1), "empty override path skips the override");

    auto empty = d.write("empty.json", "{}");
    SimConfig e = ConfigLoader::Load(ini, empty);
    check(near(e.nodes[0].position.x, 1) && near(e.nodes[1].position.y, 5),
          "empty override object changes nothing");
}

static void
test_loader_positions_override_errors()
{
    TempDir d;
    auto    ini = writeScenario(d, "[output]\ndir = out\n", kThreeNodes);
    std::string what;
    check(throwsType<std::runtime_error>(
              [&] { ConfigLoader::Load(ini, (d.path() / "nope.json").string()); }, &what) &&
              what.find("Cannot open positions override") != std::string::npos,
          "missing override file throws std::runtime_error");

    auto shortArr = d.write("short.json", R"({"a":[1,2]})");
    check(throwsType<nlohmann::json::exception>([&] { ConfigLoader::Load(ini, shortArr); }),
          "2-element override entry throws nlohmann::json::exception");
    auto strArr = d.write("str.json", R"({"b":["x",0,0]})");
    check(throwsType<nlohmann::json::exception>([&] { ConfigLoader::Load(ini, strArr); }),
          "non-numeric override entry throws nlohmann::json::exception");
    auto bad = d.write("bad.json", R"({"a":[1,2,3)");
    check(throwsType<nlohmann::json::exception>([&] { ConfigLoader::Load(ini, bad); }),
          "malformed override JSON throws nlohmann::json::exception");

    // QUESTION (src/config/config-loader.cc:435-438): config-loader.h @throws says a
    // positions-override entry "that is not a 3-element numeric array" throws, but
    // a 4-element array is accepted and its extra elements silently dropped.
    auto longArr = d.write("long.json", R"({"a":[1,2,3,4]})");
    check(throwsType<nlohmann::json::exception>([&] { ConfigLoader::Load(ini, longArr); }),
          "4-element override entry throws (documented: not a 3-element array)");
}

static void
test_loader_positions_override_duplicate_ids()
{
    TempDir d;
    auto    ini = writeScenario(d, "[output]\ndir = out\n",
                                R"([{"id":"a"},{"id":"a","position":{"x":7}}])");
    auto    ov  = d.write("pos.json", R"({"a":[1,1,1]})");
    SimConfig c = ConfigLoader::Load(ini, ov);
    check(c.nodes.size() == 2 && near(c.nodes[0].position.x, 1) && near(c.nodes[1].position.x, 1),
          "override applies to every node sharing the id");
}

// ---- main ----

/**
 * @fn main
 * @brief Run every loader/util/domain test and print a pass/fail count.
 *
 * @return 0 if all checks passed, 1 if any failed.
 */
int
main()
{
    // ini-parser
    test_ini_missing_file_throws();
    test_ini_empty_file();
    test_ini_sections_and_trimming();
    test_ini_keys_before_section();
    test_ini_split_on_first_equals();
    test_ini_duplicate_keys_and_sections();
    test_ini_comments_stripped();
    test_ini_lines_without_equals_skipped();
    test_ini_crlf_line_endings();
    test_ini_no_trailing_newline();
    test_ini_get_defaults();
    test_ini_get_bool();

    // string-utils
    test_trim_str();
    test_split_tab();
    test_to_iso8601();
    test_resolve_path();
    test_dir_of();
    test_seed_list_invalid_exits();
    test_seed_list_boundaries();
    test_seed_list_out_of_uint32_range();

    // domain
    test_max_speed_for_type();
    test_rl_resolved_defaults();

    // ConfigLoader: defaults and keys
    test_loader_documented_defaults();
    test_loader_defaults_match_simconfig_struct();
    test_loader_node_defaults_match_nodespec_struct();
    test_loader_all_keys_parsed();
    test_loader_crlf_run_ini();
    test_loader_misplaced_and_unknown_keys();
    test_loader_duplicate_key_last_wins();
    test_loader_bool_semantics();
    test_loader_controlled_nodes_presence();
    test_loader_band_and_baseline_blank();
    test_loader_no_range_checks();
    test_loader_channel_model_validation();
    test_loader_bad_numbers_throw();
    test_loader_missing_run_ini();

    // ConfigLoader: output dir
    test_loader_output_dir_relative_and_absolute();
    test_loader_output_dir_auto_three_levels();
    test_loader_output_dir_auto_deeper_nesting();
    test_loader_output_dir_auto_without_root_throws();
    test_loader_bare_relative_run_ini_path();

    // ConfigLoader: JSON files
    test_loader_nodes_full_entry();
    test_loader_nodes_partial_objects();
    test_loader_nodes_errors();
    test_loader_nodes_file_resolution();
    test_loader_jammer_defaults();
    test_loader_jammer_full();
    test_loader_jammer_errors();
    test_loader_building_defaults_match_struct();
    test_loader_building_full_and_partial();

    // ConfigLoader: positions override
    test_loader_positions_override_applied();
    test_loader_positions_override_errors();
    test_loader_positions_override_duplicate_ids();

    std::cout << "\n" << g_pass << " passed, " << g_fail << " failed.\n";
    if (g_fail > 0)
    {
        std::cout << "SOME TESTS FAILED.\n";
        return 1;
    }
    std::cout << "All tests passed.\n";
    return 0;
}

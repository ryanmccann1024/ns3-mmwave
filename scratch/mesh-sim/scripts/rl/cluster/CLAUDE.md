# Cluster experiments

Read [the operations guide](../ops/README.md#cluster-runs) and
[the test map](../tests/ops-tests.md).

- `ops/cluster.py` parses and delegates. Keep config meaning in `config.py`,
  job arguments/scripts in `jobs.py`, scheduler calls/parsing in `slurm.py`,
  persisted ownership/layout/locks in `receipts.py`, and state in `reconcile.py`.
  Recovery and submission workflows belong in their named modules; presentation
  stays in `reporting.py`. Reuse the policy plan and task/process owners.
- Check all receipt owners before mutations, then check again under the lock.
  Read-only status queries the recorded owner. Resource `account` is a project
  allocation, not user identity. Do not trust USER/LOGNAME for ownership.
- Plan, submission, recovery, cancellation and local/scheduled comparison share
  the operation lock. Hold it through comparison process cleanup. Scheduled
  comparison validates its receipt and ignores only its own job as a blocker.
- Persist intent before sbatch. Missing responses stay uncertain; empty or failed
  scheduler queries do not prove rejection. Never automatically abandon intents
  or restart dirty training directories. Preserve attempt and assertion history.
- Comparison-only submission never invents an array. Wait for every active array
  and preserve unknown-writer blockers. Cancellation success is a request, not
  proof of termination; recognize terminal states explicitly.
- Keep receipt/status versions, docs and recovery tests aligned with behavior.
  Document first-task, status, remaining work, comparison and retrieval paths.
- Use the fake scheduler and fake child processes for tests. Never submit real
  jobs, train a real study, build ns-3 or run the simulator in these checks.
  Live-site flags, account visibility, accounting latency and filesystem locks
  need separate evidence; leave that limitation visible.

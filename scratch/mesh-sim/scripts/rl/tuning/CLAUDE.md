# Tuning

Read [the operations guide](../ops/README.md) and [test map](../tests/ops-tests.md).

- Keep the CLI in `ops/tune.py` to arguments and delegation. Config owns study
  distributions; trainer owns algorithm constraints, command translation and
  objectives; study owns Optuna; driver owns workflow; artifacts owns schemas
  and checkpoints. Reuse the experiment policy owner and shared artifact I/O.
- A new parameter must reach a real trainer and be validated, recorded and
  included in compatibility/comparison before adding it to a search space.
  Keep algorithm-specific constraints out of generic tuning/CLI code.
- Checkpoint sampler state and trial intent before launch. Commit the recovery
  checkpoint before readable JSON mirrors. Preserve finished trials on resume;
  do not silently restart a sampler, training directory or failed attempt.
- Use the operations process owner for child groups and cleanup on signals or
  ordinary exceptions. Keep study, task and training resume distinct.
- Preserve training/model-selection/held-out roles and the common scored warmup
  contract. Freeze selected configurations before independent evaluation.
- Update artifact versions/readers/examples when saved semantics change.
  Tests use temporary directories and fake processes/objectives. Never run
  `./ns3 build`, `./ns3 run`, or a real simulator for these checks.

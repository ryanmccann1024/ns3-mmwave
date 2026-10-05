# ARPO placement planner source — provenance

Origin: the geometric and optimization placement planners of the ARPO network
optimization model, supplied to this project as a local source bundle.

Date copied: 2026-09-29.

Authorization: on 2026-09-29 the user authorized publishing these nine
algorithm source files in this repository. The authorization covers only the
files listed below. It does not cover the supplied RF configuration
(`rf_config.yaml`), datasets, examples, tests, weights, generated results,
archives, or any other file from the supplied bundle, none of which are copied
here. No license designation was supplied, and none is claimed.

The files are byte-for-byte copies. No imports, algorithms, or other content
were edited. `scripts/baselines/arpo_solver.py` loads them unmodified through a
scoped `sys.path` shim, because they use top-level imports such as
`from models import ...` and `from core.context import ...`.

| File | SHA-256 |
| --- | --- |
| `models.py` | `cc5a667fba9fba674e3d1cf3c99be227dcfeb0030ad32673a3ea9b85cf0c717c` |
| `core/__init__.py` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `core/geometry.py` | `89a76713e0f8abe1543ebe65d4bbe505596c5319a914be521a99beebba3cef73` |
| `core/rf.py` | `ef192e3757aa0a75c59c288dbe6461f027b9678da62ac43a19c0a72827a77178` |
| `core/context.py` | `c772c70d814b4b2564e70d38bf8874995443603faa32d0215b3e936c3b803dfe` |
| `planners/__init__.py` | `9f5747675581b5d6727a92597e87989059b3f7cf4b11e39652e5592a58e11304` |
| `planners/base.py` | `99c063a3a9ba12cae71eba6140061e46825cd71773665944037ddb62057166b6` |
| `planners/geometric.py` | `ee757cc5ce6e4cdf94d86149f335bcf07214f89f738965de3b85f8a96a280966` |
| `planners/optimization.py` | `24ef728dfeaf77aacd3d3c62d4f5381634d07c850c1eaf2be1171515ffc1db8c` |

Runtime dependencies are pinned in `requirements-baselines.txt`; `numpy` is
pinned by `requirements.txt`.

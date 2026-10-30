"""Keep research chronology out of runtime ownership and lower layers independent of CLIs."""
import ast
from pathlib import Path
import re

from scripts.sim_support import find_mesh_root

RL = find_mesh_root()/'scripts/rl'
CLIS = {f'scripts.rl.{name}' for name in ('train', 'evaluate', 'compare', 'online',
                                         'operate', 'experiment', 'preflight_campaign')}
RETIRED = re.compile(r'scripts\.rl\.(?:phase_|campaign(?:\.|$)|adaptive_campaign|campaign_diagnostics|pilot_reference|mission_(?:campaign|focused|foundation|pilot|preflight|reports|review|screen|targeted))')


def imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # Production imports use explicit absolute paths; resolve relative ones too.
            if node.level:
                package = '.'.join(path.relative_to(RL.parent.parent).parts[:-1])
                base = package.split('.')[:len(package.split('.'))-node.level+1]
                module = '.'.join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ''
            yield module
            yield from (module+'.'+alias.name for alias in node.names)


def test_runtime_has_no_numbered_research_modules_or_retired_imports():
    for path in RL.rglob('*.py'):
        if 'tests' in path.relative_to(RL).parts:
            continue
        assert not re.match(r'phase[_\d]', path.name), path
        assert not any(part.startswith('phase_') for part in path.relative_to(RL).parts), path
        assert not any(RETIRED.match(name) for name in imports(path)), path


def test_environment_and_learners_do_not_import_public_clis():
    for owner in ('env', 'agents'):
        for path in (RL/owner).rglob('*.py'):
            assert not (set(imports(path)) & CLIS), path


def test_batch_definition_does_not_import_execution_owners():
    for path in (RL/'experiments').rglob('*.py'):
        assert not any(name.startswith(('scripts.rl.ops', 'scripts.rl.cluster', 'scripts.rl.tuning'))
                       for name in imports(path)), path

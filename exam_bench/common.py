import hashlib
import ast
import json
import os
from pathlib import Path
from datetime import datetime, timezone


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def utc():
    return datetime.now(timezone.utc).isoformat()


def tree_manifest(root):
    root = Path(root)
    def link(path):
        return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
    if link(root):
        raise ValueError('Symlink/reparse root refused: '+str(root))
    result = {}
    for path in sorted(root.rglob('*')):
        if link(path):
            raise ValueError(f'Symlink refused: {path.relative_to(root)}')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


GRADING_FILES = ('grader.py', 'observer.py', 'platform.py', 'submission.py', 'queries.py',
                 'common.py', 'process.py', 'windows_job.py', 'workspaces.py', 'runtime.py', 'isolation.py', 'gates.py', 'ou.py','pr.py','forms.py','interface.py', 'calibration.py', 'calibration_ou.py','calibration_pr.py','calibration_forms.py','calibration_interface.py', 'calibration_query.py', 'calibration_periodicity.py', 'calibration_characteristics.py', 'calibration_characteristics_forms.py', 'calibrate.py', 'replay_calibration.py', 'smoke_check.py')


def runtime_fingerprint():
    """The platform/scenario calibration, independent of penalty policy edits."""
    root = Path(__file__).parent
    return {name: digest(root / name) for name in GRADING_FILES}


def grading_inputs(root=None):
    """Transitive local Python imports and the exact data used by the current ticket."""
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    modules, pending = set(), list(GRADING_FILES) + ['penalties.py', 'assessment.py']
    while pending:
        name = pending.pop()
        if name in modules:
            continue
        path = root / 'exam_bench' / name
        if not path.is_file():
            continue
        modules.add(name)
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                imports = [node.module.split('.')[0]] if node.module else [a.name for a in node.names]
                pending.extend(m + '.py' for m in imports if (root / 'exam_bench' / (m + '.py')).is_file())
    inputs = {name: root / 'exam_bench' / name for name in sorted(modules)}
    task = root / 'tasks/1c-platform-official-sample'
    checks = json.loads((task / 'checks.json').read_text(encoding='utf-8'))
    data = [task / 'checks.json', task / 'private/official-assessment-mapping.json',
            task / 'private/owner-scoring-policy.json', root / 'starters' / checks['starter'] / 'starter.json']
    data += [root / 'rules' / checks['rulebook'] / name for name in
             ('rules.json', 'examiner.json', 'chistov.json', 'standards.json')]
    inputs.update({p.relative_to(root).as_posix(): p for p in data})
    return inputs


def grading_fingerprint():
    # New keys make old incomplete fingerprints explicitly incompatible; no historical receipt is rewritten.
    return {name: digest(path) for name, path in grading_inputs().items()}

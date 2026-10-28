"""Portable, inspectable community submissions. Never export credentials or raw logs."""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exam_bench.common import digest, grading_fingerprint, tree_manifest, utc

UPSTREAM = 'zeegin/1c-agent-exam-benchmark'
ID = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}$')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    from tools.demo_runner import atomic
    atomic(path, data)


def executable(name):
    found = shutil.which(name)
    if not found and os.name == 'nt':
        found = next((str(p) for p in (Path('C:/Program Files/Git/cmd/git.exe') if name == 'git'
                     else Path('C:/Program Files/GitHub CLI/gh.exe'),) if p.is_file()), None)
    if not found:
        raise ValueError(f'Install {name} and restart the local server')
    return found


CAUSES = (('длинный путь', ('filename too long', 'path too long', 'name too long')),
          ('нет доступа к сети', ('could not resolve', 'timed out', 'connection', 'unable to access', 'ssl', 'network')),
          ('нет входа или прав в GitHub', ('auth', 'permission denied', 'http 401', 'http 403', 'not logged', 'credential')))


def command(args, cwd=ROOT):
    args = list(map(str, args))
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
    except subprocess.TimeoutExpired:
        p = subprocess.CompletedProcess(args, 'timeout', '', 'timed out')
    if p.returncode:
        # Never echo command stderr: authentication helpers may include account data. Only the stage and a category.
        words = [a for a in args[1:] if not a.startswith('-') and '=' not in a]
        stage = ' '.join([Path(args[0]).stem, *[w for w in words[:2] if re.fullmatch(r'[a-z-]+', w)]])
        stderr = p.stderr.lower()
        cause = next((name for name, marks in CAUSES if any(m in stderr for m in marks)), 'проверьте вход в GitHub и доступ к репозиторию')
        raise ValueError(f'{stage}: команда завершилась с ошибкой ({p.returncode}): {cause}')
    return p.stdout.strip()


def long_path(path):
    """On Windows the \\?\\ prefix lifts the 260-character limit for one file operation; elsewhere nothing changes."""
    path = os.path.abspath(path)
    return '\\\\?\\' + path if os.name == 'nt' and not path.startswith('\\\\?\\') else path


def copy_bundle(folder, target):
    """Copies the checked bundle file by file: long paths work and the read-only flag of frozen sources is not
    carried over, so the copy can be replaced later. The prepared bundle itself is only read."""
    for rel in [*read(folder / 'manifest.json')['files'], 'manifest.json']:
        source, dest = folder / rel, target / rel
        os.makedirs(long_path(dest.parent), exist_ok=True)
        shutil.copyfile(long_path(source), long_path(dest))


def remove_copy(target, checkout):
    """Removes an earlier copy in the service checkout, read-only files included. Links are removed, never
    followed, and nothing outside the checkout is touched."""
    checkout = Path(os.path.abspath(checkout))
    if checkout not in Path(os.path.abspath(target)).parents or os.path.islink(long_path(target)):
        raise ValueError('Служебная копия пакета находится вне проверенной папки checkout')

    def writable(function, path, *_):
        inside = Path(os.path.abspath(str(path).removeprefix('\\\\?\\')))
        if checkout not in inside.parents:
            raise ValueError('Служебная копия пакета ссылается за пределы checkout')
        os.chmod(path, stat.S_IWRITE)
        function(path)
    if sys.version_info >= (3, 12):
        shutil.rmtree(long_path(target), onexc=writable)
    else:
        shutil.rmtree(long_path(target), onerror=writable)


def operator(data):
    if set(data) - {'name', 'github'}:
        raise ValueError('Unknown operator fields')
    name, github = str(data.get('name', '')).strip(), str(data.get('github', '')).strip()
    if not 1 <= len(name) <= 100 or any(ord(c) < 32 for c in name):
        raise ValueError('Enter a public author name (1–100 characters)')
    if github and not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?', github):
        raise ValueError('Enter a GitHub login, without URL or @')
    return {'name': name, 'github': github}


def github_identity():
    """The author is the account GitHub CLI is signed in to; nothing is typed by hand."""
    try:
        data = json.loads(command([executable('gh'), 'api', 'user']))
    except (ValueError, OSError, subprocess.SubprocessError):
        raise ValueError('Войдите в GitHub: установите GitHub CLI, выполните gh auth login '
                         'и нажмите «Обновить из GitHub»') from None
    login = str(data.get('login') or '')
    name = ' '.join(str(data.get('name') or '').split())[:100] or login
    return operator({'name': name, 'github': login})


def unsafe_protection_off(machine):
    from tools.readiness import protection_disabled
    return protection_disabled(machine.get('platform_binary')) is not None


def machine_snapshot(root=ROOT, cfg=None, timing='before_run'):
    cfg = cfg or read(root / '.local/demo/config.json')
    hardware = {'cpu': platform.processor() or None, 'logical_cpus': os.cpu_count(), 'ram_bytes': None}
    try:
        if os.name == 'nt':
            ps = ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                  '[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $c=Get-CimInstance Win32_Processor; '
                  '$m=Get-CimInstance Win32_ComputerSystem; @{cpu=($c.Name -join "; ");ram_bytes=$m.TotalPhysicalMemory}|ConvertTo-Json -Compress']
            hardware.update(json.loads(command(ps)))
        elif sys.platform == 'darwin':
            hardware.update(cpu=command(['sysctl', '-n', 'machdep.cpu.brand_string']), ram_bytes=int(command(['sysctl', '-n', 'hw.memsize'])))
        else:
            info = Path('/proc/cpuinfo').read_text()
            hardware['cpu'] = next((s.split(':', 1)[1].strip() for s in info.splitlines() if s.startswith('model name')), hardware['cpu'])
            hardware['ram_bytes'] = int(next(s for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemTotal:')).split()[1]) * 1024
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
        pass
    revision = None
    try:
        revision = command([executable('git'), 'rev-parse', 'HEAD'], root)
    except ValueError:
        pass
    # Hash implementation, including uncommitted changes; no hostnames, paths or env dump.
    sources = {}
    for folder in ('exam_bench', 'tools', 'profiles', 'rules'):
        for p in sorted((root / folder).rglob('*')):
            if p.is_file() and p.suffix in ('.py', '.json', '.txt') and '__pycache__' not in p.parts:
                sources[p.relative_to(root).as_posix()] = digest(p)
    machine = read(root / cfg['machine_config'])
    return {'captured_at': utc(), 'capture_timing': timing, 'hardware': hardware,
            'os': {'system': platform.system(), 'release': platform.release(), 'version': platform.version(), 'architecture': platform.machine()},
            'python': platform.python_version(), 'platform_version': cfg['platform_version'],
            'isolation': machine['isolation'], 'network_profile': 'open-book_shell',
            'unsafe_action_protection_observed_in_user_config': unsafe_protection_off(machine),
            'git_revision': revision, 'implementation_files': sources}


def record_measurement(job, cfg, root=ROOT, timing='before_run'):
    target = job / 'measurement.json'
    if not target.exists():
        author_file = root / '.local/community/operator.json'
        write(target, {'operator': operator(read(author_file)) if author_file.is_file() else None,
                       'environment': machine_snapshot(root, cfg, timing)})


def check_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('Invalid result ID')
    return value


def require_visible_result(job_id, root=ROOT):
    job_id = check_id(job_id)
    if (root / '.local/community/deleted' / (job_id + '.json')).exists():
        raise ValueError('Результат удалён из списка')
    return job_id


def prepare_bundle(job_id, root=ROOT):
    # CLI and HTTP workers share the deletion lock.
    from exam_bench.locking import file_lock
    with file_lock(root / '.local/community/action.lock'):
        return _prepare_bundle(require_visible_result(job_id, root), root)


def _prepare_bundle(job_id, root=ROOT):
    """Build DT from immutable XML in a fresh base; never edit the solver's artifacts."""
    from tools.demo_runner import public_evaluation
    from exam_bench.platform import OneC
    from exam_bench.runtime import platform_binary
    cfg = read(root / '.local/demo/config.json')
    os.environ['EXAM_BENCH_CONFIG'] = str(root / cfg['machine_config'])
    job = root / '.local/demo/jobs' / check_id(job_id)
    evaluation = read(job / 'evaluation.json')
    run_id = check_id(evaluation['run_id'])
    run = root / '.local/runs' / run_id
    art = run / 'artifacts'
    frozen = read(run / 'artifact-manifest.json')
    if tree_manifest(art) != frozen:
        raise ValueError('Frozen submission changed')
    prior_measurement = root / '.local/demo/jobs' / run_id / 'measurement.json'
    if not (job / 'measurement.json').is_file() and prior_measurement.is_file():
        shutil.copyfile(prior_measurement, job / 'measurement.json')
    record_measurement(job, cfg, root, 'after_run')
    measurement = read(job / 'measurement.json')
    # Older runs have no operator: require explicit attribution before publishing.
    if not measurement.get('operator') or not measurement['operator'].get('github'):
        identity = operator(read(root / '.local/community/operator.json'))
        if not identity['github']:
            raise ValueError('Set your GitHub login on community.html before preparing a public submission')
        if measurement.get('operator') and measurement['operator']['name'] != identity['name']:
            raise ValueError('Public operator name differs from the operator recorded at run start')
        measurement['operator'] = identity
        measurement['operator_attached_at'] = utc()
        write(job / 'measurement.json', measurement)
    destination = root / '.local/community/prepared' / job_id
    if destination.exists():
        validate_bundle(destination)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='bundle-', dir=destination.parent))
    try:
        shutil.copytree(art / 'src', stage / 'src')
        for name in ('binding.json', 'interpretations.json', 'solution.cf'):
            if (art / name).is_file():
                shutil.copyfile(art / name, stage / name)
        if evaluation.get('binding_compatibility'):
            for name in ('binding-adapter.json', 'binding-adapter-proof.json'):
                shutil.copyfile(job / name, stage / name)
        with tempfile.TemporaryDirectory(prefix='dt-') as td:
            work = Path(td)
            shutil.copytree(stage / 'src', work / 'src')
            onec = OneC(platform_binary(), job / 'community-export', 600)
            onec.restore(work / 'ib', root / cfg['starter_dt'])
            onec.load(work / 'ib', work / 'src')
            onec.command(['DESIGNER', '/F', work / 'ib', '/DumpIB', work / 'solution.dt'], 'dump-solution')
            shutil.copyfile(work / 'solution.dt', stage / 'solution.dt')
        if not (stage / 'solution.dt').stat().st_size:
            raise ValueError('Empty DT export')
        plan = read(run / 'plan.json')
        execution = read(run / 'result.json')
        result = public_evaluation(root, job / 'evaluation.json')
        result['downloads'] = []
        write(stage / 'evaluation.json', result)
        write(stage / 'measurement.json', measurement)
        run_record = {k: plan.get(k) for k in ('client', 'model', 'client_version', 'reasoning_effort', 'harness', 'billing_channel',
            'solve_timeout_seconds', 'time_series', 'delegation', 'network_profile', 'deadline_disclosed', 'statement_sha256',
            'starter_dt_sha256', 'profile_sha256', 'execution_policy_sha256', 'calibration_sha256')}
        metrics = execution.get('metrics', {})
        run_record.update(started_at=execution.get('started_at'), timing=execution.get('time'),
                          original_submission_valid=execution.get('submission', {}).get('valid'),
                          model_provenance=execution.get('model', {}).get('provenance'),
                          tokens={k: metrics.get('tokens', {}).get(k) for k in
                                  ('input', 'cached_input', 'cache_creation_input', 'fresh_input', 'output', 'reasoning_output', 'total', 'coverage')},
                          tools={k: metrics.get('tools', {}).get(k) for k in ('mcp_calls', 'unica_calls', 'failed_calls')},
                          process={k: execution.get('process', {}).get(k) for k in ('status', 'exit_code', 'stop_confirmed')})
        write(stage / 'run.json', run_record)
        calibration = read(root / cfg['calibration'])
        write(stage / 'calibration.json', {k: calibration.get(k) for k in ('accepted', 'profile_id', 'grader_sha256', 'implementation_files', 'readonly_sources_verified', 'fingerprint_version', 'runtime_implementation_files')})
        # Keep the full formal assessment for future evaluator comparisons. It is structured evidence, not raw logs.
        write(stage / 'assessment.json', evaluation['assessment'])
        write(stage / 'grading-implementation.json', evaluation['grading_fingerprint'])
        (stage / 'README.txt').write_text('DT rebuilt by the stand from the frozen XML/BSL submission.\n'
            'No solver workspace, credentials or raw logs included.\n'
            'The score is contributor-reported until independently reproduced.\n', encoding='utf-8')
        write(stage / 'manifest.json', {'schema_version': 1, 'submission_id': job_id, 'run_id': run_id,
            'created_at': utc(), 'files': tree_manifest(stage), 'frozen_artifacts_sha256': digest(run / 'artifact-manifest.json'),
            'dt_origin': 'rebuilt_from_frozen_xml', 'verification': 'contributor_reported'})
        validate_bundle(stage)
        if tree_manifest(art) != frozen:
            raise ValueError('Frozen submission changed during export')
        stage.rename(destination)
        return destination
    finally:
        if stage.exists() and stage != destination:
            shutil.rmtree(stage)


def validate_bundle(folder):
    folder = Path(folder)
    manifest = read(folder / 'manifest.json')
    check_id(manifest['submission_id']); check_id(manifest['run_id'])
    if manifest.get('schema_version') != 1 or manifest.get('verification') != 'contributor_reported':
        raise ValueError('Unsupported submission schema')
    files = tree_manifest(folder)
    files.pop('manifest.json', None)
    if files != manifest['files']:
        raise ValueError('Bundle checksum mismatch')
    required = {'src/Configuration.xml', 'binding.json', 'solution.dt', 'evaluation.json', 'measurement.json',
                'run.json', 'calibration.json', 'assessment.json', 'grading-implementation.json', 'README.txt'}
    if not required <= files.keys():
        raise ValueError('XML, DT or measurement evidence is missing')
    fixed = required | {'interpretations.json', 'solution.cf', 'binding-adapter.json', 'binding-adapter-proof.json'}
    for name in files:
        p = folder / name
        if (p.is_symlink() or not p.resolve().is_relative_to(folder.resolve()) or
                (name not in fixed and not (name.startswith('src/') and p.suffix.lower() in ('.xml', '.bsl', '.bin', '.png', '.jpg', '.jpeg', '.gif', '.txt', '.html', '.css', '.svg', '.mxl')))):
            raise ValueError('Unsupported artifact: ' + name)
        if p.stat().st_size > 95 * 1024 * 1024:
            raise ValueError('A file exceeds 95 MiB; split artifact storage is required before submitting')
    operator(read(folder / 'measurement.json')['operator'])
    result = read(folder / 'evaluation.json')
    if result['run_id'] != manifest['run_id']:
        raise ValueError('Mismatched run ID')
    if result.get('binding_compatibility'):
        if not {'binding-adapter.json', 'binding-adapter-proof.json'} <= files.keys():
            raise ValueError('Supplemental acceptance requires original and normalized bindings with proof')
        proof = read(folder / 'binding-adapter-proof.json')
        if proof['original_binding_sha256'] != digest(folder / 'binding.json') or proof['normalized_binding_sha256'] != digest(folder / 'binding-adapter.json'):
            raise ValueError('Binding adaptation proof mismatch')
    from decimal import Decimal, InvalidOperation
    for name in ('score', 'score_upper_bound'):
        if result.get(name) is not None:
            try:
                value = Decimal(str(result[name]))
                # The owner policy deliberately does not clamp penalties at zero.
                if not value.is_finite() or value > 5:
                    raise ValueError('Score must be finite and cannot exceed five')
            except InvalidOperation:
                raise ValueError('Invalid score') from None
    return manifest


def make_pr(job_id, root=ROOT):
    from exam_bench.locking import file_lock
    with file_lock(root / '.local/community/action.lock'):
        job_id = require_visible_result(job_id, root)
        url = _make_pr(job_id, root)
        # Persist CLI submissions too, before deletion can acquire the lock.
        write(root / '.local/community/pr' / (job_id + '.json'), {'url': url})
        return url


def _make_pr(job_id, root=ROOT):
    """Only called after the user presses Send PR; touches an isolated checkout."""
    folder = root / '.local/community/prepared' / check_id(job_id)
    validate_bundle(folder)
    gh, git = executable('gh'), executable('git')
    login = command([gh, 'api', 'user', '--jq', '.login'])
    if not re.fullmatch(r'[A-Za-z0-9-]+', login):
        raise ValueError('Invalid authenticated GitHub login')
    author = read(folder / 'measurement.json')['operator']
    if not author.get('github') or author['github'].lower() != login.lower():
        raise ValueError('The author login differs from the authenticated GitHub account')
    branch = 'result/' + job_id
    # Idempotency across retries after an unknown network outcome.
    response = command([gh, 'api', '--method', 'GET', 'repos/' + UPSTREAM + '/pulls',
                        '-f', 'state=all', '-f', 'head=' + login + ':' + branch, '-f', 'per_page=100'])
    try:
        candidates = json.loads(response)
        if not isinstance(candidates, list):
            raise ValueError('Unexpected PR response')
        for candidate in candidates:
            head = candidate.get('head') or {}
            owner = (head.get('user') or {}).get('login', '')
            url = candidate.get('html_url', '')
            if (isinstance(owner, str) and owner.lower() == login.lower() and head.get('ref') == branch
                    and isinstance(url, str) and re.fullmatch(r'https://github\.com/' + re.escape(UPSTREAM) + r'/pull/[1-9][0-9]*', url)):
                return url
        if candidates:
            # The REST endpoint filters exact owner + branch, so a mismatching
            # response cannot prove that it is safe to create another PR.
            raise ValueError('GitHub returned unexpected pull requests for the result branch')
    except (TypeError, AttributeError, json.JSONDecodeError):
        raise ValueError('Unexpected PR response') from None
    fork = UPSTREAM if login.lower() == UPSTREAM.split('/')[0].lower() else login + '/' + UPSTREAM.split('/')[1]
    if fork != UPSTREAM:
        command([gh, 'repo', 'fork', UPSTREAM, '--clone=false'])
    repo_dir = root / '.local/community/checkouts' / job_id
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    hooks = root / '.local/community/disabled-hooks'
    hooks.mkdir(exist_ok=True)
    # Settings for these commands only: no hooks, no signing, Windows long paths; global Git config is left alone.
    safe_git = [git, '-c', 'core.hooksPath=' + str(hooks), '-c', 'commit.gpgsign=false', '-c', 'core.longpaths=true']
    if not repo_dir.exists():
        protocol = command([gh, 'config', 'get', 'git_protocol', '--host', 'github.com'])
        clone_url = 'git@github.com:' + fork + '.git' if protocol == 'ssh' else 'https://github.com/' + fork + '.git'
        command([*safe_git, 'clone', '--depth=1', clone_url, repo_dir])
    # Base is upstream's current default branch, never the participant's dirty worktree.
    default = command([gh, 'repo', 'view', UPSTREAM, '--json', 'defaultBranchRef', '--jq', '.defaultBranchRef.name'])
    remote_branch = command([*safe_git, 'ls-remote', '--heads', 'origin', 'refs/heads/' + branch], repo_dir)
    if remote_branch:
        # Resume after an interrupted push/PR request without force-pushing or duplicate commits.
        command([*safe_git, 'fetch', 'origin', branch], repo_dir)
        remote_manifest = json.loads(command([*safe_git, 'show', 'FETCH_HEAD:community/results/' + job_id + '/manifest.json'], repo_dir))
        if remote_manifest != read(folder / 'manifest.json'):
            raise ValueError('The result branch already contains a different bundle; it was not overwritten')
    else:
        command([*safe_git, 'fetch', 'https://github.com/' + UPSTREAM + '.git', default], repo_dir)
        command([*safe_git, 'checkout', '-B', branch, 'FETCH_HEAD'], repo_dir)
        target = repo_dir / 'community/results' / job_id
        if os.path.lexists(long_path(target)):
            remove_copy(target, repo_dir)
        copy_bundle(folder, target)
        command([*safe_git, 'add', '-f', '--', 'community/results/' + job_id], repo_dir)
        command([*safe_git, '-c', 'user.name=' + login, '-c', 'user.email=' + login + '@users.noreply.github.com',
                 'commit', '-m', 'Add community measurement ' + job_id], repo_dir)
        command([*safe_git, 'push', 'origin', branch], repo_dir)
    body = root / '.local/community' / (job_id + '-pr.txt')
    body.write_text('Community measurement from @' + login + '.\n\n'
        'Includes complete frozen XML/BSL, a DT rebuilt from those sources, hardware/environment metadata, '
        'attribution, formal assessment, calibration fingerprint and file checksums.\n\n'
        'The score is contributor-reported; independent reproduction is pending.\n', encoding='utf-8')
    url = command([gh, 'pr', 'create', '--repo', UPSTREAM, '--base', default, '--head', login + ':' + branch,
                   '--title', 'Community result: ' + job_id, '--body-file', body], repo_dir)
    if not re.fullmatch(r'https://github.com/' + re.escape(UPSTREAM) + r'/pull/\d+', url):
        raise ValueError('PR response was not a GitHub PR URL; inspect the branch before retrying')
    return url


ADAPTERS = ('supplemental_indexed_subconto_adapter', 'supplemental_named_subconto_adapter')


def regrade_reasons(folder, current=None):
    """Why a merged result needs grading again by the current grader; empty when its score is current.
    Such results are published with their score marked, not refused."""
    current = current or grading_fingerprint()
    graded = read(folder / 'grading-implementation.json')
    from tools.grading_compatibility import changed_grading_files
    changed = changed_grading_files(graded, current)
    reasons = [{'id': 'grader_changed', 'files': changed}] if changed else []
    if (folder / 'binding-adapter-proof.json').is_file() and read(folder / 'binding-adapter-proof.json').get('scope') not in ADAPTERS:
        reasons.append({'id': 'adapter_not_in_repository'})
    if read(folder / 'run.json').get('original_submission_valid') is False and not (folder / 'binding-adapter-proof.json').is_file():
        reasons.append({'id': 'original_submission_refused'})
    return reasons


def export_public(root, stage):
    records = []
    current = grading_fingerprint()
    for folder in sorted((root / 'community/results').glob('*')):
        if not folder.is_dir():
            continue
        manifest = validate_bundle(folder)
        result = read(folder / 'evaluation.json')
        measurement = read(folder / 'measurement.json')
        plan = read(folder / 'run.json')
        dest = stage / 'community-downloads' / folder.name
        dest.mkdir(parents=True)
        from tools.source_context import contexts
        write(dest / 'source-context.json', contexts(folder / 'src', result.get('charges', []),
                                                       read(folder / 'assessment.json'), read(folder / 'binding.json')))
        with zipfile.ZipFile(dest / 'solution.zip', 'w', zipfile.ZIP_DEFLATED) as z:
            for p in sorted(folder.rglob('*')):
                if p.is_file(): z.write(p, p.relative_to(folder).as_posix())
        records.append({'id': folder.name, 'run_id': manifest['run_id'], 'result': result, 'measurement': measurement, 'conditions': plan,
                        'verification': manifest['verification'], 'download': f'community-downloads/{folder.name}/solution.zip',
                        'source_context': f'community-downloads/{folder.name}/source-context.json',
                        'regrade_required': regrade_reasons(folder, current),
                        'grader_revision_sha256': hashlib.sha256(json.dumps(read(folder / 'grading-implementation.json'), sort_keys=True).encode()).hexdigest(),
                        'archive_sha256': digest(dest / 'solution.zip')})
    from tools.owner_verification import export_receipts
    export_receipts(root, stage, records, current)
    # A regrade is a revision of an existing attempt, not another solver run.
    # Keep every immutable package downloadable, with earlier evaluations nested under the latest.
    grouped = {}
    for record in records:
        grouped.setdefault(record['run_id'], []).append(record)
    results = []
    def revision_key(record):
        try:
            date = datetime.fromisoformat(record['result'].get('created_at', '').replace('Z', '+00:00'))
            timestamp = (date if date.tzinfo else date.replace(tzinfo=timezone.utc)).timestamp()
        except (ValueError, TypeError, AttributeError):
            timestamp = float('-inf')
        return timestamp, record['id']
    for revisions in grouped.values():
        revisions.sort(key=revision_key, reverse=True)
        results.append({**revisions[0], 'previous_evaluations': revisions[1:]})
    write(stage / 'community.json', {'schema_version': 1, 'results': results, 'repository': 'https://github.com/' + UPSTREAM})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'pr', 'validate'])
    parser.add_argument('id')
    a = parser.parse_args()
    if a.action == 'prepare': print(prepare_bundle(a.id))
    elif a.action == 'pr': print(make_pr(a.id))
    else:
        for f in sorted((ROOT / 'community/results').glob('*')) if a.id == 'all' else [ROOT / 'community/results' / check_id(a.id)]:
            if f.is_dir(): validate_bundle(f); print(f.name, 'OK')

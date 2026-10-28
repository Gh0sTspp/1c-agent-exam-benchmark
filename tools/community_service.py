"""Local-only community workflow; long operations survive browser/server restarts."""
import json
import os
import subprocess
import sys
import zipfile
from contextlib import ExitStack
from pathlib import Path

from tools.community_results import ROOT, check_id, read, write, prepare_bundle, make_pr, require_visible_result


def snapshot(root=ROOT):
    status = root / '.local/community/action.json'
    state = read(status) if status.exists() else None
    if state and state.get('phase') == 'working':
        from tools.demo_runner import alive
        if not alive(state.get('pid')):
            state.update(phase='failed', error='Рабочий процесс прерван. Повторите действие.')
            write(status, state)
    author = root / '.local/community/operator.json'
    results = []
    for p in sorted((root / '.local/demo/jobs').glob('*/evaluation.json'), reverse=True):
        bundle = root / '.local/community/prepared' / p.parent.name
        results.append({'id': p.parent.name, 'prepared': (bundle / 'manifest.json').is_file()})
    return {'operator': read(author) if author.exists() else {'name': '', 'github': ''},
            'action': state, 'results': results, 'configured': (root / '.local/demo/config.json').exists(),
            'csrf': None}


def start(action, data, root=ROOT):
    from exam_bench.locking import file_lock
    if action not in ('prepare', 'pr', 'setup', 'harness', 'delete'):
        raise ValueError('Unknown community action')
    with ExitStack() as stack:
        try:
            stack.enter_context(file_lock(root / '.local/community/action.lock', blocking=False))
        except BlockingIOError:
            raise RuntimeError('Подготовка или отправка уже выполняется. Повторите действие позже.') from None
        state = snapshot(root)['action']
        if action == 'delete':
            return delete_result(data, state, root)
        if state and state.get('phase') == 'working':
            raise RuntimeError('Подготовка или отправка уже выполняется')
        if action == 'setup':
            # Do not reconfigure a machine while an attempt is active.
            from tools.demo_runner import ACTIVE
            pointer = root / '.local/demo/current.json'
            if pointer.is_file():
                current = read(root / '.local/demo/jobs' / check_id(read(pointer)['job_id']) / 'status.json')
                if current['phase'] in ACTIVE:
                    raise RuntimeError('Дождитесь завершения текущего прогона')
            from tools.community_setup import validate_request
            data = validate_request(data)
            write(root / '.local/community/setup-request.json', data)
            result_id = 'setup'
        elif action == 'harness':
            from tools.prepare_native_harnesses import catalogue
            if set(data) != {'id'} or data['id'] not in catalogue():
                raise ValueError('Unknown harness')
            result_id = data['id']
        else:
            if set(data) != {'id'}:
                raise ValueError('Only a result ID is accepted')
            result_id = require_visible_result(data['id'], root)
            if not (root / '.local/demo/jobs' / result_id / 'evaluation.json').is_file():
                raise ValueError('Result has no completed evaluation')
            from tools.publication_status import job_run_id, publication_index
            status = read(root / '.local/demo/jobs' / result_id / 'status.json')
            publication = publication_index(root)(job_run_id(root / '.local/demo/jobs' / result_id, status))
            if publication['blocked']:
                raise ValueError('Этот прогон уже опубликован, отправлен или статус его PR ещё проверяется')
        log = root / '.local/community/worker.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('ab') as stream:
            opts = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
            process = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'tools.community_service', action, result_id],
                                       cwd=root, stdout=stream, stderr=stream, **opts)
            write(root / '.local/community/action.json', {'action': action, 'id': result_id, 'phase': 'working', 'pid': process.pid})
        return {'started': True}


def delete_result(data, state, root):
    """Called under action.lock, shared with prepare/PR reservations.

    Keep evidence: regrades can refer to the same run and its frozen artifacts.
    """
    if not isinstance(data, dict) or set(data) != {'id'}:
        raise ValueError('Only a result ID is accepted')
    result_id = check_id(data['id'])
    job = root / '.local/demo/jobs' / result_id
    if not result_id.startswith('demo-') or not (job / 'status.json').is_file():
        raise ValueError('Результат не найден')
    status = read(job / 'status.json')
    if status.get('phase') not in ('finished', 'failed', 'invalid_submission', 'rejected'):
        raise RuntimeError('Дождитесь завершения прогона')
    if status.get('mode') not in ('run', 'regrade'):
        raise ValueError('Результат не найден')
    if (root / '.local/community/pr' / (result_id + '.json')).exists() or (
            state and state.get('id') == result_id and state.get('pr_url')):
        raise RuntimeError('Результат уже отправлен в рейтинг: удаление запрещено')
    if state and state.get('id') == result_id and state.get('phase') == 'working':
        raise RuntimeError('Дождитесь завершения подготовки или отправки PR')
    from tools.demo_runner import atomic
    atomic(root / '.local/community/deleted' / (result_id + '.json'), {'id': result_id})
    return {'deleted': True}


def run(action, result_id, root=ROOT):
    # The parent writes reservation state under a lock before this worker proceeds.
    from exam_bench.locking import file_lock
    with file_lock(root / '.local/community/action.lock'):
        state = read(root / '.local/community/action.json')
    try:
        if action == 'setup':
            from tools.community_setup import setup
            setup(read(root / '.local/community/setup-request.json'), root)
        elif action == 'prepare':
            folder = prepare_bundle(result_id, root)
            archive = folder.with_suffix('.zip')
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
                for p in sorted(folder.rglob('*')):
                    if p.is_file(): z.write(p, p.relative_to(folder).as_posix())
            manifest = read(folder / 'manifest.json')
            state.update(download='api/community/download?id=' + result_id,
                         file_count=len(manifest['files']), bytes=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file()),
                         measurement=read(folder / 'measurement.json'), conditions=read(folder / 'run.json'))
        elif action == 'harness':
            import shutil
            from tools.prepare_native_harnesses import prepare
            node = shutil.which('node')
            if not prepare(result_id, Path(node) if node else None):
                raise ValueError('Харнес установлен, но проверка на каркасе не прошла. Подробности: .local/harnesses/' + result_id + '/capability.json')
        elif action == 'pr':
            state['pr_url'] = make_pr(result_id, root)
        state.update(phase='finished')
    except Exception as e:
        import traceback
        traceback.print_exc()
        state.update(phase='failed', error=str(e) if isinstance(e, ValueError) else
                     'Действие не завершено. Подробности: .local/community/worker.log')
    write(root / '.local/community/action.json', state)


if __name__ == '__main__':
    if sys.argv[1] == 'harness':
        from tools.prepare_native_harnesses import catalogue
        if sys.argv[2] not in catalogue():
            raise SystemExit('Unknown harness')
        run(sys.argv[1], sys.argv[2])
    else:
        run(sys.argv[1], check_id(sys.argv[2]))

"""Identify published and previously submitted local runs without blocking UI polling."""
import json
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

from tools.community_results import UPSTREAM, check_id, executable, read

_PR_URL = re.compile(r'^https://github\.com/' + re.escape(UPSTREAM) + r'/pull/[1-9][0-9]*$')
_LOGIN = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$')
_cache = {}
_lock = threading.Lock()
_TTL = 60
_queue = queue.Queue()
_workers_started = False


def _scan_remote(target):
    """Inspect only one exact owner/branch or saved PR URL; failures remain unknown."""
    try:
        opts = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        fields = 'url,state,headRefName,headRepositoryOwner'
        if target[0] == 'branch':
            args = [executable('gh'), 'api', '--method', 'GET', 'repos/' + UPSTREAM + '/pulls',
                    '-f', 'state=all', '-f', 'head=' + target[1] + ':result/' + target[2], '-f', 'per_page=100']
        else:
            args = [executable('gh'), 'pr', 'view', target[1], '--repo', UPSTREAM, '--json', fields]
        process = subprocess.run(args,
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=10, **opts)
        entries = json.loads(process.stdout) if process.returncode == 0 else None
        if target[0] == 'branch' and isinstance(entries, list):
            entries = [{'url': pr.get('html_url'), 'state': 'MERGED' if pr.get('merged_at') else pr.get('state'),
                        'headRefName': (pr.get('head') or {}).get('ref'),
                        'headRepositoryOwner': (pr.get('head') or {}).get('user')}
                       if isinstance(pr, dict) else None for pr in entries]
        if target[0] == 'url' and isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            entries = None
    except (ValueError, TypeError, AttributeError, OSError, subprocess.TimeoutExpired):
        entries = None
    with _lock:
        _cache[target] = {'entries': entries, 'time': time.monotonic(), 'working': False}


def _worker():
    while True:
        target = _queue.get()
        try:
            _scan_remote(target)
        except Exception:
            # Keep the worker alive and leave this target safely unconfirmed.
            with _lock:
                _cache[target] = {'entries': None, 'time': time.monotonic(), 'working': False}
        finally:
            _queue.task_done()


def remote_entries(target):
    global _workers_started
    with _lock:
        current = _cache.get(target)
        if current is None or (not current['working'] and time.monotonic() - current['time'] >= _TTL):
            current = {'entries': None if current is None else current['entries'],
                       'time': time.monotonic(), 'working': True}
            _cache[target] = current
            if not _workers_started:
                for _ in range(3):
                    threading.Thread(target=_worker, daemon=True).start()
                _workers_started = True
            _queue.put(target)
        return current['entries'], current['working']


def _safe_read(path):
    try:
        data = read(path)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def job_run_id(job, status):
    """Older local regrades may record their source run only in the evaluation."""
    run = status.get('run_id') or _safe_read(Path(job) / 'evaluation.json').get('run_id') or Path(job).name
    return check_id(run)


def publication_index(root):
    root = Path(root)
    published = set()
    for path in (root / 'community/results').glob('*/manifest.json'):
        data = _safe_read(path)
        try:
            if data.get('submission_id') == path.parent.name:
                published.add(check_id(data.get('run_id')))
        except (TypeError, ValueError):
            continue
    jobs = {}
    for path in (root / '.local/demo/jobs').glob('demo-*/status.json'):
        data = _safe_read(path)
        try:
            run = job_run_id(path.parent, data)
            check_id(path.parent.name)
        except (TypeError, ValueError):
            continue
        measurement = _safe_read(root / '.local/community/prepared' / path.parent.name / 'measurement.json')
        if not isinstance(measurement.get('operator'), dict):
            measurement = _safe_read(path.parent / 'measurement.json')
        operator = measurement.get('operator') or {}
        login = operator.get('github', '') if isinstance(operator, dict) else ''
        jobs[path.parent.name] = (run, login if isinstance(login, str) and _LOGIN.fullmatch(login) else '')
    receipts = {}
    for path in (root / '.local/community/pr').glob('*.json'):
        if path.stem not in jobs:
            continue
        url = _safe_read(path).get('url')
        if isinstance(url, str) and _PR_URL.fullmatch(url):
            receipts.setdefault(jobs[path.stem][0], set()).add(url)
    found = {}
    unresolved = set()
    def process(run, target):
        entries, _ = remote_entries(target)
        if entries is None:
            unresolved.add(run)
            return
        matched = False
        invalid = False
        for pr in entries:
            if not isinstance(pr, dict):
                invalid = True
                continue
            url, state = pr.get('url'), str(pr.get('state', '')).upper()
            if not isinstance(url, str) or not _PR_URL.fullmatch(url) or state not in ('OPEN', 'MERGED', 'CLOSED'):
                invalid = True
                continue
            owner = pr.get('headRepositoryOwner') or {}
            owner = owner.get('login', '') if isinstance(owner, dict) else ''
            if target[0] == 'url':
                matches = url == target[1]
                invalid = invalid or not matches
            else:
                if pr.get('headRefName') != 'result/' + target[2] or not isinstance(owner, str) or not owner:
                    invalid = True
                    continue
                matches = (pr.get('headRefName') == 'result/' + target[2] and isinstance(owner, str)
                           and owner.lower() == target[1].lower())
            if matches:
                found.setdefault(run, []).append((state, url))
                matched = True
        # A mismatched/nonconforming response cannot establish absence.
        if invalid or (len(entries) >= 100 and not matched):
            unresolved.add(run)
    for job, (run, login) in jobs.items():
        if login and run not in published:
            process(run, ('branch', login, job))
    for run, urls in receipts.items():
        if run not in published:
            for url in urls:
                process(run, ('url', url))
    def lookup(run):
        if run in published:
            return {'state': 'published', 'blocked': True}
        states = found.get(run, [])
        for code, label in [('MERGED', 'published'), ('OPEN', 'submitted'), ('CLOSED', 'closed')]:
            for state, url in states:
                if state == code:
                    return {'state': label, 'url': url, 'blocked': True}
        urls = sorted(receipts.get(run, set()))
        if urls:
            return {'state': 'unknown', 'url': urls[0], 'blocked': True}
        return {'state': 'unknown', 'blocked': run in unresolved}
    return lookup

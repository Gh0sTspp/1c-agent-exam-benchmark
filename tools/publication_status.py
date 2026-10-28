"""Identify published and previously submitted local runs without blocking UI polling."""
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from tools.community_results import UPSTREAM, check_id, executable, read

_PR_URL = re.compile(r'^https://github\.com/' + re.escape(UPSTREAM) + r'/pull/[1-9][0-9]*$')
_cache = {}
_lock = threading.Lock()
_TTL = 60


def _scan_remote(root):
    """GitHub is consulted in a background thread; failures remain unknown."""
    try:
        opts = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        process = subprocess.run([executable('gh'), 'pr', 'list', '--repo', UPSTREAM,
            '--state', 'all', '--limit', '200', '--json', 'url,state,headRefName,headRepositoryOwner'],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=10, **opts)
        entries = json.loads(process.stdout) if process.returncode == 0 else None
        if not isinstance(entries, list):
            entries = None
    except (ValueError, OSError, subprocess.TimeoutExpired):
        entries = None
    with _lock:
        _cache[str(root.resolve())] = {'entries': entries, 'time': time.monotonic(), 'working': False}


def remote_entries(root):
    key = str(root.resolve())
    with _lock:
        current = _cache.get(key)
        if current is None or (not current['working'] and time.monotonic() - current['time'] >= _TTL):
            current = {'entries': None if current is None else current['entries'],
                       'time': time.monotonic(), 'working': True}
            _cache[key] = current
            threading.Thread(target=_scan_remote, args=(root,), daemon=True).start()
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
        jobs[path.parent.name] = (run, login if isinstance(login, str) else '')
    receipts = {}
    for path in (root / '.local/community/pr').glob('*.json'):
        if path.stem not in jobs:
            continue
        url = _safe_read(path).get('url')
        if isinstance(url, str) and _PR_URL.fullmatch(url):
            receipts.setdefault(jobs[path.stem][0], set()).add(url)
    # Without a receipt or an author identity there is no safe way to match a
    # remote branch to a local job, so skip network work altogether.
    identifiable = {run for run, login in jobs.values() if login} | set(receipts)
    entries, _ = remote_entries(root) if identifiable else ([], False)
    found = {}
    if entries is not None:
        for pr in entries:
            if not isinstance(pr, dict):
                continue
            url, state = pr.get('url'), str(pr.get('state', '')).upper()
            if not isinstance(url, str) or not _PR_URL.fullmatch(url) or state not in ('OPEN', 'MERGED', 'CLOSED'):
                continue
            owner = pr.get('headRepositoryOwner') or {}
            owner = owner.get('login', '') if isinstance(owner, dict) else ''
            branch = pr.get('headRefName', '')
            job = branch[7:] if isinstance(branch, str) and branch.startswith('result/') else ''
            matched_runs = {run for run, urls in receipts.items() if url in urls}
            if job in jobs and jobs[job][1] and isinstance(owner, str) and owner.lower() == jobs[job][1].lower():
                matched_runs.add(jobs[job][0])
            for run in matched_runs:
                found.setdefault(run, []).append((state, url))
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
        # A capped response cannot establish that an older PR does not exist.
        return {'state': 'unknown', 'blocked': bool(run in identifiable and (entries is None or len(entries) >= 200))}
    return lookup

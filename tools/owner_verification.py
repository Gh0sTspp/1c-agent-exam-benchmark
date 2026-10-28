"""Public provenance for an owner recheck, separate from the contributor's measurement."""
import hashlib
import json
from collections import Counter
from pathlib import Path

from exam_bench.common import grading_fingerprint, utc
from tools.community_results import (UPSTREAM, command, executable, github_identity,
                                     machine_snapshot, read, write, digest, check_id)


def fingerprint_id(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def begin(root, cfg, server_name):
    if not server_name or len(server_name) > 100 or any(ord(c) < 32 for c in server_name):
        raise ValueError('Specify a public server name (1–100 characters)')
    account = github_identity()
    repo = json.loads(command([executable('gh'), 'api', 'repos/' + UPSTREAM], root))
    if repo['owner']['login'].lower() != account['github'].lower():
        raise ValueError('Owner verification requires the repository owner GitHub account')
    environment = machine_snapshot(root, cfg, 'before_recheck')
    from exam_bench.grader import PROFILE
    return {'kind': 'repository_owner', 'repository': UPSTREAM, 'operator': account,
            'started_at': utc(), 'server': {'name': server_name,
                'os': environment['os'], 'hardware': environment['hardware'],
                'isolation': environment['isolation']},
            'platform_version': environment['platform_version'],
            'grader': {'profile': PROFILE['id'], 'commit': environment['git_revision'],
                'working_tree_dirty': bool(command([executable('git'), 'status', '--porcelain'], root)),
                'fingerprint': grading_fingerprint()}}


def complete(verification):
    if verification['grader']['fingerprint'] != grading_fingerprint():
        raise ValueError('Grader changed during owner verification')
    return {**verification, 'completed_at': utc(),
            'grader': {**verification['grader'],
                'sha256': fingerprint_id(verification['grader']['fingerprint'])}}


def public_observation_errors(errors):
    """Keep diagnosis useful without publishing arbitrary platform text or local paths."""
    from exam_bench.grader import PROFILE
    known_cases = set(PROFILE['cases'])
    result = []
    for case, error in sorted(errors.items()):
        message = error.get('message', '') if isinstance(error, dict) else ''
        if not isinstance(message, str):
            message = ''
        if ('Значение поля не соответствует установленному отбору' in message
                and 'Регистр сведений: Спецификации; Поле: Период' in message):
            reason = ('1С отклонила запись в регистр спецификаций: период записи не соответствует отбору. '
                      'Сценарий не завершён; это само по себе не доказывает ошибку решения.')
        else:
            reason = 'Сценарий не завершился из-за ошибки наблюдения 1С; подробности сохранены в локальном протоколе.'
        result.append({'scenario': case if case in known_cases else 'other', 'reason': reason})
    return result


def publish(record, folder, root, *, allow_incomplete=False):
    """Publish a new receipt, never edit or relabel an original contributor bundle."""
    if not record.get('owner_verification') or 'assessment' not in record or (record.get('errors') and not allow_incomplete):
        raise ValueError('Only a completed owner recheck with an assessment can be published')
    if record.get('errors') and record['owner_verification'].get('outcome') != 'incomplete':
        raise ValueError('An incomplete recheck must be identified as incomplete')
    original = read(folder / 'evaluation.json')
    score = record['assessment']['score']
    public = {**original, 'created_at': record['owner_verification']['completed_at'],
              'rules': record['rules'], 'counts': dict(Counter(r['verdict'] for r in record['rules'])),
              'charges': [{'id': c['penalty_id'], 'points': c['points'], 'reason': c['reason']}
                          for c in score['charges']],
              **{k: score[k] for k in ('score', 'score_upper_bound', 'grade', 'deductions')},
              'not_assessed': sum(s['status'] == 'not_assessed' for s in record['assessment']['statuses'].values()),
              'infrastructure_errors': bool(record.get('errors')), 'comparison_eligible': False,
              'gates': {k: v.get('status', 'passed' if v.get('passed') else 'failed')
                        for k, v in record['gates'].items()}}
    public.pop('downloads', None)
    public.pop('evaluation_sha256', None)
    public.pop('observation_errors', None)
    if record.get('errors'):
        public['observation_errors'] = public_observation_errors(record['errors'])
    receipt = {'schema_version': 1, 'submission_id': folder.name,
               'original_manifest_sha256': record['original_manifest_sha256'],
               'owner_verification': record['owner_verification'], 'result': public,
               'source_findings': record['assessment'].get('findings', [])}
    if record.get('reassessment'):
        receipt['reassessment'] = record['reassessment']
    name = 'owner-' + record['owner_verification']['completed_at'].replace(':', '').replace('.', '').replace('+', '-')
    check_id(name)
    target = root / 'community/rechecks' / folder.name / (name + '.json')
    if target.exists():
        raise ValueError('Owner receipt already exists')
    if digest(folder / 'manifest.json') != receipt['original_manifest_sha256']:
        raise ValueError('Original submission changed during recheck')
    write(target, receipt)
    return target


def export_receipts(root, stage, records, current):
    """Only maintainer-controlled receipts, outside contributor bundles, can carry the badge."""
    import zipfile
    originals = {r['id']: r for r in records}
    for path in sorted((root / 'community/rechecks').glob('*/*.json')):
        receipt = read(path)
        source = originals.get(receipt.get('submission_id'))
        if source is None:
            raise ValueError('Owner receipt refers to an unknown submission')
        folder = root / 'community/results' / source['id']
        v = receipt['owner_verification']
        files = v['grader']['fingerprint']
        if (receipt.get('schema_version') != 1 or v.get('kind') != 'repository_owner'
                or v.get('repository') != UPSTREAM
                or v['operator']['github'].lower() != UPSTREAM.split('/')[0].lower()
                or receipt['original_manifest_sha256'] != digest(folder / 'manifest.json')
                or v['grader']['sha256'] != fingerprint_id(files)
                or receipt['result']['run_id'] != source['run_id']
                or receipt['result']['created_at'] != v['completed_at']):
            raise ValueError('Invalid owner verification receipt: ' + path.name)
        from datetime import datetime
        if datetime.fromisoformat(v['completed_at']) < datetime.fromisoformat(v['started_at']):
            raise ValueError('Owner verification completed before it started')
        if not v['server']['name'] or not v['platform_version']:
            raise ValueError('Owner verification environment is incomplete')
        revision_id = source['id'] + '--' + path.stem
        dest = stage / 'community-downloads' / revision_id
        dest.mkdir(parents=True)
        from tools.source_context import contexts
        write(dest / 'source-context.json', contexts(folder / 'src', receipt['result'].get('charges', []),
                    {'findings': receipt.get('source_findings', [])}, read(folder / 'binding.json')))
        with zipfile.ZipFile(dest / 'solution.zip', 'w', zipfile.ZIP_DEFLATED) as z:
            for p in sorted(folder.rglob('*')):
                if p.is_file(): z.write(p, 'original/' + p.relative_to(folder).as_posix())
            z.write(path, 'owner-recheck.json')
        from tools.grading_compatibility import changed_grading_files
        changed = changed_grading_files(files, current)
        records.append({**source, 'id': revision_id, 'result': receipt['result'],
            'verification': 'repository_owner_incomplete' if v.get('outcome') == 'incomplete' else 'repository_owner', 'owner_verification': v,
            'regrade_required': ([{'id': 'grader_changed', 'files': changed}] if changed else [])
                + [r for r in source['regrade_required'] if r['id'] != 'grader_changed'],
            'grader_revision_sha256': v['grader']['sha256'],
            'download': 'community-downloads/' + revision_id + '/solution.zip',
            'source_context': 'community-downloads/' + revision_id + '/source-context.json',
            'archive_sha256': digest(dest / 'solution.zip')})

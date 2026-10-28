"""Regrade immutable community XML using the operator's calibrated local platform."""
import argparse
import json
import os
import tempfile
from pathlib import Path
from tools.community_results import ROOT, check_id, read, write, validate_bundle, digest, tree_manifest


def recheck(result_id, output, root=ROOT, *, owner_server=None, publish_owner=False, publish_incomplete=False):
    from tools.demo_runner import prerequisites
    from exam_bench.runtime import platform_binary, machine_identity
    from exam_bench.common import grading_fingerprint, utc
    from exam_bench.submission import strip_extras, canonical_ledger, check_bindings
    from exam_bench.gates import check_all, starter_for
    from exam_bench.grader import grade
    from exam_bench.penalties import assess
    if publish_incomplete and not publish_owner:
        raise ValueError('--publish-incomplete requires --publish-owner')
    if publish_owner and not owner_server:
        raise ValueError('Publishing requires --owner-server')
    cfg, calibration = prerequisites(root, fresh=False)
    from tools import owner_verification
    verification = owner_verification.begin(root, cfg, owner_server) if owner_server else None
    folder = root / 'community/results' / check_id(result_id)
    manifest = validate_bundle(folder)
    output = Path(output).resolve()
    if output.exists() or output.is_relative_to((root / 'community').resolve()):
        raise ValueError('Use a new output directory outside original community submissions')
    output.mkdir(parents=True)
    binding, _ = strip_extras(read(folder / 'binding.json'))
    if (folder / 'binding-adapter.json').is_file():
        from tools.supplemental_acceptance import normalize
        projected, _ = normalize(folder / 'src', read(folder / 'binding.json'))
        if projected != read(folder / 'binding-adapter.json'):
            raise ValueError('Normalized binding differs from the metadata-proved projection')
        binding = projected
    binding, _ = canonical_ledger(folder / 'src', binding)
    check_bindings(folder / 'src', binding)
    dt = root / cfg['starter_dt']
    task = root / 'tasks/1c-platform-official-sample'
    with tempfile.TemporaryDirectory(prefix='rc-') as td:
        gates, ticket, allowed = check_all(folder / 'src', binding, dt, platform_binary(), Path(td))
    record = {'schema_version': 1, 'submission_id': result_id, 'created_at': utc(),
              'original_manifest_sha256': digest(folder / 'manifest.json'), 'gates': gates,
              'machine': machine_identity(), 'grading_fingerprint': grading_fingerprint(),
              'calibration_sha256': digest(root / cfg['calibration']), 'may_grade': allowed}
    if allowed:
        g = grade(folder / 'src', binding, dt, platform_binary(), output / 'grade')
        record.update(rules=g['rules'], errors=g['errors'], assessment=assess(g['rules'], folder / 'src', binding,
            read(task / 'checks.json')['requirements'], starter_for(dt), read(task / 'private/official-assessment-mapping.json'),
            read(task / 'private/owner-scoring-policy.json'), gates, g['observations']))
    validate_bundle(folder)
    errors = record.get('errors') or {}
    incomplete = (bool(errors) and all(isinstance(error, dict) and error.get('kind') == 'observation_error'
                                      for error in errors.values()))
    if verification and allowed and (not errors or (publish_incomplete and incomplete)):
        if errors:
            verification = {**verification, 'outcome': 'incomplete'}
        record['owner_verification'] = owner_verification.complete(verification)
    write(output / 'evaluation.json', record)
    if publish_owner:
        owner_verification.publish(record, folder, root, allow_incomplete=publish_incomplete and incomplete)
    return output / 'evaluation.json'


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('id'); p.add_argument('--output', required=True)
    p.add_argument('--owner-server', help='Public name of the repository owner recheck server')
    p.add_argument('--publish-owner', action='store_true', help='Save a new public owner receipt under community/rechecks')
    p.add_argument('--publish-incomplete', action='store_true', help='Allow a clearly marked incomplete receipt for observation errors; requires --publish-owner')
    a = p.parse_args()
    print(recheck(a.id, a.output, owner_server=a.owner_server, publish_owner=a.publish_owner,
                  publish_incomplete=a.publish_incomplete))

"""Smoke check of the grader on a participant's machine: does the whole pipeline work here?

Calibration of the rules is the owner's job and is done centrally; submitted results are regraded
centrally after rule changes. On a participant's machine it is enough to see that 1C restores the
starter, loads a configuration, runs the observer and that verdicts come out both ways: a correct
variant passes the rules its cases decide, a known mistake is caught. Four 1C runs instead of 74.
"""
from pathlib import Path

from .calibration import generate
from .common import digest, grading_fingerprint, runtime_fingerprint, tree_manifest, write_json
from .grader import grade, PROFILE

# One case per section with its own observer: accounting, payroll, operational accounting.
CASES = ['average', 'pr_tariff', 'ou_policies']
MUTANT = ('warehouse_average', ['average'], 'BU13')


def run(starter_source, starter_dt, binary, folder, mutant, cases):
    binding = generate(starter_source, folder / 'src', 'one', mutant)
    for path in (folder / 'src').rglob('*'):
        if path.is_file():
            path.chmod(0o444)
    hashes = tree_manifest(folder / 'src')
    g = grade(folder / 'src', binding, starter_dt, binary, folder / 'grade', cases)
    return g, tree_manifest(folder / 'src') == hashes


def smoke_check(starter_source, starter_dt, binary, root):
    from .runtime import machine_identity, require_execution_mode, platform_binary
    require_execution_mode()
    if str(Path(binary).resolve()) != platform_binary():
        raise ValueError('Calibration binary must match the machine settings')
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    implementation = grading_fingerprint()
    write_json(root / 'progress.json', {'phase': 'positive'})
    good, good_unchanged = run(starter_source, starter_dt, binary, root / 'one', None, CASES)
    write_json(root / 'progress.json', {'phase': 'mutant'})
    mutation, cases, rule = MUTANT
    bad, bad_unchanged = run(starter_source, starter_dt, binary, root / mutation, mutation, cases)
    write_json(root / 'progress.json', {'phase': 'query_parameter'})
    from .calibration_query import run as calibrate_query
    query_calibration = calibrate_query(starter_source, starter_dt, binary, root / 'query-parameter')
    write_json(root / 'progress.json', {'phase': 'periodicity'})
    from .calibration_periodicity import run as calibrate_periodicity
    periodicity_calibration = calibrate_periodicity(starter_source, starter_dt, binary, root / 'periodicity')
    write_json(root / 'progress.json', {'phase': 'characteristics'})
    from .calibration_characteristics import run as calibrate_characteristics
    characteristics_calibration = calibrate_characteristics(starter_source, starter_dt, binary, root / 'characteristics')
    passed = [r['id'] for r in good['rules'] if r['verdict'] == 'pass']
    failed = [r['id'] for r in good['rules'] if r['verdict'] == 'fail']
    caught = next(r['verdict'] for r in bad['rules'] if r['id'] == rule) == 'fail'
    if implementation != grading_fingerprint():
        raise ValueError('Grading implementation changed during the check')
    summary = {'schema_version': 1, 'fingerprint_version': 2, 'runtime_implementation_files': runtime_fingerprint(), 'mode': 'smoke', 'profile_id': PROFILE['id'],
               'grader_sha256': digest(Path(__file__).parent / 'grader.py'),
               'calibration_generator_sha256': digest(Path(__file__).parent / 'calibration.py'),
               'cases': CASES, 'positive': {'passed_rules': passed, 'failed_rules': failed, 'errors': good['errors'],
                                             'observed': sorted(good['observations'])},
               'mutant': {'mutation': mutation, 'rule': rule, 'caught': caught, 'errors': bad['errors']},
               'query_parameter_calibration': query_calibration,
               'periodicity_calibration': periodicity_calibration,
               'characteristics_calibration': characteristics_calibration,
               'positives': [], 'negatives': [], 'implementation_files': implementation,
               'readonly_sources_verified': good_unchanged and bad_unchanged, 'machine': machine_identity()}
    summary['accepted'] = bool(passed and not failed and not good['errors'] and not bad['errors'] and caught
                               and set(good['observations']) == set(CASES) and summary['readonly_sources_verified']
                               and query_calibration['passed'] and periodicity_calibration['passed'] and characteristics_calibration['passed'])
    if not summary['accepted']:
        summary['reason'] = ('1C errors: ' + ', '.join(sorted({**good['errors'], **bad['errors']}))) if good['errors'] or bad['errors'] else \
            'correct variant failed: ' + ', '.join(failed) if failed else 'known mistake not caught' if not caught else \
            'table parameter calibration failed' if not query_calibration['passed'] else 'periodicity calibration failed' if not periodicity_calibration['passed'] else 'characteristics calibration failed' if not characteristics_calibration['passed'] else 'incomplete observations'
    write_json(root / 'summary.json', summary)
    return summary

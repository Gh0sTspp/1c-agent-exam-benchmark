"""Calibrate OU03/OU08 metadata and history checks on actual 1C control configurations."""
from pathlib import Path
from contextlib import contextmanager
from copy import deepcopy

from .calibration import generate
from .common import tree_manifest, write_json
from .grader import grade
from .ou import static_signs
from . import ou


def specification_observations(observations):
    snapshots = observations.get('ou_history', {}).get('snapshots', {})
    assembly = observations.get('ou_assembly', {}).get('snapshots', {})
    versions = (snapshots.get('spec_jan') == [{'item': 'BENCH_A', 'qty': 1, 'property': 'BENCH_P1'}]
                and snapshots.get('spec_feb') == [{'item': 'BENCH_A', 'qty': 2, 'property': 'BENCH_P1'}])
    details = sorted((r.get('item'), r.get('property'), r.get('qty')) for r in assembly.get('spec', []))
    return versions, details == [('BENCH_A', 'BENCH_P1', 2), ('BENCH_B', 'BENCH_Q1', 1)]


@contextmanager
def history_boundary_probes():
    """Read on either side of week normalization without altering the grading scenarios."""
    original = ou.CASES['ou_history']
    temporary = deepcopy(original)
    temporary['steps'].extend([
        ('spec_read', 'probe_dec29', '2024-12-29', 'K'),
        ('spec_read', 'probe_dec30', '2024-12-30', 'K'),
        ('spec_read', 'probe_jan26', '2025-01-26', 'K'),
        ('spec_read', 'probe_jan27', '2025-01-27', 'K'),
    ])
    ou.CASES['ou_history'] = temporary
    try:
        yield
    finally:
        ou.CASES['ou_history'] = original


def specification_boundary_observations(observations, normalize):
    snapshots = observations.get('ou_history', {}).get('snapshots', {})
    one = [{'item': 'BENCH_A', 'qty': 1, 'property': 'BENCH_P1'}]
    two = [{'item': 'BENCH_A', 'qty': 2, 'property': 'BENCH_P1'}]
    expected = {'probe_dec29': [], 'probe_dec30': one if normalize else [],
                'probe_jan26': one, 'probe_jan27': two if normalize else one}
    actual = {key: snapshots.get(key) for key in expected}
    return actual == expected, actual, expected


def specification_inputs(starter_source, starter_dt, binary, root):
    """Exercise ordinary and week-normalizing input, including a wrong history consumer."""
    controls = []
    for normalize in (False, True):
        for mutant in (None, 'spec_first_version'):
            label = ('week' if normalize else 'plain') + ('_first_version' if mutant else '_correct')
            folder = root / label
            folder.mkdir(parents=True)
            src = folder / 'src'
            binding = generate(starter_source, src, 'one', mutant)
            if normalize:
                module = src / 'InformationRegisters/BenchSpecs/Ext/RecordSetModule.bsl'
                module.parent.mkdir(parents=True, exist_ok=True)
                module.write_text('Процедура ПередЗаписью(Отказ, Замещение)\n'
                                  ' Для Каждого Запись Из ЭтотОбъект Цикл\n'
                                  '  Запись.Период = НачалоНедели(Запись.Период);\n'
                                  ' КонецЦикла;\nКонецПроцедуры\n', encoding='utf-8')
            before = tree_manifest(src)
            cases = ['ou_assembly', 'ou_assembly_split', 'ou_history']
            with history_boundary_probes():
                evaluation = grade(src, binding, starter_dt, binary, folder / 'grade', cases)
            verdicts = {r['id']: r['verdict'] for r in evaluation['rules']
                        if r['id'] in ('OU07', 'OU08', 'OU10', 'OU11', 'OU12', 'OU13')}
            observations = evaluation['observations']
            version_rows, preserved_details = specification_observations(observations)
            boundaries_match, boundary_actual, boundary_expected = specification_boundary_observations(observations, normalize)
            expected = 'fail' if mutant else 'pass'
            passed = (not evaluation['errors'] and tree_manifest(src) == before
                      and set(cases).issubset(observations) and version_rows and preserved_details and boundaries_match
                      and verdicts.get('OU07') == 'pass' and verdicts.get('OU08') == 'pass'
                      and verdicts.get('OU12') == expected
                      and (bool(mutant) or all(verdicts.get(r) == 'pass' for r in ('OU10', 'OU11', 'OU13'))))
            controls.append({'case': label, 'expected_ou12': expected, 'verdicts': verdicts,
                             'versions_preserved': version_rows, 'details_preserved': preserved_details,
                             'boundary_dates_match': boundaries_match, 'boundary_actual': boundary_actual,
                             'boundary_expected': boundary_expected,
                             'errors': evaluation['errors'], 'passed': passed})
    return controls


def run(starter_source, starter_dt, binary, root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    controls = []
    for label, policy, spec, expected in [
        ('year_day', 'Year', 'Day', ('pass', 'pass')),
        ('day_day', 'Day', 'Day', ('inconclusive', 'pass')),
        ('year_second', 'Year', 'Second', ('pass', 'inconclusive')),
    ]:
        folder = root / label
        folder.mkdir()
        src = folder / 'src'
        binding = generate(starter_source, src, 'one')
        for name, old, value in [('BenchPolicies', 'Year', policy), ('BenchSpecs', 'Day', spec)]:
            path = src / 'InformationRegisters' / (name + '.xml')
            text = path.read_text(encoding='utf-8-sig')
            marker = '<InformationRegisterPeriodicity>' + old + '</InformationRegisterPeriodicity>'
            if text.count(marker) != 1:
                raise ValueError('Control fixture periodicity is missing or ambiguous: ' + name)
            path.write_text(text.replace(marker, '<InformationRegisterPeriodicity>' + value + '</InformationRegisterPeriodicity>'), encoding='utf-8')
        before = tree_manifest(src)
        actual_periods = static_signs(src, binding)['periodicity']
        evaluation = grade(src, binding, starter_dt, binary, folder / 'grade', ['ou_history'])
        verdicts = {r['id']: r['verdict'] for r in evaluation['rules'] if r['id'] in ('OU03', 'OU08')}
        passed = (not evaluation['errors'] and tree_manifest(src) == before
                  and actual_periods == {'policies': policy, 'specification': spec}
                  and (verdicts.get('OU03'), verdicts.get('OU08')) == expected)
        controls.append({'case': label, 'periodicity': actual_periods, 'expected': dict(zip(('OU03', 'OU08'), expected)),
                         'verdicts': verdicts, 'errors': evaluation['errors'], 'passed': passed})
    input_controls = specification_inputs(starter_source, starter_dt, binary, root / 'specification-input')
    summary = {'passed': all(x['passed'] for x in controls + input_controls), 'controls': controls,
               'specification_input_controls': input_controls,
               'limitations': ['Дневная периодичность не подтверждает запрет второй версии за календарную неделю',
                               'Иная периодичность сама по себе не доказывает дефект решения']}
    write_json(root / 'summary.json', summary)
    return summary

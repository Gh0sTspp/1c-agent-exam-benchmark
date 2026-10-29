"""Live controls for the report observer, independent of submitted results.

Run against disposable controls, never against published submissions:
python -m exam_bench.calibration_report_observer --source XML --starter DT --binary 1CV8 --output NEW_DIRECTORY
The output directory contains each generated source, grade and summary.json.
"""
import argparse
import copy
from pathlib import Path

from . import grader, ou, pr
from .calibration import generate
from .common import write_json
from .report_observability import inspect_report


# Each mutant changes one report's behavior, not the adapter. They were already
# used by the full calibration; both implementations are exercised here.
MUTANTS = (
    ('report_ignores_period', 'report', 'bu_sales', 'BU16'),
    ('report_profit_wrong', 'report', 'bu_sales', 'BU17'),
    ('statement_ignores_department', 'ou_report', 'ou_statement', 'OU19'),
    ('statement_without_characteristics', 'ou_report', 'ou_statement', 'OU20'),
    ('ou_sales_profit_wrong', 'ou_report', 'ou_sales', 'OU21'),
    ('bonus_report_all_months', 'pr_bonus', 'pr_bonus', 'PR19'),
    ('bonus_report_wrong_seniority', 'pr_bonus', 'pr_bonus', 'PR19'),
)
REPORTS = {
    'bu_sales': ('report', 'BU16', 'item'),
    'ou_statement': ('ou_report', 'OU19', 'item'),
    'ou_sales': ('ou_report', 'OU21', 'item'),
    'pr_bonus': ('pr_bonus', 'PR19', 'employee'),
}
POSITIVE_RULES = ('BU16', 'BU17', 'OU19', 'OU20', 'OU21', 'PR19')


def report_observation(observations, role):
    """Get exactly the rows, captured schema and error for a report role."""
    case = observations.get(REPORTS[role][0]) or {}
    if role == 'bu_sales':
        return case.get('report_rows'), case.get('report_schema'), case.get('report_error')
    key = {'ou_statement': 'statement', 'ou_sales': 'sales', 'pr_bonus': 'report_feb'}[role]
    snapshots, errors = case.get('snapshots') or {}, case.get('errors') or {}
    return snapshots.get(key), snapshots.get(key + '_schema'), errors.get(key)


def verify_schema(observations, binding, role):
    rows, schema, error = report_observation(observations, role)
    report = (binding.get('reports') or {}).get(role) or {}
    fields = report.get('fields')
    evidence = inspect_report(fields, list(fields or {}), rows, schema, error)
    statuses = {key: value['status'] for key, value in evidence['fields'].items()}
    passed = (bool(fields) and evidence['status'] == 'observed'
              and len(statuses) == len(fields) and all(status == 'observed' for status in statuses.values()))
    return {'passed': bool(passed), 'status': evidence['status'], 'fields': statuses,
            'columns': schema.get('columns') if isinstance(schema, dict) else None, 'error': error}


def _rule(grade, name):
    return next((r for r in grade.get('rules', []) if r.get('id') == name), None)


def _compare(observations, binding, role):
    if role == 'bu_sales':
        return grader.compare(observations, binding)
    if role == 'pr_bonus':
        return pr.compare(observations, binding)
    return ou.compare(observations, binding)


def adapter_controls(observations, binding):
    """Re-evaluate the *same* live observations with deliberately bad bindings.

    These are adapter controls, not generated solutions or 1C executions.
    They must become inconclusive rather than falsely passing or failing.
    """
    result = []
    for role, (_, rule, field) in REPORTS.items():
        for mutation in ('missing_mapping', 'missing_column'):
            changed = copy.deepcopy(binding)
            fields = changed['reports'][role]['fields']
            if mutation == 'missing_mapping':
                fields.pop(field, None)
            else:
                fields[field] = 'BenchNonexistentColumn'
            verdict = next((r for r in _compare(observations, changed, role) if r['id'] == rule), None)
            result.append({'role': role, 'mutation': mutation, 'rule': rule,
                           'actual': verdict, 'passed': bool(verdict and verdict['verdict'] == 'inconclusive')})
    return result


def calibrate(starter_source, starter_dt, binary, evidence):
    """Run controls once per implementation; do not alter existing results."""
    evidence = Path(evidence)
    evidence.mkdir(parents=True, exist_ok=False)
    results = []
    for variant in ('one', 'two'):
        architecture = 'function' if variant == 'one' else 'dcs'
        controls = [(None, None, None, None)] + list(MUTANTS)
        for mutant, case, role, rule in controls:
            name = mutant or 'positive'
            folder = evidence / (variant + '_' + name)
            folder.mkdir()
            binding = generate(starter_source, folder / 'source', variant, mutant)
            grade = grader.grade(folder / 'source', binding, starter_dt, binary, folder / 'grade',
                                 [case] if case else ['report', 'ou_report', 'pr_bonus'])
            expected_rules = {rule: 'fail'} if mutant else {r: 'pass' for r in POSITIVE_RULES}
            actual = {r: _rule(grade, r) for r in expected_rules}
            schemas = {r: verify_schema(grade['observations'], binding, r)
                       for r in ([role] if role else REPORTS)}
            adapters = [] if mutant else adapter_controls(grade['observations'], binding)
            passed = (not grade['errors'] and all(s['passed'] for s in schemas.values())
                      and all(actual[r] and actual[r]['verdict'] == expected
                              for r, expected in expected_rules.items())
                      and all(item['passed'] for item in adapters))
            result = {'variant': variant, 'architecture': architecture, 'control': name,
                      'expected': expected_rules, 'rules': actual, 'schemas': schemas,
                      'adapter_controls': adapters, 'platform_errors': grade['errors'],
                      'grade_ref': str((folder / 'grade' / 'grade.json').relative_to(evidence)),
                      'passed': bool(passed)}
            results.append(result)
            write_json(evidence / 'progress.json', {'completed': len(results), 'results': results})
            print(variant, name, 'pass' if passed else 'FAIL', flush=True)
    summary = {'passed': bool(results) and all(result['passed'] for result in results),
               'results': results}
    write_json(evidence / 'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, help='Exported starter configuration XML directory')
    parser.add_argument('--starter', required=True, help='Starter DT')
    parser.add_argument('--binary', required=True, help='1cv8 executable')
    parser.add_argument('--output', required=True, help='New evidence directory')
    args = parser.parse_args()
    if not calibrate(args.source, args.starter, args.binary, args.output)['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

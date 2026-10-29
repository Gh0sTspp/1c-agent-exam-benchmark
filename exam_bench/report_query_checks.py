"""Adversarial report inputs; observations never assume a particular query implementation.

These are technical report verdicts, not a diagnosis of a specific official
penalty. A wrong number alone cannot prove whether a join or a virtual table was
the cause. The caller must keep such attribution separate.
"""
from decimal import Decimal, InvalidOperation


# Same January movements, different opening balances. Both items deliberately
# have no characteristic value: a report must not lose them at an outer join.
CASES = {
    'report_balance_contrast': {
        'departments': ['D'], 'items': ['X', 'Y'], 'properties': {},
        'steps': [
            ('policy', 'D', 'fifo', '2024-01-01'),
            ('receipt', 'dec', '2024-12-10', 'D', [('X', None, 2, 10), ('Y', None, 4, 10)]),
            ('snapshot', 'opening'),
            ('receipt', 'jan', '2025-01-10', 'D', [('X', None, 3, 20), ('Y', None, 3, 20)]),
            ('sale', 'sale', '2025-01-20', [('D', 'X', 1, 30), ('D', 'Y', 1, 30)]),
            ('snapshot', 'closing'),
            ('report', 'statement', 'ou_statement', '2025-01-01', '2025-01-31', 'D'),
        ],
    },
    # Two lines for the same item in one sale: joining two line sets only by
    # the document duplicates amounts. No assumption about the SQL is made.
    'report_sales_cardinality': {
        'departments': ['D'], 'items': ['X'], 'properties': {},
        'steps': [
            ('policy', 'D', 'fifo', '2024-01-01'),
            ('receipt', 'receipt', '2025-01-10', 'D', [('X', None, 10, 10)]),
            ('snapshot', 'before'),
            ('sale', 'sale', '2025-01-20', [('D', 'X', 2, 30), ('D', 'X', 1, 40)]),
            ('snapshot', 'after'),
            ('report', 'sales', 'ou_sales', '2025-01-01', '2025-01-31', None),
        ],
    },
}

_EXPECTED = {
    'report_balance_contrast': {
        'X': {'opening': 20, 'receipt': 60, 'expense': 10, 'closing': 70},
        'Y': {'opening': 40, 'receipt': 60, 'expense': 10, 'closing': 90},
    },
    'report_sales_cardinality': {'X': {'quantity': 3, 'cost': 30, 'revenue': 100, 'profit': 70}},
}
_ROLES = {'report_balance_contrast': ('statement', 'ou_statement'),
          'report_sales_cardinality': ('sales', 'ou_sales')}


def _number(value):
    if value is None or isinstance(value, bool) or value == '':
        raise ValueError('report contains a missing or non-numeric value')
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('report contains a missing or non-numeric value') from None
    if not number.is_finite():
        raise ValueError('report contains a non-finite value')
    return number


def _stock(snapshot, item):
    rows = [r for r in snapshot if r.get('department') == 'BENCH_D' and r.get('item') == 'BENCH_' + item]
    return (sum((_number(r.get('qty')) for r in rows), Decimal(0)),
            sum((_number(r.get('cost')) for r in rows), Decimal(0)))


def _fixture_verified(case, observation):
    posted = observation['posted']
    names = ('dec', 'jan', 'sale') if case == 'report_balance_contrast' else ('receipt', 'sale')
    if not all(posted.get(name) is True for name in names):
        raise ValueError('fixture documents were not all posted')
    snapshots = observation['snapshots']
    if case == 'report_balance_contrast':
        expected = [('opening', 'X', (2, 20)), ('opening', 'Y', (4, 40)),
                    ('closing', 'X', (4, 70)), ('closing', 'Y', (6, 90))]
    else:
        expected = [('before', 'X', (10, 100)), ('after', 'X', (7, 70))]
    if any(_stock(snapshots[name], item) != tuple(map(Decimal, values)) for name, item, values in expected):
        raise ValueError('fixture stock does not match the intended movements')


def evaluate(case, observations, binding):
    """Return pass/fail/inconclusive with evidence, not an official penalty.

    The report renderer must tag every output row with ``__leaf``. Hierarchical
    subtotal rows are ignored; a renderer without that information cannot
    safely establish whether totals or joins have been counted twice.
    """
    if case not in CASES:
        raise ValueError('unknown report query scenario')
    label, role = _ROLES[case]
    expected = _EXPECTED[case]
    def inconclusive(reason):
        return {'case': case, 'verdict': 'inconclusive', 'reason': reason}
    try:
        obs = observations[case]
        _fixture_verified(case, obs)
        if label in obs.get('errors', {}):
            return inconclusive('report was not observed: ' + str(obs['errors'][label])[:180])
        fields = binding.get('reports', {}).get(role, {}).get('fields', {})
        required = {'item'} | set(next(iter(expected.values())))
        rows = obs['snapshots'][label]
        from .report_observability import require_report_fields
        require_report_fields(fields, required, rows, obs['snapshots'].get(label + '_schema'))
        if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get('__leaf'), bool)
                                             or not isinstance(r.get('__inherited'), list)
                                             or any(not isinstance(k, str) for k in r['__inherited']) for r in rows):
            return inconclusive('report row hierarchy is unavailable')
        # Empty DCS results can have one grand-total leaf with NULL in every
        # physical output column. Only the observer's full-row marker proves
        # this; all mapped fields being NULL alone cannot validate a binding.
        if (len(rows) == 1 and rows[0]['__leaf'] and rows[0].get('__empty') is True
                and not rows[0]['__inherited'] and all(rows[0].get(k) is None for k in required)):
            rows = []
        if rows and not any(r['__leaf'] and r.get('item') in {'BENCH_' + item for item in expected}
                            for r in rows):
            return inconclusive('report item mapping is not verified by any expected item')
        details = {}
        for item, want in expected.items():
            leaves = [r for r in rows if r['__leaf'] and r.get('item') == 'BENCH_' + item]
            if not leaves:
                details[item] = {'actual': None, 'expected': want, 'leaves': 0}
                continue
            if any(set(r['__inherited']) & set(want) for r in leaves):
                return inconclusive('report leaf inherited a numeric subtotal')
            actual = {key: sum((_number(r.get(key)) for r in leaves), Decimal(0)) for key in want}
            details[item] = {'actual': {key: str(value) for key, value in actual.items()}, 'expected': want, 'leaves': len(leaves)}
        # The fixture verifies stock movements but does not observe the register
        # or document data actually used as the source of sales revenue. A
        # wrong revenue/profit could therefore originate before the report.
        if case == 'report_sales_cardinality':
            stock_wrong = any(row['actual'] is None or any(
                _number(row['actual'][k]) != Decimal(row['expected'][k]) for k in ('quantity', 'cost'))
                for row in details.values())
            if not stock_wrong and any(
                any(_number(row['actual'][k]) != Decimal(row['expected'][k]) for k in ('revenue', 'profit'))
                for row in details.values()
            ):
                return {'case': case, 'verdict': 'inconclusive', 'details': details,
                        'reason': 'sales revenue source was not independently verified'}
            wrong = stock_wrong
        else:
            wrong = any(row['actual'] is None or any(_number(row['actual'][k]) != Decimal(v) for k, v in row['expected'].items())
                        for row in details.values())
        return {'case': case, 'verdict': 'fail' if wrong else 'pass', 'details': details,
                'reason': 'report values differ from verified fixture' if wrong else None}
    except (KeyError, TypeError, ValueError) as exc:
        return inconclusive('required observations unavailable: ' + str(exc)[:180])


def integrate(rules, observations, binding, selected_cases=None):
    """Combine observable scenarios into OU19/OU21 without invented causes.

    A previously failing assertion remains a failure. A missing new scenario
    prevents a pass only in the full run or when the caller selected that
    scenario explicitly; other targeted calibration runs remain unchanged.
    OU20's characteristic-value requirement remains under its existing test.
    """
    mappings = {'report_balance_contrast': 'OU19', 'report_sales_cardinality': 'OU21'}
    for case, rule_id in mappings.items():
        if selected_cases is not None and case not in selected_cases:
            continue
        result = evaluate(case, observations, binding)
        rule = next((r for r in rules if r['id'] == rule_id), None)
        if rule is None:
            continue
        rule.setdefault('additional_checks', []).append(result)
        previous, current = rule['verdict'], result['verdict']
        if current == 'fail' or previous == 'fail':
            rule['verdict'] = 'fail'
        elif current == 'inconclusive' or previous == 'inconclusive':
            rule['verdict'] = 'inconclusive'
        else:
            rule['verdict'] = 'pass'
        if current != 'pass':
            note = '%s: %s' % (case, result.get('reason') or current)
            rule['reason'] = '; '.join(filter(None, [rule.get('reason'), note]))
        rule['coverage'] = 'selected_fixtures_and_report_cardinality'
    return rules

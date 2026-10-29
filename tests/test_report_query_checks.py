import copy
import unittest

from exam_bench.report_query_checks import evaluate, integrate
from exam_bench.calibration_ou import STATEMENT_QUERY
from exam_bench.calibration_report_query_checks import _turnovers_only, JOIN_MULTIPLY


FIELDS = {
    'ou_statement': {'fields': {k: k for k in ('item', 'opening', 'receipt', 'expense', 'closing')}},
    'ou_sales': {'fields': {k: k for k in ('item', 'quantity', 'cost', 'revenue', 'profit')}},
}
BINDING = {'reports': FIELDS}


def stock(item, qty, cost):
    return {'department': 'BENCH_D', 'item': 'BENCH_' + item, 'qty': qty, 'cost': cost}


def statement():
    return {'report_balance_contrast': {
        'posted': {'dec': True, 'jan': True, 'sale': True}, 'errors': {},
        'snapshots': {
            'opening': [stock('X', 2, 20), stock('Y', 4, 40)],
            'closing': [stock('X', 4, 70), stock('Y', 6, 90)],
            'statement_schema': {'columns': list(FIELDS['ou_statement']['fields'].values())},
            'statement': [
                {'__leaf': False, '__inherited': [], 'item': 'BENCH_X', 'opening': 20, 'receipt': 60, 'expense': 10, 'closing': 70},
                {'__leaf': True, '__inherited': [], 'item': 'BENCH_X', 'opening': 20, 'receipt': 60, 'expense': 10, 'closing': 70},
                {'__leaf': True, '__inherited': [], 'item': 'BENCH_Y', 'opening': 40, 'receipt': 60, 'expense': 10, 'closing': 90},
            ]}}}


def sales():
    return {'report_sales_cardinality': {
        'posted': {'receipt': True, 'sale': True}, 'errors': {},
        'snapshots': {
            'before': [stock('X', 10, 100)], 'after': [stock('X', 7, 70)],
            'sales_schema': {'columns': list(FIELDS['ou_sales']['fields'].values())},
            'sales': [{'__leaf': True, '__inherited': [], 'item': 'BENCH_X', 'quantity': 3, 'cost': 30, 'revenue': 100, 'profit': 70}]}}}



class ReportQueryChecksTests(unittest.TestCase):
    def test_mutants_really_exercise_turnovers_and_unconstrained_join(self):
        query = _turnovers_only(STATEMENT_QUERY)
        self.assertIn('.Обороты(&НачалоПериода', query)
        self.assertNotIn('.ОстаткиИОбороты(', query)
        self.assertNotIn('CostНачальныйОстаток', query)
        self.assertIn('ПО Т.Регистратор = С.Ссылка', JOIN_MULTIPLY)
        self.assertNotIn('Т.Item = С.Номенклатура', JOIN_MULTIPLY)

    def test_integration_preserves_existing_failure_and_limits_selected_cases(self):
        rules = [{'id': 'OU19', 'verdict': 'fail', 'reason': 'other fixture'},
                 {'id': 'OU20', 'verdict': 'pass', 'reason': None},
                 {'id': 'OU21', 'verdict': 'pass', 'reason': None}]
        integrate(rules, statement(), BINDING, ['report_balance_contrast'])
        self.assertEqual([r['verdict'] for r in rules], ['fail', 'pass', 'pass'])
        self.assertNotIn('additional_checks', rules[2])

    def test_full_run_requires_new_observations_and_uses_no_gen_attribution(self):
        rules = [{'id': 'OU19', 'verdict': 'pass', 'reason': None},
                 {'id': 'OU21', 'verdict': 'pass', 'reason': None}]
        observations = statement()
        del observations['report_balance_contrast']['snapshots']['statement'][-1]
        integrate(rules, observations, BINDING)
        self.assertEqual([r['verdict'] for r in rules], ['fail', 'inconclusive'])
        self.assertEqual([r['id'] for r in rules], ['OU19', 'OU21'])

    def test_balance_control_ignores_tree_subtotal_and_detects_turnover_only(self):
        data = statement()
        assert evaluate('report_balance_contrast', data, BINDING)['verdict'] == 'pass'
        for row in data['report_balance_contrast']['snapshots']['statement']:
            row['opening'], row['closing'] = 0, 50
        result = evaluate('report_balance_contrast', data, BINDING)
        assert result['verdict'] == 'fail'
        assert result['details']['X']['actual']['opening'] == '0'


    def test_absent_item_in_unmatched_join_is_observed_failure(self):
        data = statement()
        data['report_balance_contrast']['snapshots']['statement'] = []
        assert evaluate('report_balance_contrast', data, BINDING)['verdict'] == 'fail'

    def test_existing_but_wrong_item_mapping_is_inconclusive(self):
        data = statement()
        for row in data['report_balance_contrast']['snapshots']['statement']:
            row['item'] = 'Some other value from an existing column'
        result = evaluate('report_balance_contrast', data, BINDING)
        self.assertEqual(result['verdict'], 'inconclusive')
        self.assertIn('item mapping', result['reason'])

    def test_empty_dcs_grand_total_requires_all_physical_columns_empty(self):
        data = statement()
        row = {'__leaf': True, '__inherited': [], '__empty': True,
               'item': None, 'opening': None, 'receipt': None, 'expense': None, 'closing': None}
        data['report_balance_contrast']['snapshots']['statement'] = [row]
        self.assertEqual(evaluate('report_balance_contrast', data, BINDING)['verdict'], 'fail')
        # A different, unmapped physical column contains data: the item
        # binding may be wrong, so the missing values prove nothing.
        row['__empty'] = False
        self.assertEqual(evaluate('report_balance_contrast', data, BINDING)['verdict'], 'inconclusive')
        del row['__empty']
        self.assertEqual(evaluate('report_balance_contrast', data, BINDING)['verdict'], 'inconclusive')

    def test_missing_one_item_when_other_item_matches_is_failure(self):
        data = statement()
        rows = data['report_balance_contrast']['snapshots']['statement']
        rows[:] = [row for row in rows if row['item'] == 'BENCH_X']
        self.assertEqual(evaluate('report_balance_contrast', data, BINDING)['verdict'], 'fail')


    def test_duplicate_join_fails_even_when_one_row_is_individually_correct(self):
        data = sales()
        rows = data['report_sales_cardinality']['snapshots']['sales']
        rows.append(copy.deepcopy(rows[0]))
        result = evaluate('report_sales_cardinality', data, BINDING)
        assert result['verdict'] == 'fail'
        assert result['details']['X']['actual']['revenue'] == '200'

    def test_sales_revenue_mismatch_is_inconclusive_without_source_verification(self):
        data = sales()
        row = data['report_sales_cardinality']['snapshots']['sales'][0]
        row.update(revenue=120, profit=90)
        result = evaluate('report_sales_cardinality', data, BINDING)
        self.assertEqual(result['verdict'], 'inconclusive')
        self.assertEqual(result['details']['X']['actual']['revenue'], '120')
        self.assertIn('not independently verified', result['reason'])

    def test_stock_error_still_fails_when_revenue_also_differs(self):
        data = sales()
        row = data['report_sales_cardinality']['snapshots']['sales'][0]
        row.update(quantity=6, cost=60, revenue=200, profit=140)
        self.assertEqual(evaluate('report_sales_cardinality', data, BINDING)['verdict'], 'fail')


    def test_detail_rows_can_be_split_and_subtotals_are_ignored(self):
        data = sales()
        data['report_sales_cardinality']['snapshots']['sales'] = [
            {'__leaf': False, '__inherited': [], 'item': 'BENCH_X', 'quantity': 3, 'cost': 30, 'revenue': 100, 'profit': 70},
            {'__leaf': True, '__inherited': [], 'item': 'BENCH_X', 'quantity': 2, 'cost': 20, 'revenue': 60, 'profit': 40},
            {'__leaf': True, '__inherited': [], 'item': 'BENCH_X', 'quantity': 1, 'cost': 10, 'revenue': 40, 'profit': 30},
        ]
        assert evaluate('report_sales_cardinality', data, BINDING)['verdict'] == 'pass'


    def test_missing_hierarchy_or_invalid_fixture_cannot_be_scored(self):
        data = sales()
        del data['report_sales_cardinality']['snapshots']['sales'][0]['__leaf']
        assert evaluate('report_sales_cardinality', data, BINDING)['verdict'] == 'inconclusive'
        data = sales()
        data['report_sales_cardinality']['snapshots']['after'][0]['qty'] = 8
        assert evaluate('report_sales_cardinality', data, BINDING)['verdict'] == 'inconclusive'
        data = sales()
        data['report_sales_cardinality']['posted']['sale'] = False
        assert evaluate('report_sales_cardinality', data, BINDING)['verdict'] == 'inconclusive'


    def test_missing_columns_and_report_errors_are_inconclusive(self):
        data = sales()
        assert evaluate('report_sales_cardinality', data, {'reports': {}})['verdict'] == 'inconclusive'
        data['report_sales_cardinality']['errors']['sales'] = 'report failed'
        assert evaluate('report_sales_cardinality', data, BINDING)['verdict'] == 'inconclusive'

    def test_unmapped_item_and_inherited_numeric_totals_are_inconclusive(self):
        data = sales()
        data['report_sales_cardinality']['snapshots']['sales_schema']['columns'].remove('item')
        self.assertEqual(evaluate('report_sales_cardinality', data, BINDING)['verdict'], 'inconclusive')
        data = sales()
        data['report_sales_cardinality']['snapshots']['sales'][0]['__inherited'] = ['revenue']
        self.assertEqual(evaluate('report_sales_cardinality', data, BINDING)['verdict'], 'inconclusive')
        data = sales()
        data['report_sales_cardinality']['snapshots']['sales'][0]['__inherited'] = ['item']
        self.assertEqual(evaluate('report_sales_cardinality', data, BINDING)['verdict'], 'pass')

import unittest
from exam_bench.report_observability import inspect_report, report_code_with_schema
from exam_bench import grader, ou, pr


class ReportObservabilityTests(unittest.TestCase):
    def test_capture_is_optional_for_both_report_architectures(self):
        reports = [
            {'object': 'Report.Sales', 'kind': 'function', 'module': 'object',
             'function': 'Build', 'fields': {'quantity': 'Quantity'}},
            {'object': 'Report.Sales', 'kind': 'dcs',
             'parameters': {'period_start': 'Start', 'period_end': 'End'},
             'fields': {'quantity': 'Quantity'}},
        ]
        for report in reports:
            for department in (False, True):
                with self.subTest(kind=report['kind'], department=department):
                    code = report_code_with_schema(report, 'Report_Test', department)
                    args = 'Начало, Конец' + (', Подразделение' if department else '')
                    self.assertIn(f'Функция Report_Test({args}, СхемаРезультата = Неопределено)', code)
                    self.assertIn('Для Каждого Колонка Из Коллекция.Колонки', code)
                    self.assertIn('СхемаРезультата.Вставить("columns", ИменаКолонок)', code)
                    self.assertIn('ДобавитьСтроки(', code)

    def test_zero_null_and_missing_column_are_distinct(self):
        fields = {'zero': 'Zero', 'null': 'Null', 'absent': 'Absent'}
        result = inspect_report(fields, fields, [{'zero': 0, 'null': None, 'absent': None}],
                                {'columns': ['zero', 'NULL']})['fields']
        self.assertEqual(result['zero']['values'], [0])
        self.assertEqual(result['null']['values'], [None])
        self.assertEqual(result['absent']['status'], 'mapped_column_absent')

    def test_no_binding_is_not_an_absent_report(self):
        self.assertEqual(inspect_report(None, ['amount'])['status'], 'binding_unavailable')
        result = inspect_report({}, ['amount'], [{}], {'columns': ['Amount']})
        self.assertEqual(result['fields']['amount']['status'], 'mapping_unavailable')

    def test_missing_schema_or_observation_stays_unknown(self):
        fields = {'amount': 'Amount'}
        self.assertEqual(inspect_report(fields, fields)['status'], 'observation_unavailable')
        self.assertEqual(inspect_report(fields, fields, [{'amount': None}])['fields']['amount']['status'], 'schema_unavailable')
        self.assertEqual(inspect_report(fields, fields, None, error='bad parameter')['status'], 'execution_error')
        self.assertEqual(inspect_report(fields, fields, [{}], {'columns': ['Amount']})['fields']['amount']['status'], 'row_data_unavailable')

    def test_no_rows_is_not_a_zero_or_missing_column(self):
        result = inspect_report({'amount': 'Amount'}, ['amount'], [], {'columns': ['Amount']})
        self.assertEqual(result['fields']['amount']['status'], 'observed')
        self.assertEqual(result['fields']['amount']['values'], [])

    def test_tree_totals_are_not_aggregated_with_leaf_rows(self):
        rows = [{'amount': 12, '__leaf': False}, {'amount': 12, '__leaf': True}]
        result = inspect_report({'amount': 'Amount'}, ['amount'], rows, {'columns': ['Amount']})
        self.assertEqual(result['fields']['amount']['values'], [12, 12])

    def test_inherited_roles_are_recorded_in_bsl(self):
        self.assertIn('Унаследовано.Добавить(КЗ.Ключ)', grader.REPORT_HELPERS)
        self.assertIn('Р.Вставить("__inherited", Унаследовано)', grader.REPORT_HELPERS)

    def test_empty_row_uses_all_physical_columns_not_only_binding(self):
        self.assertIn('Для Каждого Колонка Из Колонки Цикл', grader.REPORT_HELPERS)
        self.assertIn('ФизическоеЗначение = Стр[Колонка.Имя]', grader.REPORT_HELPERS)
        self.assertIn('Р.Вставить("__empty", ПустаяСтрока)', grader.REPORT_HELPERS)


class ReportComparisonIntegrationTests(unittest.TestCase):
    def test_ou_old_snapshot_and_schema_classification(self):
        fields = {k: k for k in ('item', 'opening', 'receipt', 'expense', 'closing')}
        binding = {'ou': {'objects': {}, 'fields': {'sale': {'department': 'Rows.Department'}}},
                   'reports': {'ou_statement': {'fields': fields}}}
        row = {'item': 'BENCH_X', 'opening': 20, 'receipt': 60, 'expense': 40, 'closing': 40}
        observation = {'ou_report': {'errors': {}, 'snapshots': {'statement': [row]}}}

        def verdict():
            return {r['id']: r for r in ou.compare(observation, binding)}['OU19']['verdict']

        self.assertEqual(verdict(), 'pass')  # old snapshot, readable values
        row['closing'] = None
        self.assertEqual(verdict(), 'inconclusive')  # old adapter may have lost a column
        observation['ou_report']['snapshots']['statement_schema'] = {'columns': list(fields.values())}
        self.assertEqual(verdict(), 'fail')  # real NULL does not equal 40
        observation['ou_report']['snapshots']['statement_schema']['columns'].remove('closing')
        self.assertEqual(verdict(), 'inconclusive')
        observation['ou_report']['errors']['statement'] = 'adapter parameter error'
        self.assertEqual(verdict(), 'inconclusive')

    def test_bu_mapped_columns_and_error_are_inconclusive(self):
        fields = {k: k for k in ('item', 'sold', 'quantity', 'cost', 'revenue', 'profit')}
        binding = {'account_codes': {'goods': '41'}, 'reports': {'bu_sales': {'fields': fields}}}
        rows = [{'item': 'BENCH_A', 'sold': 'BENCH_A', 'quantity': 1, 'cost': 10, 'revenue': 40, 'profit': 30, '__leaf': True, '__inherited': []},
                {'item': 'BENCH_A', 'sold': 'BENCH_C', 'quantity': 1, 'cost': 20, 'revenue': 40, 'profit': 20, '__leaf': True, '__inherited': []}]
        snap = {'posted': True, 'sale_lines': ['BENCH_A'], 'report_rows': rows, 'report_schema': {'columns': list(fields)}}

        def verdict():
            return {r['id']: r for r in grader.compare({'report': snap}, binding)}['BU16']['verdict']

        self.assertEqual(verdict(), 'pass')
        rows[0]['cost'] = None
        self.assertEqual(verdict(), 'fail')
        snap['report_schema']['columns'].remove('cost')
        self.assertEqual(verdict(), 'inconclusive')
        snap['report_error'] = 'bad parameter'
        self.assertEqual(verdict(), 'inconclusive')

    def test_payroll_missing_mapping_and_adapter_error(self):
        fields = {'employee': 'Employee', 'amount': 'Amount', 'percent': 'Percent'}
        binding = {'reports': {'pr_bonus': {'fields': fields}}}
        snap = {'errors': {}, 'snapshots': {'report_feb': [], 'report_feb_schema': {'columns': ['Employee', 'Amount', 'Percent']}}}

        def verdict():
            return {r['id']: r for r in pr.compare({'pr_bonus': snap}, binding)}['PR19']['verdict']

        self.assertEqual(verdict(), 'fail')  # schema proves empty result
        fields.pop('amount')
        self.assertEqual(verdict(), 'inconclusive')
        fields['amount'] = 'Amount'
        snap['errors']['report_feb'] = 'adapter failed'
        self.assertEqual(verdict(), 'inconclusive')


if __name__ == '__main__':
    unittest.main()

import unittest

from exam_bench import grader


def fixture():
    fields = {key: key for key in ('item', 'sold', 'quantity', 'cost', 'revenue', 'profit')}
    binding = {'account_codes': {'goods': '41'}, 'reports': {'bu_sales': {'fields': fields}}}
    rows = [
        {'item': 'BENCH_A', 'sold': None, 'quantity': 2, 'cost': 30, 'revenue': 80,
         'profit': 50, '__leaf': False, '__inherited': []},
        {'item': 'BENCH_A', 'sold': 'BENCH_A', 'quantity': None, 'cost': None,
         'revenue': None, 'profit': None, '__leaf': False, '__inherited': ['item']},
        {'item': 'BENCH_A', 'sold': 'BENCH_A', 'quantity': 1, 'cost': 10,
         'revenue': 40, 'profit': 30, '__leaf': True, '__inherited': ['item', 'sold']},
        {'item': 'BENCH_A', 'sold': 'BENCH_C', 'quantity': 1, 'cost': 20,
         'revenue': 40, 'profit': 20, '__leaf': True, '__inherited': ['item']},
    ]
    snapshot = {'report_rows': rows, 'report_schema': {'columns': list(fields)},
                'posted': True, 'sale_lines': ['BENCH_A']}
    return binding, snapshot


def verdicts(binding, snapshot):
    return {r['id']: r['verdict'] for r in grader.compare({'report': snapshot}, binding)}


class BUReportDetailTests(unittest.TestCase):
    def test_group_subtotals_and_nulls_do_not_corrupt_detail(self):
        binding, snapshot = fixture()
        result = verdicts(binding, snapshot)
        self.assertEqual((result['BU16'], result['BU17']), ('pass', 'pass'))

    def test_real_wrong_detail_still_fails(self):
        binding, snapshot = fixture()
        snapshot['report_rows'][-1]['profit'] = 21
        result = verdicts(binding, snapshot)
        self.assertEqual(result['BU16'], 'pass')
        self.assertEqual(result['BU17'], 'fail')

    def test_old_rows_without_leaf_marker_are_inconclusive(self):
        binding, snapshot = fixture()
        for row in snapshot['report_rows']:
            row.pop('__leaf')
            row.pop('__inherited')
        result = verdicts(binding, snapshot)
        self.assertEqual((result['BU16'], result['BU17']), ('inconclusive', 'inconclusive'))

    def test_inherited_numeric_values_cannot_confirm_detail(self):
        binding, snapshot = fixture()
        snapshot['report_rows'][-1]['__inherited'].append('cost')
        result = verdicts(binding, snapshot)
        self.assertEqual((result['BU16'], result['BU17']), ('inconclusive', 'inconclusive'))

    def test_unavailable_inheritance_metadata_is_inconclusive(self):
        binding, snapshot = fixture()
        snapshot['report_rows'][-1].pop('__inherited')
        result = verdicts(binding, snapshot)
        self.assertEqual((result['BU16'], result['BU17']), ('inconclusive', 'inconclusive'))


if __name__ == '__main__':
    unittest.main()

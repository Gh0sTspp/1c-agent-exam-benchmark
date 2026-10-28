import copy
import unittest

from exam_bench.calibration_periodicity import (history_boundary_probes, specification_observations,
                                                  specification_boundary_observations)
from exam_bench import ou
from exam_bench.ou import specification_write


def valid_observations():
    return {'ou_history': {'snapshots': {
        'spec_jan': [{'item': 'BENCH_A', 'qty': 1, 'property': 'BENCH_P1'}],
        'spec_feb': [{'item': 'BENCH_A', 'qty': 2, 'property': 'BENCH_P1'}],
    }}, 'ou_assembly': {'snapshots': {'spec': [
        {'item': 'BENCH_B', 'qty': 1, 'property': 'BENCH_Q1'},
        {'item': 'BENCH_A', 'qty': 2, 'property': 'BENCH_P1'},
    ]}}}


class SpecificationInputCalibrationTests(unittest.TestCase):
    def test_append_does_not_set_a_period_filter_or_replace_other_records(self):
        code = specification_write('InformationRegister.Spec', 'Дата(2025,1,1)', [('Item', 'Товар')])
        self.assertIn('СоздатьНаборЗаписей()', code)
        self.assertIn('Набор.Записать(Ложь)', code)
        self.assertNotIn('.Отбор.', code)

    def test_boundary_probes_distinguish_week_normalization_from_ordinary_write(self):
        one = [{'item': 'BENCH_A', 'qty': 1, 'property': 'BENCH_P1'}]
        two = [{'item': 'BENCH_A', 'qty': 2, 'property': 'BENCH_P1'}]
        snapshots = {'probe_dec29': [], 'probe_dec30': one, 'probe_jan26': one, 'probe_jan27': two}
        data = {'ou_history': {'snapshots': snapshots}}
        self.assertTrue(specification_boundary_observations(data, True)[0])
        self.assertFalse(specification_boundary_observations(data, False)[0])
        snapshots.update(probe_dec30=[], probe_jan27=one)
        self.assertTrue(specification_boundary_observations(data, False)[0])
        self.assertFalse(specification_boundary_observations(data, True)[0])

    def test_probes_restore_original_scenario_even_on_error(self):
        original = ou.CASES['ou_history']
        with self.assertRaisesRegex(RuntimeError, 'stop'):
            with history_boundary_probes():
                self.assertIsNot(ou.CASES['ou_history'], original)
                self.assertEqual(len(ou.CASES['ou_history']['steps']), len(original['steps']) + 4)
                raise RuntimeError('stop')
        self.assertIs(ou.CASES['ou_history'], original)

    def test_control_detects_lost_history_and_distinct_details(self):
        data = valid_observations()
        self.assertEqual(specification_observations(data), (True, True))
        missing_history = copy.deepcopy(data)
        missing_history['ou_history']['snapshots']['spec_jan'] = []
        self.assertEqual(specification_observations(missing_history), (False, True))
        missing_detail = copy.deepcopy(data)
        missing_detail['ou_assembly']['snapshots']['spec'].pop()
        self.assertEqual(specification_observations(missing_detail), (True, False))


if __name__ == '__main__':
    unittest.main()

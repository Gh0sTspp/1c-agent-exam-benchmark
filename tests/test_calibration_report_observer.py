import unittest
from unittest.mock import patch

from exam_bench import calibration_report_observer as calibration


class ObserverCalibrationTests(unittest.TestCase):
    def test_schema_requires_actual_physical_columns(self):
        binding = {'reports': {'ou_statement': {'fields': {'item': 'Товар', 'opening': 'Начало'}}}}
        obs = {'ou_report': {'snapshots': {'statement': [{'item': 'X', 'opening': 0}],
                                           'statement_schema': {'columns': ['товар', 'Начало']}}, 'errors': {}}}
        self.assertTrue(calibration.verify_schema(obs, binding, 'ou_statement')['passed'])
        obs['ou_report']['snapshots']['statement_schema']['columns'].pop()
        self.assertFalse(calibration.verify_schema(obs, binding, 'ou_statement')['passed'])
        obs['ou_report']['snapshots'].pop('statement_schema')
        self.assertFalse(calibration.verify_schema(obs, binding, 'ou_statement')['passed'])

    def test_adapter_controls_mutate_copy_and_check_inconclusive(self):
        binding = {'reports': {role: {'fields': {field: 'Value'}}
                               for role, (_, _, field) in calibration.REPORTS.items()}}
        seen = []

        def compare(observations, mutated, role):
            _, rule, field = calibration.REPORTS[role]
            seen.append((role, mutated['reports'][role]['fields'].get(field)))
            return [{'id': rule, 'verdict': 'inconclusive'}]

        with patch.object(calibration, '_compare', side_effect=compare):
            controls = calibration.adapter_controls({}, binding)
        self.assertEqual(len(controls), 8)
        self.assertTrue(all(c['passed'] for c in controls))
        self.assertEqual(len([v for _, v in seen if v is None]), 4)
        self.assertEqual(len([v for _, v in seen if v == 'BenchNonexistentColumn']), 4)
        self.assertTrue(all(report['fields'] for report in binding['reports'].values()))

    def test_controls_cover_existing_report_rules(self):
        self.assertEqual({rule for _, _, _, rule in calibration.MUTANTS},
                         {'BU16', 'BU17', 'OU19', 'OU20', 'OU21', 'PR19'})


if __name__ == '__main__':
    unittest.main()

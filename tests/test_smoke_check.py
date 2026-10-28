import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from exam_bench import smoke_check as smoke
from exam_bench.preflight import verify_calibration


def fake_generate(starter, target, variant, mutant=None):
    Path(target).mkdir(parents=True)
    (Path(target) / 'Configuration.xml').write_text('<x/>')
    return {'mutant': mutant}


def grading(good_rules, caught=True, errors=None):
    def grade(source, binding, starter, binary, evidence, cases):
        if binding['mutant']:
            return {'rules': [{'id': 'BU13', 'verdict': 'fail' if caught else 'pass'}], 'errors': {}, 'observations': {c: {} for c in cases}}
        return {'rules': good_rules, 'errors': errors or {}, 'observations': {c: {} for c in cases}}
    return grade


class SmokeCheck(unittest.TestCase):
    def run_check(self, grade, query_passed=True, periodicity_passed=True, characteristics_passed=True):
        with tempfile.TemporaryDirectory() as td, \
             patch.object(smoke, 'generate', side_effect=fake_generate), patch.object(smoke, 'grade', side_effect=grade) as g, \
             patch('exam_bench.runtime.require_execution_mode'), \
             patch('exam_bench.calibration_query.run', return_value={'passed': query_passed}), \
             patch('exam_bench.calibration_periodicity.run', return_value={'passed': periodicity_passed}), \
             patch('exam_bench.calibration_characteristics.run', return_value={'passed': characteristics_passed}), \
             patch('exam_bench.runtime.platform_binary', return_value=str(Path('/bin/sh').resolve())), \
             patch('exam_bench.runtime.machine_identity', return_value={'os': 'TestOS'}):
            return smoke.smoke_check(Path(td), Path(td) / 'dt', '/bin/sh', Path(td) / 'smoke'), g

    def test_correct_variant_passes_and_known_mistake_is_caught(self):
        summary, grade = self.run_check(grading([{'id': 'BU13', 'verdict': 'pass'}, {'id': 'PR02', 'verdict': 'inconclusive'}]))
        self.assertTrue(summary['accepted'])
        self.assertEqual(grade.call_count, 2)
        self.assertEqual(grade.call_args_list[0].args[5], smoke.CASES)
        verify_calibration(summary)  # the stand accepts it like a calibration

    def test_any_failure_is_reported(self):
        cases = [(grading([{'id': 'BU13', 'verdict': 'fail'}]), 'correct variant failed: BU13'),
                 (grading([{'id': 'BU13', 'verdict': 'pass'}], caught=False), 'known mistake not caught'),
                 (grading([{'id': 'BU13', 'verdict': 'pass'}], errors={'average': {'kind': 'platform_error_unclassified'}}), '1C errors: average')]
        for grade, reason in cases:
            with self.subTest(reason=reason):
                summary, _ = self.run_check(grade)
                self.assertFalse(summary['accepted'])
                self.assertEqual(summary['reason'], reason)

    def test_failed_query_parameter_calibration_is_reported(self):
        summary, _ = self.run_check(grading([{'id': 'BU13', 'verdict': 'pass'}]), query_passed=False)
        self.assertFalse(summary['accepted'])
        self.assertEqual(summary['reason'], 'table parameter calibration failed')

    def test_failed_periodicity_calibration_is_reported(self):
        summary, _ = self.run_check(grading([{'id': 'BU13', 'verdict': 'pass'}]), periodicity_passed=False)
        self.assertFalse(summary['accepted'])
        self.assertEqual(summary['reason'], 'periodicity calibration failed')

    def test_failed_characteristics_calibration_is_reported(self):
        summary, _ = self.run_check(grading([{'id': 'BU13', 'verdict': 'pass'}]), characteristics_passed=False)
        self.assertFalse(summary['accepted'])
        self.assertEqual(summary['reason'], 'characteristics calibration failed')


if __name__ == '__main__':
    unittest.main()

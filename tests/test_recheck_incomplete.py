import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from tools.community_results import read, write
from tools.recheck_community import recheck
from test_community_results import fixture


class RecheckIncompleteTests(unittest.TestCase):
    def run_recheck(self, root, errors, *, allowed=True, **options):
        folder = fixture(root)
        write(root / 'calibration.json', {})
        task = root / 'tasks/1c-platform-official-sample'
        write(task / 'checks.json', {'requirements': []})
        write(task / 'private/official-assessment-mapping.json', {})
        write(task / 'private/owner-scoring-policy.json', {})
        verification = {'kind': 'repository_owner', 'completed_at': '2026-10-28T12:00:00+00:00'}
        score = {'charges': [], 'score': None, 'score_upper_bound': '5', 'grade': None, 'deductions': '0'}
        assessment = {'score': score, 'statuses': {'F1C-OU01': {'status': 'not_assessed'}}}
        grade = {'rules': [{'id': 'OU01', 'verdict': 'inconclusive'}], 'errors': errors, 'observations': {}}
        patches = {
            'tools.demo_runner.prerequisites': ({'starter_dt': 'starter.dt', 'calibration': 'calibration.json'}, {}),
            'exam_bench.runtime.platform_binary': Path('platform'),
            'exam_bench.runtime.machine_identity': {},
            'exam_bench.common.grading_fingerprint': {},
            'exam_bench.submission.strip_extras': ({}, []),
            'exam_bench.submission.canonical_ledger': ({}, []),
            'exam_bench.submission.check_bindings': None,
            'exam_bench.gates.check_all': ({}, {}, allowed),
            'exam_bench.gates.starter_for': {},
            'exam_bench.grader.grade': grade,
            'exam_bench.penalties.assess': assessment,
            'tools.owner_verification.begin': verification,
        }
        with ExitStack() as stack:
            for name, value in patches.items():
                stack.enter_context(patch(name, return_value=value))
            stack.enter_context(patch('tools.owner_verification.complete', side_effect=lambda value: value))
            return recheck(folder.name, root / 'out', root, owner_server='Owner Windows stand',
                           publish_owner=True, **options)

    def test_observation_errors_are_published_only_with_explicit_flag(self):
        errors = {'ou_assembly': {'kind': 'observation_error', 'message': 'example'}}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaisesRegex(ValueError, 'completed owner recheck'):
                self.run_recheck(root, errors)
            self.assertFalse(list((root / 'community/rechecks').rglob('*.json')))
            self.assertEqual(read(root / 'out/evaluation.json')['errors'], errors)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = self.run_recheck(root, errors, publish_incomplete=True)
            self.assertEqual(read(result)['errors'], errors)
            receipts = list((root / 'community/rechecks').rglob('*.json'))
            self.assertEqual(len(receipts), 1)
            receipt = read(receipts[0])
            self.assertEqual(receipt['owner_verification']['outcome'], 'incomplete')
            self.assertTrue(receipt['result']['infrastructure_errors'])
            self.assertFalse(receipt['result']['comparison_eligible'])

    def test_other_errors_and_failed_gates_are_never_published(self):
        for errors, allowed in [({'load': {'kind': 'platform_error'}}, True), ({}, False),
                                ({'ou': {'kind': 'observation_error'}, 'load': {'kind': 'platform_error'}}, True)]:
            with self.subTest(errors=errors, allowed=allowed), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                with self.assertRaisesRegex(ValueError, 'completed owner recheck'):
                    self.run_recheck(root, errors, allowed=allowed, publish_incomplete=True)
                self.assertFalse(list((root / 'community/rechecks').rglob('*.json')))

    def test_completed_recheck_is_published_normally(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.run_recheck(root, {})
            receipts = list((root / 'community/rechecks').rglob('*.json'))
            self.assertEqual(len(receipts), 1)
            receipt = read(receipts[0])
            self.assertNotIn('outcome', receipt['owner_verification'])
            self.assertFalse(receipt['result']['infrastructure_errors'])

    def test_flag_requires_owner_publication(self):
        with self.assertRaisesRegex(ValueError, 'requires --publish-owner'):
            recheck('example', 'unused', publish_incomplete=True)

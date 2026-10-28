import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from exam_bench.common import digest, grading_fingerprint, tree_manifest
from tools.community_results import export_public, read, write
from tools.owner_verification import begin, complete, fingerprint_id, publish, public_observation_errors
from test_community_results import fixture


class OwnerVerification(unittest.TestCase):
    def receipt(self, root, folder, *, incomplete=False):
        files = grading_fingerprint()
        v = {'kind': 'repository_owner', 'repository': 'zeegin/1c-agent-exam-benchmark',
             'operator': {'name': 'Owner', 'github': 'zeegin'},
             'started_at': '2026-10-26T10:00:00+00:00', 'completed_at': '2026-10-26T11:00:00+00:00',
             'server': {'name': 'Review Windows', 'os': {'system': 'Windows'},
                        'hardware': {'cpu': 'CPU', 'ram_bytes': 16 * 1024**3}, 'isolation': 'dedicated-host'},
             'platform_version': '8.3.27.2342',
             'grader': {'profile': 'technical-v8', 'commit': 'abc', 'working_tree_dirty': False,
                        'fingerprint': files, 'sha256': fingerprint_id(files)}}
        record = {'original_manifest_sha256': digest(folder / 'manifest.json'),
                  'owner_verification': v, 'rules': [{'id': 'PR14', 'verdict': 'inconclusive'}],
                  'assessment': {'score': {'charges': [], 'score': None, 'score_upper_bound': '5',
                                         'grade': None, 'deductions': '0'},
                                 'statuses': {'F1C-PR11': {'status': 'not_assessed'}}},
                  'errors': {}, 'gates': {}}
        if incomplete:
            v['outcome'] = 'incomplete'
            record['errors'] = {'ou_assembly': {'kind': 'observation_error', 'message':
                'Значение поля не соответствует установленному отбору: '
                'Регистр сведений: Спецификации; Поле: Период; C:\\Users\\private\\db'}}
        return publish(record, folder, root, allow_incomplete=incomplete)

    def test_revision_keeps_author_and_original_bytes_with_separate_verification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); folder = fixture(root)
            original = tree_manifest(folder)
            path = self.receipt(root, folder)
            export_public(root, root / 'dist')
            row = read(root / 'dist/community.json')['results'][0]
            self.assertEqual(row['verification'], 'repository_owner')
            self.assertEqual(row['measurement']['operator']['github'], 'tester')
            self.assertEqual(row['owner_verification']['operator']['github'], 'zeegin')
            self.assertEqual(row['owner_verification']['platform_version'], '8.3.27.2342')
            self.assertEqual(row['regrade_required'], [])
            self.assertIsNone(row['result']['score'])  # owner badge does not make coverage complete
            self.assertEqual(row['previous_evaluations'][0]['verification'], 'contributor_reported')
            with zipfile.ZipFile(root / 'dist' / row['download']) as z:
                self.assertEqual(z.read('owner-recheck.json'), path.read_bytes())
                self.assertEqual(z.read('original/solution.dt'), (folder / 'solution.dt').read_bytes())
            self.assertEqual(tree_manifest(folder), original)

    def test_telemetry_compatibility_keeps_receipt_history_without_falsely_regrading(self):
        from test_grading_compatibility import OLD, NEW
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); folder = fixture(root)
            current = grading_fingerprint()
            self.assertEqual(current['claude.py'], NEW)
            previous = {**current, 'claude.py': OLD}
            with patch('test_owner_verification.grading_fingerprint', return_value=previous):
                path = self.receipt(root, folder)
            before = path.read_bytes()
            export_public(root, root / 'dist')
            row = read(root / 'dist/community.json')['results'][0]
            self.assertEqual(row['regrade_required'], [])
            self.assertEqual(row['owner_verification']['grader']['fingerprint']['claude.py'], OLD)
            self.assertEqual(path.read_bytes(), before)
            self.assertTrue(row['previous_evaluations'])

    def test_rejects_wrong_owner_source_or_fingerprint(self):
        for field in ('owner', 'source', 'fingerprint'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                root = Path(td); folder = fixture(root); path = self.receipt(root, folder)
                receipt = read(path)
                if field == 'owner': receipt['owner_verification']['operator']['github'] = 'tester'
                if field == 'source': receipt['original_manifest_sha256'] = 'wrong'
                if field == 'fingerprint': receipt['owner_verification']['grader']['sha256'] = 'wrong'
                write(path, receipt)
                with self.assertRaisesRegex(ValueError, 'Invalid owner'):
                    export_public(root, root / 'dist')

    def test_only_owner_account_can_begin(self):
        with patch('tools.owner_verification.github_identity', return_value={'github': 'tester'}), \
             patch('tools.owner_verification.command', return_value=json.dumps({'owner': {'login': 'zeegin'}})):
            with self.assertRaisesRegex(ValueError, 'repository owner GitHub'):
                begin(Path('.'), {}, 'Public server')

    def test_changed_grader_cannot_finish(self):
        with self.assertRaisesRegex(ValueError, 'Grader changed'):
            complete({'grader': {'fingerprint': {'old.py': 'old'}}})

    def test_incomplete_recheck_cannot_be_published(self):
        with self.assertRaisesRegex(ValueError, 'completed owner recheck'):
            publish({}, Path('.'), Path('.'))

    def test_explicit_incomplete_recheck_remains_unranked_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); folder = fixture(root)
            path = self.receipt(root, folder, incomplete=True)
            export_public(root, root / 'dist')
            row = read(root / 'dist/community.json')['results'][0]
            self.assertEqual(row['verification'], 'repository_owner_incomplete')
            self.assertTrue(row['result']['infrastructure_errors'])
            self.assertFalse(row['result']['comparison_eligible'])
            self.assertEqual(row['previous_evaluations'][0]['verification'], 'contributor_reported')
            errors = row['result']['observation_errors']
            self.assertEqual(errors[0]['scenario'], 'ou_assembly')
            self.assertIn('период записи не соответствует отбору', errors[0]['reason'])
            self.assertNotIn('C:\\Users\\private', json.dumps(errors, ensure_ascii=False))
            with zipfile.ZipFile(root / 'dist' / row['download']) as z:
                receipt = json.loads(z.read('owner-recheck.json'))
                self.assertEqual(receipt['result']['observation_errors'], errors)
                self.assertEqual(z.read('owner-recheck.json'), path.read_bytes())

    def test_unknown_errors_never_expose_raw_messages_or_untrusted_case_names(self):
        errors = public_observation_errors({
            'ou_history': {'kind': 'observation_error', 'message': 'C:\\Users\\private\\secret'},
            'C:\\Users\\private\\bad': {'kind': 'observation_error', 'message': '<script>secret</script>'},
        })
        self.assertEqual({x['scenario'] for x in errors}, {'ou_history', 'other'})
        self.assertNotIn('private', json.dumps(errors, ensure_ascii=False))
        self.assertNotIn('secret', json.dumps(errors, ensure_ascii=False))

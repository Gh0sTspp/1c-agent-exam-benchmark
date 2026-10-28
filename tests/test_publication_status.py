import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools.community_results import write
from tools.publication_status import _scan_remote, publication_index
from tools.community_service import start


class PublicationStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.job('demo-original', 'run-original', 'tester')
        self.job('demo-regrade', 'run-original', 'tester')
        self.job('demo-new', 'run-new', 'tester')

    def job(self, name, run, login):
        folder = self.root / '.local/demo/jobs' / name
        write(folder / 'status.json', {'run_id': run, 'phase': 'finished', 'mode': 'run', 'started_unix': 1})
        write(folder / 'evaluation.json', {})
        write(folder / 'measurement.json', {'operator': {'github': login}})

    def index(self, entries, checking=False):
        with patch('tools.publication_status.remote_entries', return_value=(entries, checking)):
            return publication_index(self.root)

    def test_published_identity_covers_regrades_and_takes_precedence(self):
        write(self.root / 'community/results/demo-original/manifest.json',
              {'submission_id': 'demo-original', 'run_id': 'run-original'})
        write(self.root / '.local/community/pr/demo-original.json',
              {'url': 'https://github.com/zeegin/1c-agent-exam-benchmark/pull/55'})
        lookup = self.index(None)
        self.assertEqual(lookup('run-original'), {'state': 'published', 'blocked': True})
        self.assertEqual(lookup('run-new'), {'state': 'unknown', 'blocked': True})

    def test_older_regrade_can_resolve_run_from_evaluation(self):
        folder = self.root / '.local/demo/jobs/demo-regrade'
        write(folder / 'status.json', {'phase': 'finished', 'mode': 'regrade', 'started_unix': 1})
        write(folder / 'evaluation.json', {'run_id': 'run-original'})
        url = 'https://github.com/zeegin/1c-agent-exam-benchmark/pull/55'
        write(self.root / '.local/community/pr/demo-regrade.json', {'url': url})
        self.assertEqual(self.index(None)('run-original'), {'state': 'unknown', 'url': url, 'blocked': True})

    def test_open_merged_closed_and_unknown_receipt_are_distinct(self):
        url = 'https://github.com/zeegin/1c-agent-exam-benchmark/pull/55'
        write(self.root / '.local/community/pr/demo-original.json', {'url': url})
        self.assertEqual(self.index(None)('run-original'), {'state': 'unknown', 'url': url, 'blocked': True})
        for state, expected in [('OPEN', 'submitted'), ('MERGED', 'published'), ('CLOSED', 'closed')]:
            with self.subTest(state=state):
                lookup = self.index([{'url': url, 'state': state}])
                self.assertEqual(lookup('run-original'), {'state': expected, 'url': url, 'blocked': True})

    def test_remote_branch_requires_correct_owner_and_exact_job(self):
        url = 'https://github.com/zeegin/1c-agent-exam-benchmark/pull/56'
        pr = {'url': url, 'state': 'OPEN', 'headRefName': 'result/demo-regrade',
              'headRepositoryOwner': {'login': 'tester'}}
        self.assertEqual(self.index([pr])('run-original')['state'], 'submitted')
        pr['headRepositoryOwner']['login'] = 'someone-else'
        self.assertEqual(self.index([pr])('run-original')['state'], 'unknown')
        pr['headRepositoryOwner']['login'] = 'tester'
        pr['headRefName'] = 'result/demo-other'
        self.assertEqual(self.index([pr])('run-original')['state'], 'unknown')

    def test_untrusted_urls_and_unrelated_manifests_do_not_count(self):
        write(self.root / 'community/results/other/manifest.json',
              {'submission_id': 'not-other', 'run_id': 'run-original'})
        write(self.root / '.local/community/pr/demo-original.json', {'url': 'https://attacker.invalid/pr/55'})
        self.assertEqual(self.index([])('run-original'), {'state': 'unknown', 'blocked': False})
        self.assertTrue(self.index(None, checking=True)('run-new')['blocked'])

    def test_network_failure_blocks_known_author_but_not_a_new_anonymous_run(self):
        self.job('demo-anonymous', 'run-anonymous', '')
        self.assertEqual(self.index(None)('run-original'), {'state': 'unknown', 'blocked': True})
        self.assertEqual(self.index(None)('run-anonymous'), {'state': 'unknown', 'blocked': False})
        self.assertEqual(self.index([])('run-original'), {'state': 'unknown', 'blocked': False})
        self.assertEqual(self.index([{}] * 200)('run-original'), {'state': 'unknown', 'blocked': True})

    def test_service_rejects_duplicate_but_new_run_can_prepare(self):
        write(self.root / 'community/results/demo-original/manifest.json',
              {'submission_id': 'demo-original', 'run_id': 'run-original'})
        with patch('tools.publication_status.remote_entries', return_value=([], False)):
            with patch('tools.community_service.subprocess.Popen', return_value=Mock(pid=123)) as spawn:
                for action in ('prepare', 'pr'):
                    with self.assertRaisesRegex(ValueError, 'уже опубликован'):
                        start(action, {'id': 'demo-regrade'}, self.root)
                spawn.assert_not_called()
                self.assertEqual(start('prepare', {'id': 'demo-new'}, self.root), {'started': True})
                spawn.assert_called_once()

    def test_background_github_process_does_not_hold_workspace_directory(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def run(*args, **kwargs):
            calls.append(kwargs)
            entered.set()
            self.assertTrue(release.wait(5))
            return Mock(returncode=0, stdout='[]')
        with patch('tools.publication_status.executable', return_value='gh'), \
             patch('tools.publication_status.subprocess.run', side_effect=run):
            thread = threading.Thread(target=_scan_remote, args=(self.root,))
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertNotEqual(Path(calls[0]['cwd']), self.root)
                self.temp.cleanup()
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()

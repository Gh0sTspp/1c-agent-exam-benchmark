import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools.community_results import write
from tools.publication_status import _cache, _scan_remote, publication_index
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

    def test_foreign_branch_is_not_treated_as_our_submission(self):
        url = 'https://github.com/zeegin/1c-agent-exam-benchmark/pull/56'
        foreign = {'url': url, 'state': 'OPEN', 'headRefName': 'result/demo-regrade',
                   'headRepositoryOwner': {'login': 'other'}}
        def response(target):
            return ([foreign], False) if target == ('branch', 'tester', 'demo-regrade') else ([], False)
        with patch('tools.publication_status.remote_entries', side_effect=response):
            self.assertEqual(publication_index(self.root)('run-original'), {'state': 'unknown', 'blocked': False})

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
            thread = threading.Thread(target=_scan_remote, args=(('branch', 'tester', 'demo-new'),))
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertNotEqual(Path(calls[0]['cwd']), self.root)
                self.temp.cleanup()
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())

    def test_remote_queries_target_the_exact_branch_and_saved_pr(self):
        url = 'https://github.com/zeegin/1c-agent-exam-benchmark/pull/55'
        responses = [Mock(returncode=0, stdout='[]'),
                     Mock(returncode=0, stdout='{"url":"' + url + '","state":"CLOSED"}')]
        with patch('tools.publication_status.executable', return_value='gh'), \
             patch('tools.publication_status.subprocess.run', side_effect=responses) as run:
            _scan_remote(('branch', 'tester', 'demo-new'))
            _scan_remote(('url', url))
        branch = run.call_args_list[0].args[0]
        saved_pr = run.call_args_list[1].args[0]
        self.assertEqual(branch[1:4], ['api', '--method', 'GET'])
        self.assertIn('head=tester:result/demo-new', branch)
        self.assertEqual(saved_pr[1:4], ['pr', 'view', url])
        self.assertTrue(all(call.kwargs['timeout'] == 10 for call in run.call_args_list))

    def test_many_unrelated_pull_requests_do_not_block_new_branch(self):
        # The remote response is scoped to this branch; unrelated repository PRs
        # never enter the result, regardless of their number.
        self.assertEqual(self.index([])('run-new'), {'state': 'unknown', 'blocked': False})

    def test_malformed_rest_head_is_unknown_and_worker_result_is_not_stuck(self):
        target = ('branch', 'tester', 'demo-bad')
        with patch('tools.publication_status.executable', return_value='gh'), \
             patch('tools.publication_status.subprocess.run', return_value=Mock(returncode=0, stdout='[{"head":"wrong"}]')):
            _scan_remote(target)
        self.assertIsNone(_cache[target]['entries'])
        self.assertFalse(_cache[target]['working'])

    def test_rest_merged_and_graphql_closed_are_distinguished(self):
        import json
        url = 'https://github.com/zeegin/1c-agent-exam-benchmark/pull/55'
        rest = [{'html_url': url, 'state': 'closed', 'merged_at': '2026-10-29T01:00:00Z',
                 'head': {'ref': 'result/demo-new', 'user': {'login': 'tester'}}}]
        graph = {'url': url, 'state': 'CLOSED'}
        responses = [Mock(returncode=0, stdout=json.dumps(rest)), Mock(returncode=0, stdout=json.dumps(graph))]
        with patch('tools.publication_status.executable', return_value='gh'), \
             patch('tools.publication_status.subprocess.run', side_effect=responses):
            _scan_remote(('branch', 'tester', 'demo-new'))
            _scan_remote(('url', url))
        self.assertEqual(_cache[('branch', 'tester', 'demo-new')]['entries'][0]['state'], 'MERGED')
        self.assertEqual(_cache[('url', url)]['entries'][0]['state'], 'CLOSED')


if __name__ == '__main__':
    unittest.main()

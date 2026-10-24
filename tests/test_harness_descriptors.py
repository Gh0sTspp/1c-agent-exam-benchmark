import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from exam_bench import portable_harnesses as native
from exam_bench.common import digest
from tools import check_native_harnesses as checks
from tools import prepare_native_harnesses as prepare

ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def one_harness(root):
    """A stand whose only harness, test-1, copies one downloaded file into its package."""
    (root / 'harnesses').mkdir(); (root / 'profiles').mkdir()
    asset = root / 'tool.exe'; asset.write_bytes(b'fixture tool')
    configuration = {'version': '1', 'label': 'Test', 'command': '{package}/tool.exe', 'registration': 'test'}
    (root / 'harnesses/test-1.json').write_text(json.dumps({'schema_version': 1, 'id': 'test-1', 'label': 'Test', 'probe': None,
        'targets': {'test-x64': {'downloads': {'tool.exe': {'url': 'https://example.org/tool.exe', 'sha256': digest(asset)}},
                                 'install': [{'copy': 'tool.exe', 'to': 'tool.exe'}], 'configuration': configuration}}}))
    with patch.object(prepare, 'ROOT', root), patch.object(prepare, 'CATALOGUE', root / 'harnesses'), \
         patch.object(checks, 'ROOT', root), patch.object(native, 'ROOT', root), \
         patch.object(prepare, 'target', return_value='test-x64'), patch.object(prepare, 'download', return_value=asset) as download:
        yield configuration, download


class Descriptors(unittest.TestCase):
    def test_shipped_descriptors_are_valid_and_reference_their_downloads(self):
        docs = prepare.catalogue()
        self.assertIn('unica-0.14.0-rc.1', docs)
        for name, doc in docs.items():
            for target in doc['targets'].values():
                for step in target['install']:
                    kind = next(iter(set(step) & prepare.STEPS))
                    if kind in ('copy', 'unzip', 'unzip-source', 'verified-entrypoint'):
                        self.assertIn(step[kind], target['downloads'], name)
                    if kind == 'pip':
                        self.assertTrue((ROOT / step[kind]).is_file(), name)

    def test_unsafe_descriptors_are_refused(self):
        base = {'schema_version': 1, 'id': 'x', 'targets': {'windows-x64': {
            'downloads': {'a.zip': {'url': 'https://example.org/a.zip', 'sha256': '0' * 64}},
            'install': [{'unzip': 'a.zip'}], 'configuration': {'command': '{package}/x.exe'}}}}
        prepare.validate(base, 'x')
        with self.assertRaisesRegex(ValueError, 'match'):
            prepare.validate(base, 'y')
        script = json.loads(json.dumps(base)); script['targets']['windows-x64']['install'] = [{'run': 'setup.cmd'}]
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            prepare.validate(script, 'x')
        plain = json.loads(json.dumps(base)); plain['targets']['windows-x64']['downloads']['a.zip']['url'] = 'http://example.org/a.zip'
        with self.assertRaisesRegex(ValueError, 'https'):
            prepare.validate(plain, 'x')

    def test_one_harness_installs_from_its_descriptor_and_is_sealed(self):
        with tempfile.TemporaryDirectory() as td, one_harness(Path(td)) as (configuration, _):
            root = Path(td)
            self.assertTrue(prepare.install('test-1'))
            self.assertEqual((root / '.local/harnesses/test-1/package/tool.exe').read_bytes(), b'fixture tool')
            self.assertEqual(native.registry()['test-1'], configuration)
            self.assertEqual(json.loads((root / '.local/harnesses/test-1/profile.json').read_text())['target'], 'test-x64')
            self.assertFalse((root / 'profiles/test-1-portable.json').exists())  # Git is not touched by an install
            native.verify('test-1', require_probe=False)
            self.assertFalse(prepare.install('test-1'))  # sealed installs are never overwritten

    def test_interrupted_attempt_starts_again_but_an_earlier_installation_is_kept(self):
        with tempfile.TemporaryDirectory() as td, one_harness(Path(td)) as (_, download):
            base = Path(td) / '.local/harnesses/test-1'
            download.side_effect = TimeoutError('timed out')
            with self.assertRaises(TimeoutError):
                prepare.install('test-1')
            self.assertFalse(base.exists())  # a failed download leaves no folder
            download.side_effect = None
            with patch.object(prepare, 'run_step', side_effect=OSError('step failed')), self.assertRaises(OSError):
                prepare.install('test-1')
            self.assertEqual([p.name for p in base.iterdir()], ['package'])
            (base / 'source').mkdir(); (base / 'package/partial.bin').write_bytes(b'x')
            self.assertTrue(prepare.install('test-1'))
            self.assertEqual([p.name for p in (base / 'package').iterdir()], ['tool.exe'])
        with tempfile.TemporaryDirectory() as td, one_harness(Path(td)):
            base = Path(td) / '.local/harnesses/test-1'
            (base / 'package').mkdir(parents=True); (base / 'notes.txt').write_text('earlier format')
            with self.assertRaisesRegex(ValueError, 'прежнего формата'):
                prepare.install('test-1')
            self.assertTrue((base / 'notes.txt').is_file())


class Response(io.BytesIO):
    """What urlopen returns: a status and a body that ends cleanly or, given an error, breaks off."""
    def __init__(self, body, status=200, error=None):
        super().__init__(body); self.status, self.error = status, error

    def read(self, size=-1):
        chunk = super().read(size)
        if not chunk and self.error:
            raise self.error
        return chunk


class Downloads(unittest.TestCase):
    BODY = bytes(range(256)) * 40
    RELEASE = 'https://github.com/me/tool/releases/download/v1/tool.zip'
    ARCHIVE = 'https://codeload.github.com/me/tool/zip/refs/tags/v1'

    def record(self, url):
        return {'url': url, 'sha256': hashlib.sha256(self.BODY).hexdigest(), 'bytes': len(self.BODY)}

    @contextlib.contextmanager
    def stand(self, *answers):
        """urlopen gives these answers in turn; pauses between attempts are recorded, not waited."""
        with tempfile.TemporaryDirectory() as td, patch.object(prepare, 'ROOT', Path(td)), \
             patch.object(prepare.urllib.request, 'urlopen', side_effect=answers) as urlopen, \
             patch.object(prepare.time, 'sleep') as sleep:
            yield Path(td) / '.local/downloads/harnesses', urlopen, sleep

    @staticmethod
    def ranges(urlopen):
        return [c.args[0].get_header('Range') for c in urlopen.call_args_list]

    def test_a_release_asset_resumes_after_a_broken_transfer(self):
        with self.stand(Response(self.BODY[:4096], error=TimeoutError('timed out')),
                        Response(self.BODY[4096:], status=206)) as (folder, urlopen, sleep):
            self.assertEqual(prepare.download('tool.zip', self.record(self.RELEASE)).read_bytes(), self.BODY)
            self.assertEqual(self.ranges(urlopen), [None, 'bytes=4096-'])
            sleep.assert_called_once_with(5)
            self.assertEqual([p.name for p in folder.iterdir()], ['tool.zip'])

    def test_an_archive_without_range_support_is_downloaded_again(self):
        # codeload.github.com may end the stream early without an error and answers Range with 200
        with self.stand(Response(self.BODY[:4096]), Response(self.BODY)) as (_, urlopen, sleep):
            self.assertEqual(prepare.download('tool.zip', self.record(self.ARCHIVE)).read_bytes(), self.BODY)
            self.assertEqual(self.ranges(urlopen), [None, 'bytes=4096-'])
            sleep.assert_called_once_with(5)

    def test_the_last_failure_names_the_manual_route_which_skips_the_download(self):
        with self.stand(*[urllib.error.URLError('timed out')] * 4) as (folder, urlopen, sleep):
            with self.assertRaisesRegex(ValueError, r'\.local/downloads/harnesses/tool\.zip'):
                prepare.download('tool.zip', self.record(self.ARCHIVE))
            self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 15, 45])
            (folder / 'tool.zip').write_bytes(self.BODY)  # put there by hand
            self.assertEqual(prepare.download('tool.zip', self.record(self.ARCHIVE)), folder / 'tool.zip')
            self.assertEqual(urlopen.call_count, 4)

    def test_a_missing_file_is_not_requested_again(self):
        with self.stand(urllib.error.HTTPError(self.RELEASE, 404, 'Not Found', {}, None)) as (_, urlopen, sleep):
            with self.assertRaisesRegex(ValueError, '404'):
                prepare.download('tool.zip', self.record(self.RELEASE))
            sleep.assert_not_called()

    def test_size_is_checked_before_the_hash_and_a_wrong_download_is_discarded(self):
        record = self.record(self.RELEASE)
        with self.stand(Response(self.BODY[::-1])) as (folder, _, _):
            with self.assertRaisesRegex(ValueError, 'checksum'):
                prepare.download('tool.zip', record)
            self.assertEqual(list(folder.iterdir()), [])  # the next attempt starts afresh
            (folder / 'tool.zip').write_bytes(self.BODY[:100])
            with patch.object(prepare.hashlib, 'sha256', side_effect=AssertionError('hashed')), \
                 self.assertRaisesRegex(ValueError, '100 байт вместо 10240'):
                prepare.download('tool.zip', record)


class PosixInstallSteps(unittest.TestCase):
    @unittest.skipIf(prepare.os.name == 'nt', 'POSIX permissions')
    def test_zip_keeps_execute_bits(self):
        import zipfile
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / 'a.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                info = zipfile.ZipInfo('bin/tool'); info.external_attr = 0o755 << 16
                z.writestr(info, b'#!/bin/sh\n'); z.writestr('README', b'x')
            prepare.unzip(archive, Path(td) / 'out')
            self.assertTrue((Path(td) / 'out/bin/tool').stat().st_mode & 0o100)
            self.assertFalse((Path(td) / 'out/README').stat().st_mode & 0o100)

    def test_tar_cannot_escape_the_package(self):
        import io, tarfile
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / 'a.tar.gz'
            with tarfile.open(archive, 'w:gz') as t:
                info = tarfile.TarInfo('../escape'); info.size = 1
                t.addfile(info, io.BytesIO(b'x'))
            with self.assertRaises(Exception):
                prepare.untar(archive, Path(td) / 'out')
            self.assertFalse((Path(td) / 'escape').exists())

    def test_npm_packages_for_other_systems_are_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            (project / 'package-lock.json').write_text(json.dumps({'packages': {
                '': {}, 'node_modules/win': {'os': ['win32'], 'resolved': 'x', 'integrity': 'sha512-x'},
                'node_modules/arm': {'os': ['darwin'], 'cpu': ['arm64'], 'resolved': 'y', 'integrity': 'sha512-y'}}}))
            with patch.object(prepare.urllib.request, 'urlopen', side_effect=AssertionError('downloaded')):
                prepare.npm_locked(project, 'linux-x64')  # nothing applies to Linux x64
            with patch.object(prepare.urllib.request, 'urlopen', side_effect=RuntimeError('fetch')) as fetch:
                with self.assertRaises(RuntimeError):
                    prepare.npm_locked(project, 'macos-arm64')
                self.assertIn('y', str(fetch.call_args))


if __name__ == '__main__':
    unittest.main()

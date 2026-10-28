import re
import unittest

from tools.build_public_site import PUBLIC, ROOT


class PublicSiteAssetsTest(unittest.TestCase):
    def test_static_module_dependencies_are_published(self):
        # A missing ES module prevents the entire leaderboard from starting in a browser.
        html = (ROOT / 'site/leaderboard.html').read_text(encoding='utf-8')
        pending = re.findall(r'<script\b[^>]*\bsrc=["\']([^"\']+)["\']', html)
        visited = set()
        while pending:
            name = pending.pop()
            if name in visited:
                continue
            visited.add(name)
            self.assertIn(name, PUBLIC, f'{name} is required by the public leaderboard')
            source = (ROOT / 'site' / name).read_text(encoding='utf-8')
            pending.extend(re.findall(r'^\s*import\s+(?:[^\n]*?\s+from\s+)?["\']\./([^"\']+)["\']', source, re.MULTILINE))

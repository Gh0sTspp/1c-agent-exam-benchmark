"""Build Pages from committed results only, even when invoked in a populated local checkout.

The public site is the leaderboard alone: no methodology, task materials or local stand pages.
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ('leaderboard.html', 'leaderboard.js', 'nav.js', 'style.css', 'community.json',
          'penalty-cards.js', 'penalty-info.json', 'source-viewer.js', 'api-cost.js')
sys.path.insert(0, str(ROOT))


def build_public(root=ROOT):
    from tools.build_result_site import build
    # The public builder cannot see .local, credentials, logs or in-flight attempts.
    with tempfile.TemporaryDirectory(prefix='public-site-') as td:
        clean = Path(td)
        for name in ('site', 'rules', 'starters', 'tasks', 'community', 'docs'):
            shutil.copytree(root / name, clean / name, ignore=shutil.ignore_patterns('dist', 'dist-public', '.dist-staging', '__pycache__', '*.zip'))
        build(clean, catalogue_only=True)
        dist = clean / 'site/dist'
        target = root / 'site/dist-public'
        if target.exists(): shutil.rmtree(target)
        target.mkdir(parents=True)
        for name in PUBLIC:
            shutil.copyfile(dist / name, target / name)
        shutil.copyfile(dist / 'leaderboard.html', target / 'index.html')
        if (dist / 'community-downloads').is_dir():
            shutil.copytree(dist / 'community-downloads', target / 'community-downloads')
        (target / '.nojekyll').touch()
    return target


if __name__ == '__main__':
    print(build_public())

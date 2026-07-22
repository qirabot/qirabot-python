"""Drift guard: the wheel's skill payload must mirror plugins/qirabot/skills/qirabot/.

The plugins/ copy is canonical (the claude-plugins marketplace pulls it via
git-subdir); src/qirabot/skill-data/ is what pip installs ship. Edit under
plugins/ and run scripts/sync_skill.py to update the mirror.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CANONICAL = REPO / "plugins" / "qirabot" / "skills" / "qirabot"
BUNDLED = REPO / "src" / "qirabot" / "skill-data"


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


@pytest.mark.skipif(not CANONICAL.is_dir(), reason="plugins/ not present in this checkout")
def test_bundled_payload_mirrors_plugins():
    src = _tree(CANONICAL)
    dst = _tree(BUNDLED) if BUNDLED.is_dir() else {}
    diffs = sorted(rel for rel in src.keys() | dst.keys() if src.get(rel) != dst.get(rel))
    assert not diffs, (
        f"skill payload out of sync: {diffs} — run: python scripts/sync_skill.py"
    )

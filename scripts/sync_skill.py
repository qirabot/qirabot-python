#!/usr/bin/env python3
"""Sync the Agent Skill payload from plugins/ into the installable package.

The canonical skill source lives at plugins/qirabot/skills/qirabot/ (the
qirabot/claude-plugins marketplace pulls that directory via git-subdir). The
wheel ships a byte-for-byte mirror at src/qirabot/skill-data/ so that
`qirabot skill install` works from any pip install. This script keeps the two
trees identical; tests/test_skill_sync.py fails CI when they drift.

Usage:
    python scripts/sync_skill.py          # overwrite src/qirabot/skill-data/
    python scripts/sync_skill.py --check  # exit 1 if the trees differ
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "plugins" / "qirabot" / "skills" / "qirabot"
DST = REPO / "src" / "qirabot" / "skill-data"

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def check() -> int:
    src, dst = _tree(SRC), _tree(DST) if DST.is_dir() else {}
    diffs = sorted(
        {rel for rel in src.keys() | dst.keys() if src.get(rel) != dst.get(rel)}
    )
    if not diffs:
        return 0
    print(f"skill payload out of sync ({SRC} vs {DST}):")
    for rel in diffs:
        state = "missing" if rel not in dst else "extra" if rel not in src else "differs"
        print(f"  {state}: {rel}")
    print("run: python scripts/sync_skill.py")
    return 1


def sync() -> int:
    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST, ignore=IGNORE)
    print(f"synced {SRC} -> {DST}")
    return 0


if __name__ == "__main__":
    if not SRC.is_dir():
        print(f"source not found: {SRC}", file=sys.stderr)
        sys.exit(2)
    sys.exit(check() if "--check" in sys.argv[1:] else sync())

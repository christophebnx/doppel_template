"""Next free identifier.

  ids.py next task         -> T-0001   (tasks/ and tasks/_archive/)
  ids.py next question     -> Q-001    (questions.md + inbox/_processed/ where answered questions are archived)

A domain module adds its kinds to KINDS: (prefix, width, globs, mode) with mode = name | frontmatter | content.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from common import get_root

KINDS = {
    "task": ("T", 4, ["tasks/T-*.md", "tasks/_archive/**/T-*.md", "archive/projects/*/tasks/T-*.md"], "name"),
    "question": ("Q", 3, ["questions.md", "inbox/_processed/*.md"], "content"),
}


def used_numbers(root: Path, kind: str) -> set[int]:
    prefix, _, globs, mode = KINDS[kind]
    rx = re.compile(rf"\b{prefix}-(\d+)\b")
    nums: set[int] = set()
    for g in globs:
        for p in root.glob(g):
            if mode == "name":
                text = p.name
            elif mode == "frontmatter":  # only the `id:` line (meeting minutes mention other ids in their body)
                m = re.search(rf"^id:\s*({prefix}-\d+)\s*$", p.read_text(encoding="utf-8", errors="ignore"), re.M)
                text = m.group(1) if m else ""
            else:
                text = p.read_text(encoding="utf-8", errors="ignore")
            nums.update(int(x) for x in rx.findall(text))
    return nums


def next_id(root: Path, kind: str) -> str:
    prefix, width, _, _ = KINDS[kind]
    n = max(used_numbers(root, kind), default=0) + 1
    return f"{prefix}-{n:0{width}d}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("next"); n.add_argument("kind", choices=sorted(KINDS))
    args = ap.parse_args(argv)
    print(next_id(get_root(args.root), args.kind))
    return 0


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))

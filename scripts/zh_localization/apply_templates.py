# -*- coding: utf-8 -*-
"""将标注模板 YAML 中的标题/分组/说明/可见标签汉化。"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from templates_dict import GROUPS, TITLES, H1, DT, LABELS  # noqa: E402

TAG_VALUE_RE = re.compile(r'(<(?:Header|Label|Choice|Button|Column|TextArea|Rating)\b[^>]*?\bvalue=")([^"]*)(")')


def replace_exact(text, mapping):
    """按整串精确匹配替换（仅处理出现在行内/标签值中的场景）。"""
    out = text
    for key, zh in mapping.items():
        if key in out:
            out = out.replace(key, zh)
    return out


def process(path, dry_run=False):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    orig = text

    # title / group 行
    def line_replace(m):
        return m.group(0)

    for key, zh in {**GROUPS, **TITLES}.items():
        text = re.sub(r"^(title|group):\s*" + re.escape(key) + r"\s*$", lambda m: m.group(1) + ": " + zh, text, flags=re.M)

    # details 中的 h1 / dt / dd
    for key, zh in {**H1, **DT}.items():
        text = text.replace(key, zh)

    # config 中可见标签 value
    def repl(m):
        val = m.group(2)
        if val in LABELS:
            return m.group(1) + LABELS[val] + m.group(3)
        return m.group(0)

    text = TAG_VALUE_RE.sub(repl, text)

    if text == orig:
        return 0
    if dry_run:
        print(f"[dry-run] {path}")
        return 1
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    print(f"[ok] {path}")
    return 1


def main():
    root = Path("label_studio/annotation_templates")
    dry = "--dry-run" in sys.argv
    total = 0
    for p in sorted(root.rglob("config.yml")):
        total += process(p, dry_run=dry)
    print(f"TOTAL {total}")


if __name__ == "__main__":
    main()

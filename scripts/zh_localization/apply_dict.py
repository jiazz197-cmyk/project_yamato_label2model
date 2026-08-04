# -*- coding: utf-8 -*-
"""按词库批量替换源码中的用户可见文案（仅替换精确命中项）。"""

import argparse
import re
import sys
from pathlib import Path
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parent))
from main_app_dict import DICT, TEXT_DICT  # noqa: E402
from more_dict import DICT as MORE_DICT, TEXT as MORE_TEXT  # noqa: E402

DICT = {**DICT, **MORE_DICT}
TEXT_DICT = {**TEXT_DICT, **MORE_TEXT}

JSX_RE = re.compile(r"(?:>|\})\s*([^<>{}\n]+?)\s*(?=<)")


def mask_comments(text):
    """返回同长度字符串，注释位置用 \\0 占位；字符串内的 // 不会被误判为注释。"""
    chars = list(text)
    i = 0
    n = len(text)
    mode = "code"  # code | dq | sq | tick | line | block
    while i < n:
        c = text[i]
        if mode == "code":
            if c == "/" and i + 1 < n and text[i + 1] == "/":
                mode = "line"
                i += 1
            elif c == "/" and i + 1 < n and text[i + 1] == "*":
                mode = "block"
                i += 1
            elif c == "/" and i + 1 < n and text[i + 1] not in ("/", "*") and _is_regex_like(text, i):
                j = i + 1
                in_class = False
                while j < n:
                    ch = text[j]
                    if ch == "\\":
                        j += 2
                        continue
                    if ch == "[":
                        in_class = True
                    elif ch == "]":
                        in_class = False
                    elif ch == "/" and not in_class:
                        break
                    j += 1
                i = j + 1 if j < n else n
            elif c == '"':
                mode = "dq"
                i += 1
            elif c == "'":
                mode = "sq"
                i += 1
            elif c == "`":
                mode = "tick"
                i += 1
            else:
                i += 1
        elif mode == "dq":
            if c == "\\":
                i += 2
                continue
            if c == '"':
                mode = "code"
            i += 1
        elif mode == "sq":
            if c == "\\":
                i += 2
                continue
            if c == "'":
                mode = "code"
            i += 1
        elif mode == "tick":
            if c == "\\":
                i += 2
                continue
            if c == "`":
                mode = "code"
            i += 1
        elif mode == "line":
            if c == "\n":
                mode = "code"
            else:
                chars[i] = "\0"
            i += 1
        elif mode == "block":
            if c == "*" and i + 1 < n and text[i + 1] == "/":
                chars[i] = "\0"
                chars[i + 1] = "\0"
                i += 2
                mode = "code"
            else:
                chars[i] = "\0"
                i += 1
    return "".join(chars)


def find_strings(text):
    """状态机找出真实字符串字面量内容区间（跳过注释），返回 (内容开始, 内容结束)。"""
    masked = mask_comments(text)
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = masked[i]
        if c == "`":
            j = i + 1
            while j < n:
                if masked[j] == "\\":
                    j += 2
                    continue
                if masked[j] == "`":
                    break
                j += 1
            i = j + 1 if j < n else n
        elif c == "/" and i + 1 < n and masked[i + 1] not in ("/", "*") and _is_regex_like(masked, i):
            j = i + 1
            in_class = False
            while j < n:
                ch = masked[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    break
                j += 1
            i = j + 1 if j < n else n
        elif c in ('"', "'"):
            q = c
            j = i + 1
            while j < n:
                if masked[j] == "\\":
                    j += 2
                    continue
                if masked[j] == q:
                    break
                j += 1
            if j < n:
                out.append((i + 1, j))
                i = j + 1
            else:
                i += 1
        else:
            i += 1
    return out


def _is_regex_like(masked, i):
    """粗略判断当前位置的 / 是正则而非除法。"""
    prev = masked[i - 1] if i > 0 else "\n"
    if prev.isalnum() or prev in (")", "]", "_", "$"):
        return False
    j = i + 1
    n = len(masked)
    content = []
    while j < n:
        ch = masked[j]
        if ch == "\\":
            content.append(ch)
            if j + 1 < n:
                content.append(masked[j + 1])
            j += 2
            continue
        if ch == "/":
            return bool(re.search(r"[\\\[\]()^$*+?.|{}]", "".join(content)))
        if ch == "\n":
            return False
        content.append(ch)
        j += 1
    return False


def mask_comments_and_strings(text):
    """把注释和字符串内容替换为相同长度占位符，保持偏移不变。"""
    chars = list(text)
    for start, end in find_strings(text):
        for k in range(max(0, start - 1), min(len(chars), end + 1)):
            chars[k] = "#"
    masked_comments = mask_comments(text)
    for i, c in enumerate(masked_comments):
        if c == "\0":
            chars[i] = "#"
    return "".join(chars)


def decode_escapes(s):
    """按 JS 规则解码常见转义，保留非 ASCII 字符。"""
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt in ("'", '"', "\\"):
                out.append(nxt)
                i += 2
            elif nxt == "n":
                out.append("\n")
                i += 2
            elif nxt == "r":
                out.append("\r")
                i += 2
            elif nxt == "t":
                out.append("\t")
                i += 2
            elif nxt == "u" and i + 5 < n:
                try:
                    out.append(chr(int(s[i + 2 : i + 6], 16)))
                    i += 6
                except ValueError:
                    out.append(c)
                    i += 1
            elif nxt == "x" and i + 3 < n:
                try:
                    out.append(chr(int(s[i + 2 : i + 4], 16)))
                    i += 4
                except ValueError:
                    out.append(c)
                    i += 1
            else:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    s = "".join(out)
    return (
        s.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u00a0", " ")
    )


def replace_spans(text, spans):
    """按 (start, end, replacement) 一次性重建文本。"""
    out = []
    pos = 0
    for start, end, repl in sorted(spans):
        if start < pos:
            continue
        out.append(text[pos:start])
        out.append(repl)
        pos = end
    out.append(text[pos:])
    return "".join(out)


def apply_file(path, dict_map, text_map, dry_run=False):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    replaced = 0
    spans = []

    for start, end in find_strings(text):
        content = text[start:end]
        key = decode_escapes(content).strip()
        if key in dict_map:
            spans.append((start, end, dict_map[key]))
            replaced += 1

    # JSX 文本节点单独处理，同样用一次性重建；屏蔽引号内内容避免误伤
    patched = replace_spans(text, spans)
    masked2 = mask_comments_and_strings(patched)
    spans2 = []
    for m in JSX_RE.finditer(masked2):
        content = m.group(1)
        key = content.strip().replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
        if key in text_map:
            spans2.append((m.start(1), m.end(1), text_map[key]))
    if spans2:
        patched = replace_spans(patched, spans2)

    if replaced == 0 and not spans2:
        return 0

    if dry_run:
        print(f"[dry-run] {path}: {replaced} 处字符串, {len(spans2)} 处 JSX")
    else:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(patched)
        print(f"[ok] {path}: {replaced} 处字符串, {len(spans2)} 处 JSX")
    return replaced + len(spans2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    total = 0
    for raw in args.paths:
        p = Path(raw)
        files = [p] if p.is_file() else sorted(
            x for x in p.rglob("*")
            if x.suffix in (".jsx", ".tsx", ".js", ".ts")
            and "test" not in x.name.lower()
            and ".spec." not in x.name.lower()
            and ".stories." not in x.name.lower()
            and "storybook" not in x.parts
            and not x.name.endswith(".d.ts")
            and "__tests__" not in x.parts
        )
        for f in files:
            total += apply_file(f, DICT, TEXT_DICT, dry_run=args.dry_run)
    print(f"TOTAL {total}")


if __name__ == "__main__":
    main()

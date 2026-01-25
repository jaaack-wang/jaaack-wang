#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


# 正文引用：支持 [[12\]](...) 或 [[12]](...)
BODY_CITE_RE = re.compile(
    r"""\[\[(?P<ix>\d+)(?:\\)?\]\]\(
        https?://(?:www\.)?zhihu\.com/[^)\s]*?
        \#ref_(?P=ix)(?:_\d+)?      # #ref_{ix} or #ref_{ix}_0
        [^)\s]*                      # anything else but stop before ')'
    \)""",
    re.VERBOSE,
)

# 关键修复：URL 匹配必须在 ')' 之前结束
# 也就是：匹配到 #ref_{ix} 后，继续吃“非 ) 和非空白”的字符
ANY_REF_URL_RE = re.compile(
    r"""https?://(?:www\.)?zhihu\.com/[^)\s]*?\#ref_(?P<ix>\d+)[^)\s]*""",
    re.VERBOSE,
)

CITE_HTML = r'<a id="cite{ix}" href="#ref{ix}">[{ix}]</a>'
REF_LINE  = r'<a id="ref{ix}">[{ix}] {detail}</a> [↩](#cite{ix})'


def last_ref_line_with_detail(lines: List[str], ix: str) -> Optional[Tuple[int, str]]:
    """
    找到“最后一次出现 #ref_{ix} 的那一行”，并取 URL 之后的尾部文本作为 detail。
    URL 后通常紧跟 ')'（markdown 链接闭合），这里会把开头的 ')' 和空白去掉。
    """
    last_li = None
    last_end = None

    for li, line in enumerate(lines):
        for m in ANY_REF_URL_RE.finditer(line):
            if m.group("ix") == ix:
                last_li = li
                last_end = m.end()

    if last_li is None or last_end is None:
        return None

    tail = lines[last_li][last_end:]
    # 去掉 markdown 里链接闭合的 ')' 以及随后的空白
    tail = re.sub(r"^\)\s*", "", tail).strip()

    if not tail:
        return None
    return last_li, tail


def transform_text(text: str) -> Tuple[str, Dict[str, str]]:
    lines = text.splitlines(keepends=False)

    # 1) 统计正文里每个 ix 出现次数
    body_counts: Dict[str, int] = {}
    for line in lines:
        for m in BODY_CITE_RE.finditer(line):
            ix = m.group("ix")
            body_counts[ix] = body_counts.get(ix, 0) + 1

    # 2) 统计全文里（包括参考文献）每个 ix 的 #ref 出现次数
    total_counts: Dict[str, int] = dict(body_counts)
    for line in lines:
        for m in ANY_REF_URL_RE.finditer(line):
            ix = m.group("ix")
            total_counts[ix] = total_counts.get(ix, 0) + 1

    # 3) eligible：总出现 >=2 且最后一次出现的 #ref_{ix} 所在行必须带注释细节
    report: Dict[str, str] = {}
    eligible: Dict[str, Tuple[int, str]] = {}  # ix -> (ref_line_index, detail)

    for ix, total in total_counts.items():
        if total < 2:
            report[ix] = f"skip: total occurrences only {total}"
            continue

        last_info = last_ref_line_with_detail(lines, ix)
        if not last_info:
            report[ix] = "skip: last #ref_{ix} line has no trailing note detail"
            continue

        ref_li, detail = last_info
        eligible[ix] = (ref_li, detail)
        report[ix] = f"ok: total {total} (body {body_counts.get(ix,0)}); ref line {ref_li+1}"

    if not eligible:
        return text, report

    # 4) 替换正文引用 -> cite anchor
    def body_repl(m: re.Match) -> str:
        ix = m.group("ix")
        if ix in eligible:
            return CITE_HTML.format(ix=ix)
        return m.group(0)

    lines = [BODY_CITE_RE.sub(body_repl, line) for line in lines]

    # 5) 替换参考文献“最后一次出现 #ref_{ix} 的那一整行”
    for ix, (li, detail) in eligible.items():
        lines[li] = REF_LINE.format(ix=ix, detail=detail)

    return "\n\n".join(lines), report


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python zhihu_refs_to_anchors.py <input.md> [output.md]", file=sys.stderr)
        sys.exit(2)

    in_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else in_path  # 默认覆盖输入文件

    text = in_path.read_text(encoding="utf-8")
    new_text, report = transform_text(text)

    # 原子写入：先写临时文件，再替换目标文件
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(new_text, encoding="utf-8")
    tmp_path.replace(out_path)

    print(f"Wrote: {out_path}")
    for ix in sorted(report, key=lambda x: int(x)):
        print(f"[{ix}] {report[ix]}")


if __name__ == "__main__":
    main()

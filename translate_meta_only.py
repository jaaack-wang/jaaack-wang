#!/usr/bin/env python3
"""
Translate ONLY front-matter title and tags for *_translated.md posts.

Key behavior:
- DOES NOT touch body
- DOES NOT overwrite the file content beyond front matter edits
- Uses sibling (same pair_id, opposite lang) as the source for title/tags
- Uses GPT ONLY for translating title/tags, never other fields
- PRESERVES TAG FORMAT in the translated post:
    - inline tags: [a, b] stays inline
    - block tags list stays block
- Skips if title/tags already look like the target language unless --force

Usage:
  python3 translate_meta_only.py --posts-dir _posts --dry-run
  python3 translate_meta_only.py --posts-dir _posts
  python3 translate_meta_only.py --posts-dir _posts --force
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from openai import OpenAI


FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")


# ---------- front matter helpers ----------

def parse_front_matter(text: str) -> Tuple[Optional[str], str]:
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return None, text
    return m.group(1), text[m.end():]

def strip_yaml_scalar(v: str) -> str:
    v = v.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    return v

def yaml_extract_lang(raw_yaml: Optional[str]) -> Optional[str]:
    if not raw_yaml:
        return None
    m = re.search(r"(?m)^lang:\s*(.+?)\s*$", raw_yaml)
    if not m:
        return None
    v = strip_yaml_scalar(m.group(1))
    return v if v in ("zh", "en") else None

def yaml_extract_pair_id(raw_yaml: Optional[str]) -> Optional[str]:
    if not raw_yaml:
        return None
    m = re.search(r"(?m)^pair_id:\s*(.+?)\s*$", raw_yaml)
    if not m:
        return None
    v = strip_yaml_scalar(m.group(1))
    return v or None

def yaml_extract_title(raw_yaml: Optional[str]) -> Optional[str]:
    if not raw_yaml:
        return None
    m = re.search(r"(?m)^title:\s*(.+?)\s*$", raw_yaml)
    if not m:
        return None
    return strip_yaml_scalar(m.group(1))

def yaml_extract_tags(raw_yaml: Optional[str]) -> List[str]:
    """
    Extract tags from either:
    - tags: [a, b]
    - tags:
        - a
        - b
    """
    if not raw_yaml:
        return []

    m = re.search(r"(?m)^tags:\s*\[(.*?)\]\s*$", raw_yaml)
    if m:
        inside = m.group(1).strip()
        if not inside:
            return []
        parts = [p.strip().strip('"').strip("'") for p in inside.split(",")]
        return [p for p in parts if p]

    m = re.search(r"(?ms)^tags:\s*\n((?:\s*-\s*.*\n)+)", raw_yaml)
    if m:
        block = m.group(1)
        items = []
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("-"):
                items.append(strip_yaml_scalar(line[1:].strip()))
        return [t for t in items if t]

    return []

def detect_existing_tags_style(raw_yaml: Optional[str]) -> str:
    """
    Returns:
      - "inline" if tags: [ ... ] exists
      - "block" if tags:\n  - ... exists
      - "missing" if no tags key present
    """
    if not raw_yaml:
        return "missing"
    if re.search(r"(?m)^tags:\s*\[.*\]\s*$", raw_yaml):
        return "inline"
    if re.search(r"(?m)^tags:\s*$", raw_yaml) and re.search(r"(?m)^\s*-\s+", raw_yaml):
        # a bit permissive; good enough for typical front matter
        return "block"
    if re.search(r"(?m)^tags:\s*$", raw_yaml):
        return "block"
    return "missing"

def yaml_quote_if_needed(s: str) -> str:
    if s == "":
        return '""'
    # Safer to JSON-quote if non-ascii or problematic YAML chars
    if any(ord(ch) > 127 for ch in s):
        return json.dumps(s, ensure_ascii=False)
    if re.search(r'[:#\n\r\t]', s) or s.strip() != s:
        return json.dumps(s, ensure_ascii=False)
    if s[0] in ("-", "?", "!", "@", "&", "*", "%"):
        return json.dumps(s, ensure_ascii=False)
    return s

def render_tags(new_tags: List[str], style: str) -> List[str]:
    """
    Render tags in the requested style.
    """
    if style == "inline":
        # tags: [a, b]
        inside = ", ".join([strip_yaml_scalar(yaml_quote_if_needed(t)) if False else t for t in []])  # placeholder
        # we want controlled quoting per tag:
        items = [yaml_quote_if_needed(t) for t in new_tags]
        return [f"tags: [{', '.join(items)}]"]
    # block default
    lines = ["tags:"]
    for t in new_tags:
        lines.append(f"  - {yaml_quote_if_needed(t)}")
    return lines

def yaml_replace_title_and_tags_preserve_tags_format(
    raw_yaml: Optional[str],
    new_title: str,
    new_tags: List[str],
    insert_tags_if_missing: bool = True,
) -> str:
    """
    Replace/insert title and tags while preserving the existing tag format in THIS FILE.
    - title is replaced if present, otherwise inserted
    - tags are replaced if present
    - if tags missing:
        - insert only if insert_tags_if_missing=True
        - otherwise leave missing
    """
    if raw_yaml is None:
        raw_yaml = ""

    tag_style = detect_existing_tags_style(raw_yaml)

    lines = raw_yaml.splitlines()

    out_lines: List[str] = []
    i = 0
    removed_tags = False
    removed_title = False

    while i < len(lines):
        line = lines[i]

        # remove existing title:
        if re.match(r"^title:\s*", line):
            removed_title = True
            i += 1
            continue

        # remove existing tags inline:
        if re.match(r"^tags:\s*\[.*\]\s*$", line):
            removed_tags = True
            i += 1
            continue

        # remove existing tags block:
        if re.match(r"^tags:\s*$", line):
            removed_tags = True
            i += 1
            while i < len(lines) and re.match(r"^\s*-\s*", lines[i]):
                i += 1
            continue

        out_lines.append(line)
        i += 1

    # Append title (always)
    out_lines.append(f"title: {yaml_quote_if_needed(new_title)}")

    # Append tags only if they existed OR user wants insertion
    if removed_tags or (insert_tags_if_missing and tag_style == "missing"):
        style = tag_style if tag_style in ("inline", "block") else "block"
        out_lines.extend(render_tags(new_tags, style))

    return "\n".join(out_lines).strip("\n")


# ---------- pairing/index ----------

@dataclass
class PostInfo:
    path: Path
    raw_yaml: Optional[str]
    body: str
    lang: Optional[str]
    pair_id: Optional[str]
    title: Optional[str]
    tags: List[str]

def load_post_info(path: Path) -> PostInfo:
    text = path.read_text(encoding="utf-8")
    raw_yaml, body = parse_front_matter(text)
    return PostInfo(
        path=path,
        raw_yaml=raw_yaml,
        body=body,
        lang=yaml_extract_lang(raw_yaml),
        pair_id=yaml_extract_pair_id(raw_yaml),
        title=yaml_extract_title(raw_yaml),
        tags=yaml_extract_tags(raw_yaml),
    )

def is_translated_filename(path: Path) -> bool:
    return path.stem.endswith("_translated")

def target_lang_looks_done(lang: str, title: str, tags: List[str]) -> bool:
    combined = (title or "") + " " + " ".join(tags or [])
    has_cjk = bool(CJK_RE.search(combined))
    if lang == "en":
        return (not has_cjk) and len((title or "").strip()) > 0
    if lang == "zh":
        return has_cjk
    return False


# ---------- OpenAI translate calls (metadata only) ----------

def call_openai_text(client: OpenAI, model: str, system: str, user: str, max_retries: int = 5) -> str:
    backoff = 1.5
    for attempt in range(max_retries):
        try:
            resp = client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.output_text
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(backoff)
            backoff *= 2.0

def translate_title(client: OpenAI, model: str, text: str, source_lang: str, target_lang: str) -> str:
    system = (
        "You are a meticulous bilingual translator. "
        "Translate a blog post TITLE faithfully and naturally. "
        "Preserve meaning and tone; do not add commentary."
    )
    user = f"Translate this title from {source_lang} to {target_lang}. Output ONLY the translated title:\n\n{text}"
    return call_openai_text(client, model, system, user).strip().strip('"')

def translate_tags(client: OpenAI, model: str, tags: List[str], source_lang: str, target_lang: str) -> List[str]:
    system = (
        "You are a meticulous bilingual translator. "
        "Translate blog TAGS faithfully. "
        "Output must be valid JSON: an array of strings, same number of tags, same order. "
        "No extra text."
    )
    user = (
        f"Translate these tags from {source_lang} to {target_lang}.\n"
        f"Return ONLY JSON array of strings.\n\n"
        f"{json.dumps(tags, ensure_ascii=False)}"
    )
    out = call_openai_text(client, model, system, user).strip()

    try:
        arr = json.loads(out)
        if isinstance(arr, list) and all(isinstance(x, str) for x in arr):
            return [x.strip() for x in arr]
    except Exception:
        pass

    m = re.search(r"(\[.*\])", out, re.DOTALL)
    if m:
        arr = json.loads(m.group(1))
        if isinstance(arr, list) and all(isinstance(x, str) for x in arr):
            return [x.strip() for x in arr]

    raise ValueError(f"Could not parse JSON array for tags. Model output:\n{out}")


# ---------- main workflow ----------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts-dir", default="_posts", help="Path to _posts directory.")
    ap.add_argument("--model", default="gpt-4.1", help="Model to use for metadata translation.")
    ap.add_argument("--dry-run", action="store_true", help="Do not write files; print planned edits.")
    ap.add_argument("--force", action="store_true", help="Translate title/tags even if they look already done.")
    ap.add_argument(
        "--no-insert-tags-if-missing",
        action="store_true",
        help="If a translated post has no tags field, do not insert it.",
    )
    args = ap.parse_args()

    posts_dir = Path(args.posts_dir)
    if not posts_dir.exists():
        raise SystemExit(f"Not found: {posts_dir}")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY environment variable.")
    client = OpenAI(api_key=api_key)

    # Index posts by pair_id
    all_posts: List[PostInfo] = []
    by_pair: Dict[str, List[PostInfo]] = {}

    for p in posts_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".md", ".markdown"):
            continue
        info = load_post_info(p)
        all_posts.append(info)
        if info.pair_id:
            by_pair.setdefault(info.pair_id, []).append(info)

    translated_posts = [pi for pi in all_posts if is_translated_filename(pi.path)]
    if not translated_posts:
        print("No *_translated.md files found. Nothing to do.")
        return

    changed = 0
    skipped = 0
    errors = 0

    for t in translated_posts:
        if not t.raw_yaml:
            print(f"SKIP {t.path}: no front matter")
            skipped += 1
            continue
        if t.lang not in ("zh", "en"):
            print(f"SKIP {t.path}: missing/invalid lang")
            skipped += 1
            continue
        if not t.pair_id:
            print(f"SKIP {t.path}: missing pair_id (cannot find sibling reliably)")
            skipped += 1
            continue

        siblings = by_pair.get(t.pair_id, [])
        sib = next(
            (s for s in siblings if s.path != t.path and s.lang in ("zh", "en") and s.lang != t.lang),
            None
        )

        if not sib:
            print(f"SKIP {t.path.name}: no sibling with same pair_id and opposite lang")
            skipped += 1
            continue
        if not sib.title:
            print(f"SKIP {t.path.name}: sibling has no title")
            skipped += 1
            continue

        if target_lang_looks_done(t.lang, t.title or "", t.tags) and not args.force:
            print(f"SKIP {t.path.name}: title/tags already look like {t.lang}")
            skipped += 1
            continue

        try:
            new_title = translate_title(client, args.model, sib.title, sib.lang, t.lang)
            source_tags = sib.tags or []
            new_tags = translate_tags(client, args.model, source_tags, sib.lang, t.lang) if source_tags else []

            insert_tags = not args.no_insert_tags_if_missing
            new_yaml = yaml_replace_title_and_tags_preserve_tags_format(
                t.raw_yaml, new_title, new_tags, insert_tags_if_missing=insert_tags
            )

            original_text = t.path.read_text(encoding="utf-8")
            _, body = parse_front_matter(original_text)
            new_text = f"---\n{new_yaml}\n---\n{body.lstrip()}"

            if args.dry_run:
                print(f"DRY  {t.path.name}: would update title/tags (preserve tags format)")
            else:
                t.path.write_text(new_text, encoding="utf-8")
                print(f"OK   {t.path.name}: updated title/tags (preserve tags format)")

            changed += 1

        except Exception as e:
            print(f"ERR  {t.path.name}: {e}")
            errors += 1

    print("\nDone.")
    print(f"Changed: {changed}")
    print(f"Skipped: {skipped}")
    print(f"Errors : {errors}")


if __name__ == "__main__":
    main()

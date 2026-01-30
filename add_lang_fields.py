#!/usr/bin/env python3
"""
Add lang / is_translation / pair_id to all Jekyll posts in _posts/.

Defaults:
- is_translation: true if filename includes "_translated" (before .md), else false
- pair_id: derived from filename slug with "_translated" removed
- lang: auto-detected (zh if CJK chars appear in title/body, else en)

Does NOT overwrite existing values unless --force is used.

Usage:
  python3 add_lang_fields.py --posts-dir _posts --dry-run
  python3 add_lang_fields.py --posts-dir _posts
  python3 add_lang_fields.py --posts-dir _posts --force
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Dict, Tuple, Optional

FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\uac00-\ud7af]")  # Han + Kana + Hangul

def parse_front_matter(text: str) -> Tuple[Optional[str], Dict[str, str], str]:
    """
    Returns (raw_yaml, kv_dict, rest_of_file).
    kv_dict is a *simple* YAML key:value parser sufficient for typical Jekyll front matter.
    """
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return None, {}, text

    raw_yaml = m.group(1)
    rest = text[m.end():]

    kv: Dict[str, str] = {}
    for line in raw_yaml.splitlines():
        # Keep simple "key: value" lines. Ignore lists/objects; we won't rewrite them.
        # If line is like `title: "..."` or `tags: [a, b]` it will be preserved in raw_yaml.
        if ":" not in line:
            continue
        # Ignore indentation (nested YAML); preserve as raw only.
        if line.startswith((" ", "\t")):
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if key:
            kv[key] = val
    return raw_yaml, kv, rest

def has_front_matter(text: str) -> bool:
    return FRONT_MATTER_RE.match(text) is not None

def compute_is_translation(filename: str) -> bool:
    return "_translated" in filename

def compute_pair_id(filename: str) -> str:
    # Expect Jekyll post filename: YYYY-MM-DD-something.md
    # Remove extension, remove trailing _translated, then remove leading date.
    stem = Path(filename).stem  # without .md
    stem = re.sub(r"_translated$", "", stem)
    stem = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem)
    # As a safety, collapse whitespace and ensure non-empty.
    stem = stem.strip()
    return stem or "untitled"

def detect_lang(raw_yaml: Optional[str], body: str) -> str:
    # Prefer checking title in front matter if present
    sample = ""
    if raw_yaml:
        # crude extraction of title line for language detection
        m = re.search(r"(?m)^title:\s*(.+)\s*$", raw_yaml)
        if m:
            sample += m.group(1) + "\n"
    sample += body[:4000]  # enough for detection, avoid huge reads
    return "zh" if CJK_RE.search(sample) else "en"

def insert_or_replace_fields(
    raw_yaml: Optional[str],
    kv: Dict[str, str],
    fields: Dict[str, str],
    force: bool
) -> str:
    """
    Return new raw_yaml with fields inserted.
    We preserve original raw_yaml content and append missing fields at end,
    unless force=True, in which case we remove existing simple key lines and append fresh values.
    """
    if raw_yaml is None:
        raw_yaml = ""

    lines = raw_yaml.splitlines()

    if force:
        # Remove any top-level lines matching the keys we manage (lang, is_translation, pair_id)
        managed = set(fields.keys())
        new_lines = []
        for line in lines:
            if ":" in line and not line.startswith((" ", "\t")):
                k = line.split(":", 1)[0].strip()
                if k in managed:
                    continue
            new_lines.append(line)
        lines = new_lines
        kv = {k: v for k, v in kv.items() if k not in managed}

    # Append fields that are missing
    for k, v in fields.items():
        if (k in kv) and not force:
            continue
        lines.append(f"{k}: {v}")

    # Ensure no leading/trailing blank weirdness
    out = "\n".join([ln for ln in lines if ln is not None])
    out = out.strip("\n")
    return out

def process_file(path: Path, force: bool, dry_run: bool) -> Tuple[bool, str]:
    original = path.read_text(encoding="utf-8")

    raw_yaml, kv, rest = parse_front_matter(original)

    is_tr = compute_is_translation(path.name)
    pair_id = compute_pair_id(path.name)
    lang = detect_lang(raw_yaml, rest)

    fields = {
        "lang": lang,
        "is_translation": "true" if is_tr else "false",
        "pair_id": pair_id,
    }

    new_yaml = insert_or_replace_fields(raw_yaml, kv, fields, force=force)

    if has_front_matter(original):
        new_text = re.sub(FRONT_MATTER_RE, f"---\n{new_yaml}\n---\n", original, count=1)
    else:
        # If no front matter exists, create it
        new_text = f"---\n{new_yaml}\n---\n\n{original.lstrip()}"

    changed = (new_text != original)

    if changed and not dry_run:
        path.write_text(new_text, encoding="utf-8")

    return changed, f"{path}: {'CHANGED' if changed else 'ok'} (lang={lang}, is_translation={is_tr}, pair_id={pair_id})"

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts-dir", default="_posts", help="Path to your Jekyll _posts directory.")
    ap.add_argument("--force", action="store_true", help="Overwrite existing lang/is_translation/pair_id values.")
    ap.add_argument("--dry-run", action="store_true", help="Show what would change without editing files.")
    args = ap.parse_args()

    posts_dir = Path(args.posts_dir)
    if not posts_dir.exists() or not posts_dir.is_dir():
        raise SystemExit(f"Not found or not a directory: {posts_dir}")

    md_files = sorted([p for p in posts_dir.rglob("*") if p.is_file() and p.suffix.lower() in (".md", ".markdown")])

    if not md_files:
        print(f"No markdown files found under {posts_dir}")
        return

    changed_count = 0
    for p in md_files:
        try:
            changed, msg = process_file(p, force=args.force, dry_run=args.dry_run)
            print(msg)
            if changed:
                changed_count += 1
        except UnicodeDecodeError:
            print(f"{p}: skipped (not utf-8?)")
        except Exception as e:
            print(f"{p}: ERROR: {e}")

    print(f"\nDone. Files changed: {changed_count} / {len(md_files)}")
    if args.dry_run:
        print("Dry run only; no files were modified.")

if __name__ == "__main__":
    main()

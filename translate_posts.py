#!/usr/bin/env python3
"""
Translate Jekyll posts in _posts/ and write *_translated.md files.

- Front matter is NOT translated by GPT; it is edited deterministically.
- Body is translated chunk-by-chunk to avoid omission.
- Fenced code blocks (``` ... ```) are preserved verbatim.

Requirements:
  pip install openai
  export OPENAI_API_KEY=...

Usage:
  python3 translate_posts.py --posts-dir _posts --dry-run
  python3 translate_posts.py --posts-dir _posts
  python3 translate_posts.py --posts-dir _posts --model gpt-4.1
"""

from __future__ import annotations

import argparse
import os
import re
import time
from tqdm import tqdm
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from openai import OpenAI  # official SDK (Responses API)


# --- Front matter parsing (simple + robust for common Jekyll cases) ---

FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

def parse_front_matter(text: str) -> Tuple[Optional[str], str]:
    """
    Returns (raw_yaml, body). raw_yaml excludes the --- lines.
    If no front matter found, raw_yaml is None and body is the whole text.
    """
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return None, text
    raw_yaml = m.group(1)
    body = text[m.end():]
    return raw_yaml, body

def yaml_get_top_level_kv(raw_yaml: str) -> Dict[str, str]:
    """
    Very small YAML key:value parser for top-level scalar/list-on-one-line.
    Good enough for reading lang/is_translation/pair_id/title, etc.
    Does not attempt full YAML.
    """
    kv: Dict[str, str] = {}
    for line in raw_yaml.splitlines():
        if ":" not in line:
            continue
        if line.startswith((" ", "\t")):
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        if k:
            kv[k] = v
    return kv

def yaml_upsert(raw_yaml: Optional[str], updates: Dict[str, str]) -> str:
    """
    Upsert top-level keys. If raw_yaml is None, create new YAML.
    This removes any existing lines for the keys in updates, then appends new values.
    Preserves everything else verbatim.
    """
    if raw_yaml is None:
        raw_yaml = ""

    lines = raw_yaml.splitlines()
    keys = set(updates.keys())

    kept: List[str] = []
    for line in lines:
        if ":" in line and not line.startswith((" ", "\t")):
            k = line.split(":", 1)[0].strip()
            if k in keys:
                continue
        kept.append(line)

    # Append updates at end
    for k, v in updates.items():
        kept.append(f"{k}: {v}")

    out = "\n".join(kept).strip("\n")
    return out


# --- Translation splitting: preserve fenced code blocks verbatim ---

FENCE_RE = re.compile(r"(^```.*?$.*?^```[ \t]*$)", re.DOTALL | re.MULTILINE)

@dataclass
class Segment:
    kind: str   # "code" or "text"
    content: str

def split_preserve_code_fences(md: str) -> List[Segment]:
    """
    Splits markdown into alternating text/code segments.
    Code fences (```...```) are returned as kind="code" and should not be translated.
    """
    segments: List[Segment] = []
    last = 0
    for m in FENCE_RE.finditer(md):
        if m.start() > last:
            segments.append(Segment("text", md[last:m.start()]))
        segments.append(Segment("code", m.group(1)))
        last = m.end()
    if last < len(md):
        segments.append(Segment("text", md[last:]))
    return segments

def chunk_text(text: str, max_chars: int) -> List[str]:
    """
    Chunk plain text by paragraph boundaries first, then hard-split if needed.
    """
    if not text.strip():
        return [text]

    parts = re.split(r"(\n\s*\n)", text)  # keep blank-line separators
    chunks: List[str] = []
    buf = ""

    def flush():
        nonlocal buf
        if buf:
            chunks.append(buf)
            buf = ""

    for p in parts:
        if len(buf) + len(p) <= max_chars:
            buf += p
        else:
            if buf:
                flush()
            # If a single part is still too large, hard split
            if len(p) > max_chars:
                for i in range(0, len(p), max_chars):
                    chunks.append(p[i:i+max_chars])
            else:
                buf = p

    flush()
    return chunks

def detect_lang_from_front_matter(raw_yaml: Optional[str], body: str) -> str:
    """
    Determine source language:
    - Use front matter `lang` if present
    - Else: heuristic: if CJK chars appear in title/body -> zh else en
    """
    if raw_yaml:
        kv = yaml_get_top_level_kv(raw_yaml)
        if "lang" in kv:
            # kv values might be quoted; normalize
            v = kv["lang"].strip().strip('"').strip("'")
            if v in ("zh", "en"):
                return v

    cjk = re.search(r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\uac00-\ud7af]", (raw_yaml or "") + "\n" + body[:4000])
    return "zh" if cjk else "en"

def compute_pair_id_from_filename(filename: str) -> str:
    stem = Path(filename).stem  # no .md
    stem = re.sub(r"_translated$", "", stem)
    stem = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem)
    stem = stem.strip()
    return stem or "untitled"

def translated_path_for(src: Path) -> Path:
    if src.name.endswith("_translated.md") or src.name.endswith("_translated.markdown"):
        return src
    if src.suffix.lower() == ".markdown":
        return src.with_name(src.stem + "_translated.markdown")
    return src.with_name(src.stem + "_translated.md")


# --- OpenAI call ---

def translate_chunk(
    client: OpenAI,
    model: str,
    chunk: str,
    source_lang: str,
    target_lang: str,
    max_retries: int = 5,
) -> str:
    """
    Translate one chunk using Responses API; returns translated text only.
    """
    # Keep instructions short + strict: output translation only.
    system = (
        "You are a meticulous bilingual translator. "
        "Translate faithfully and completely. "
        "Preserve Markdown formatting, headings, lists, emphasis, links, punctuation style, and line breaks as much as possible. "
        "Do not add or remove content. Do not summarize. Do not omit anything."
    )

    user = (
        f"Translate the following Markdown text from {source_lang} to {target_lang}.\n"
        "Return ONLY the translated text (no commentary).\n\n"
        f"{chunk}"
    )

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
            # Responses API returns output text via output_text convenience
            out = resp.output_text
            return out
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(backoff)
            backoff *= 2.0


def translate_markdown_body(
    client: OpenAI,
    model: str,
    body: str,
    source_lang: str,
    target_lang: str,
    max_chars_per_chunk: int,
) -> str:
    """
    Translate markdown body while preserving fenced code blocks.
    """
    segments = split_preserve_code_fences(body)
    out_parts: List[str] = []

    for seg in segments:
        if seg.kind == "code":
            out_parts.append(seg.content)
            continue

        # translate text segments in chunks
        text_chunks = chunk_text(seg.content, max_chars=max_chars_per_chunk)
        translated_chunks: List[str] = []
        for ch in text_chunks:
            # Keep empty chunks as-is (avoid weird changes)
            if not ch.strip():
                translated_chunks.append(ch)
            else:
                translated_chunks.append(
                    translate_chunk(
                        client=client,
                        model=model,
                        chunk=ch,
                        source_lang=source_lang,
                        target_lang=target_lang,
                    )
                )
        out_parts.append("".join(translated_chunks))

    return "".join(out_parts)


# --- Main processing ---

def should_skip_file(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith("."):
        return True
    if path.suffix.lower() not in (".md", ".markdown"):
        return True
    return False

def process_post(
    client: OpenAI,
    src_path: Path,
    model: str,
    dry_run: bool,
    overwrite: bool,
    max_chars_per_chunk: int,
) -> Tuple[bool, str]:
    src_text = src_path.read_text(encoding="utf-8")
    raw_yaml, body = parse_front_matter(src_text)

    src_lang = detect_lang_from_front_matter(raw_yaml, body)
    tgt_lang = "en" if src_lang == "zh" else "zh"

    dst_path = translated_path_for(src_path)
    if dst_path.exists() and (not overwrite):
        return False, f"{src_path}: skip (translated exists: {dst_path.name})"

    # Determine pair_id
    pair_id = None
    if raw_yaml:
        kv = yaml_get_top_level_kv(raw_yaml)
        if "pair_id" in kv:
            pair_id = kv["pair_id"].strip().strip('"').strip("'")
    if not pair_id:
        pair_id = compute_pair_id_from_filename(src_path.name)

    # Translate body
    translated_body = translate_markdown_body(
        client=client,
        model=model,
        body=body,
        source_lang=src_lang,
        target_lang=tgt_lang,
        max_chars_per_chunk=max_chars_per_chunk,
    )

    # Build translated front matter: keep original front matter + deterministic updates
    updates = {
        "lang": tgt_lang,
        "is_translation": "true",
        "pair_id": pair_id,
    }
    new_yaml = yaml_upsert(raw_yaml, updates)

    out_text = f"---\n{new_yaml}\n---\n{translated_body.lstrip()}"
    changed = True

    if not dry_run:
        dst_path.write_text(out_text, encoding="utf-8")

    return changed, f"{src_path.name} -> {dst_path.name} (source={src_lang}, target={tgt_lang}, model={model})"

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--posts-dir", default="_posts", help="Path to _posts directory.")
    ap.add_argument("--model", default="gpt-5.2-2025-12-11", help="Model to use (e.g., gpt-4.1).")
    ap.add_argument("--dry-run", action="store_true", help="Do not write files; just print actions.")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing *_translated.md files.")
    ap.add_argument("--max-chars", type=int, default=12000, help="Max characters per translation chunk.")
    args = ap.parse_args()

    posts_dir = Path(args.posts_dir)
    if not posts_dir.exists() or not posts_dir.is_dir():
        raise SystemExit(f"Not found or not a directory: {posts_dir}")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY environment variable.")

    client = OpenAI(api_key=api_key)

    files = sorted([p for p in posts_dir.rglob("*") if p.is_file() and not should_skip_file(p)])
    if not files:
        print(f"No markdown files found under {posts_dir}")
        return

    changed = 0
    for p in tqdm(files):
        # don’t translate already-translated files again (unless user explicitly points to them)
        if p.stem.endswith("_translated"):
            continue
        try:
            did, msg = process_post(
                client=client,
                src_path=p,
                model=args.model,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
                max_chars_per_chunk=args.max_chars,
            )
            print(msg)
            if did:
                changed += 1
        except UnicodeDecodeError:
            print(f"{p}: skipped (not utf-8?)")
        except Exception as e:
            print(f"{p}: ERROR: {e}")

    print(f"\nDone. Translated files written: {changed} (dry-run={args.dry_run})")

if __name__ == "__main__":
    main()

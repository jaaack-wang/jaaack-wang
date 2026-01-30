#!/usr/bin/env python3
"""
Sanity-check translated Jekyll posts (language-aware).

Supports:
- Original language = zh or en
- Translation direction = zh→en or en→zh
- Recursive _posts/ scanning
- Console warnings
- CSV + JSON reports

Rule-based + heuristic-based only. Read-only.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Dict, Tuple, Optional, List

# ---------------- config ----------------

POSTS_DIR = "_posts"
CSV_OUT = "translation_sanity_report.csv"
JSON_OUT = "translation_sanity_report.json"

FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
CODE_FENCE_RE = re.compile(r"^```", re.MULTILINE)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# ---------------- parsing helpers ----------------

def parse_front_matter(text: str) -> Tuple[Optional[str], str]:
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return None, text
    return m.group(1), text[m.end():]

def yaml_kv(raw: Optional[str]) -> Dict[str, str]:
    if not raw:
        return {}
    out = {}
    for line in raw.splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out

# ---------------- language detection ----------------

def detect_lang(kv: Dict[str, str], body: str) -> str:
    """
    Prefer front matter lang if present, otherwise heuristic.
    """
    if kv.get("lang") in ("zh", "en"):
        return kv["lang"]
    return "zh" if CJK_RE.search(body) else "en"

# ---------------- metrics ----------------

def chinese_char_count(text: str) -> int:
    return len(CJK_RE.findall(text))

def english_word_count(text: str) -> int:
    return len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", text))

def paragraph_count(text: str) -> int:
    return len([p for p in re.split(r"\n\s*\n", text) if p.strip()])

def heading_count(text: str) -> int:
    return len(re.findall(r"^#{1,6}\s+", text, re.MULTILINE))

def list_item_count(text: str) -> int:
    return len(re.findall(r"^(\s*[-*+]|\s*\d+\.)\s+", text, re.MULTILINE))

def code_block_count(text: str) -> int:
    return len(CODE_FENCE_RE.findall(text)) // 2

# ---------------- pairing ----------------

def find_pairs(posts_dir: Path):
    originals: Dict[str, Path] = {}
    translations: Dict[str, Path] = {}

    for p in posts_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".md", ".markdown"):
            continue

        stem = p.stem
        if stem.endswith("_translated"):
            base = stem.replace("_translated", "")
            translations[base] = p
        else:
            originals[stem] = p

    for base, orig in originals.items():
        yield orig, translations.get(base)

# ---------------- checks ----------------

def check_pair(orig: Path, trans: Optional[Path]) -> Dict:
    row = {
        "original_file": orig.name,
        "translated_file": trans.name if trans else "",
        "pair_id": "",
        "orig_lang": "",
        "trans_lang": "",
        "lang_ok": False,
        "pair_id_ok": False,
        "is_translation_ok": False,
        "orig_length": 0,
        "trans_length": 0,
        "length_ratio": 0.0,
        "paragraphs_orig": 0,
        "paragraphs_trans": 0,
        "headings_orig": 0,
        "headings_trans": 0,
        "lists_orig": 0,
        "lists_trans": 0,
        "code_blocks_orig": 0,
        "code_blocks_trans": 0,
        "flags": [],
        "severity": "OK",
    }

    if not trans:
        row["flags"].append("missing translation")
        row["severity"] = "FAIL"
        return row

    o_text = orig.read_text(encoding="utf-8")
    t_text = trans.read_text(encoding="utf-8")

    o_yaml, o_body = parse_front_matter(o_text)
    t_yaml, t_body = parse_front_matter(t_text)

    o_kv = yaml_kv(o_yaml)
    t_kv = yaml_kv(t_yaml)

    row["pair_id"] = o_kv.get("pair_id", "")

    orig_lang = detect_lang(o_kv, o_body)
    trans_lang = detect_lang(t_kv, t_body)

    row["orig_lang"] = orig_lang
    row["trans_lang"] = trans_lang

    # --- front matter checks ---
    row["lang_ok"] = orig_lang != trans_lang
    row["pair_id_ok"] = (
        "pair_id" in o_kv and o_kv.get("pair_id") == t_kv.get("pair_id")
    )
    row["is_translation_ok"] = t_kv.get("is_translation") == "true"

    if not row["lang_ok"]:
        row["flags"].append("lang not flipped")
    if not row["pair_id_ok"]:
        row["flags"].append("pair_id mismatch")
    if not row["is_translation_ok"]:
        row["flags"].append("is_translation not true")

    # --- length heuristics (direction-aware) ---
    if orig_lang == "zh":
        o_len = chinese_char_count(o_body)
        t_len = english_word_count(t_body)
    else:
        o_len = english_word_count(o_body)
        t_len = chinese_char_count(t_body)

    row["orig_length"] = o_len
    row["trans_length"] = t_len
    row["length_ratio"] = round(t_len / o_len, 3) if o_len > 0 else 0.0

    # conservative truncation detection
    if o_len > 0 and row["length_ratio"] < 0.25:
        row["flags"].append("translation suspiciously short")

    # --- structure checks ---
    def chk(name, o_n, t_n, thresh):
        if o_n > 0 and (t_n / o_n) < thresh:
            row["flags"].append(f"{name} dropped ({o_n}->{t_n})")

    row["paragraphs_orig"] = paragraph_count(o_body)
    row["paragraphs_trans"] = paragraph_count(t_body)
    chk("paragraphs", row["paragraphs_orig"], row["paragraphs_trans"], 0.6)

    row["headings_orig"] = heading_count(o_body)
    row["headings_trans"] = heading_count(t_body)
    chk("headings", row["headings_orig"], row["headings_trans"], 0.7)

    row["lists_orig"] = list_item_count(o_body)
    row["lists_trans"] = list_item_count(t_body)
    chk("lists", row["lists_orig"], row["lists_trans"], 0.6)

    row["code_blocks_orig"] = code_block_count(o_body)
    row["code_blocks_trans"] = code_block_count(t_body)
    if row["code_blocks_orig"] != row["code_blocks_trans"]:
        row["flags"].append("code blocks mismatch")

    # --- severity ---
    if row["flags"]:
        row["severity"] = "WARN"
    if "missing translation" in row["flags"]:
        row["severity"] = "FAIL"

    row["flags"] = "; ".join(row["flags"])
    return row

# ---------------- main ----------------

def main():
    posts_dir = Path(POSTS_DIR)
    if not posts_dir.exists():
        print(f"Directory not found: {POSTS_DIR}")
        return

    rows: List[Dict] = []

    print("🔍 Sanity-checking translations (language-aware)...\n")

    for orig, trans in find_pairs(posts_dir):
        row = check_pair(orig, trans)
        rows.append(row)

        if row["severity"] != "OK":
            print(f"⚠ {row['original_file']}")
            for f in row["flags"].split("; "):
                print(f"  - {f}")
            print()

    if not rows:
        print("No posts found. Nothing to report.")
        return

    # CSV
    with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    # # JSON
    # with open(JSON_OUT, "w", encoding="utf-8") as f:
    #     json.dump(rows, f, indent=2, ensure_ascii=False)

    print("✅ Done.")
    print(f"CSV report : {CSV_OUT}")
    # print(f"JSON report: {JSON_OUT}")
    print(f"Checked {len(rows)} original posts.")

if __name__ == "__main__":
    main()

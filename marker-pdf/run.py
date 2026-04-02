#!/usr/bin/env python
"""
run.py - Local runner for PDF to Markdown conversion.

All book-specific configuration lives in templates/<template>/pdf_config.yaml.
The conversion logic is fully generic -- font ratios and weight patterns are
used instead of hardcoded font names or absolute sizes.

Usage:
  python run.py path/to/book.pdf                    # full conversion
  python run.py path/to/book.pdf --save-raw         # save Marker output before post-processing
  python run.py raw.md book.pdf --postprocess       # re-run post-processing only (fast)
  python run.py path/to/book.pdf --template homestead
  python run.py path/to/book.pdf --page-range 62-200
  python run.py path/to/book.pdf --dump-fonts       # calibration mode
"""
import os, sys, re, argparse, logging
from pathlib import Path

logging.basicConfig(level=logging.WARNING)
SCRIPT_DIR = Path(__file__).resolve().parent

def _load_yaml(path):
    import yaml
    with open(path, encoding="utf-8") as f: return yaml.safe_load(f)

def load_template(name):
    path = SCRIPT_DIR / "templates" / name / "pdf_config.yaml"
    if not path.exists(): print(f"ERROR: {path}"); sys.exit(1)
    cfg = _load_yaml(path)
    cfg["_citation_res"] = [re.compile(p) for p in cfg.get("citation_patterns", [])]
    return cfg

def size_bucket(s): return round(float(s) * 2) / 2

def font_weight(f):
    n = f.lower()
    if "bolditalic" in n or ("bold" in n and "italic" in n): return "bold-italic"
    if "bold" in n: return "bold"
    if "italic" in n: return "italic"
    return "regular"

def normalise_key(text):
    t = re.sub(r"\*+", "", text)
    t = t.replace("\u2018","'").replace("\u2019","'").replace("\u201c",'"').replace("\u201d",'"')
    t = t.replace("\u2013","-").replace("\u2014","-")
    return " ".join(t.split()).strip().lower()[:60]

def _match_rule(w, r, rule):
    return rule["weight"] == w and rule["min_ratio"] <= r <= rule["max_ratio"]

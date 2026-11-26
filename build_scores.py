#!/usr/bin/env python3
"""Build scores.enc.json for the GE5072 Score Check page.

Reads the pseudonymised extract (Code + scores, no names, no student IDs) that
ge5072_pseudonymise.py writes, and encrypts each student's row with a key
derived from that student's own code. The published file therefore holds no
readable scores: the page can open a row only when someone types its code.

    python3 build_scores.py           # rebuild scores.enc.json
    python3 build_scores.py --push    # rebuild, commit, push (Pages redeploys)

Regenerate the extract first if the master changed:
    cd ~/Library/CloudStorage/OneDrive-UniversityoftheThaiChamberofCommerce/Pseudonymisation
    /opt/homebrew/bin/python3.11 ge5072_pseudonymise.py --if-changed
"""
import argparse
import base64
import csv
import datetime as dt
import hashlib
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ONEDRIVE = Path.home() / "Library/CloudStorage/OneDrive-UniversityoftheThaiChamberofCommerce"
SRC = ONEDRIVE / "Pseudonymisation/shareable/GE5072_Scores_Analysis.csv"
MASTER = ONEDRIVE / "GE5072 (Aj.Mew) Scores.xlsx"
HERE = Path(__file__).resolve().parent
OUT = HERE / "scores.enc.json"

ITERATIONS = 150_000
ALPHABET = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")

# key in the page -> column in the extract (header text as the generator writes it)
COLUMNS = {
    "att": "Attendance (10%)",
    "eval": "Evaluation (2.5%)",
    "a1": "Assignment 1 (2.5%)",
    "a2": "Assignment 2 (2.5%)",
    "a3": "Assignment 3 (2.5%)",
    "fp": "Final Projects (10%)",
    "quiz": "Quiz (5%)",
    "busuu": "Busuu (10%)",
    "partA": "Bonus Points (Part A)",
    "partB": "Bonus Points (Part B: 75)",
}
# Final Projects (10%) = report /8 + presentation /2. Until the presentation marks are
# in the tracker, the column holds the report only: the page then shows Report x/8 and
# Presentation "รอบันทึก" /2. Set to False once the column holds the full /10.
FP_PRESENTATION_PENDING = True

# Part A catalogue as announced in Teams on 26 Nov 2026: 65 points in all.
EXERCISES = {f"Ex {i}": (15 if i == 3 else 5) for i in range(1, 12)}
PART_A_TOTAL = 65

# Demo row so the teacher can try the live page without a student's code.
DEMO_CODE = "S-TEST"
DEMO = {"g": "TEST", "demo": True,
        "att": 9.5, "eval": None, "a1": 2.5, "a2": 2.5, "a3": None, "fp": 7.5,
        "quiz": 4, "busuu": 10, "partA": 40, "partB": None,
        "ex": {"Ex 1": 5, "Ex 2": 5, "Ex 3": 15, "Ex 5": 5, "Ex 6": 5, "Ex 8": 5}}


def num(v):
    v = (v or "").strip()
    if not v:
        return None
    try:
        f = float(v)
    except ValueError:
        return v  # e.g. "Submitted" = handed in, not graded yet
    return int(f) if f.is_integer() else round(f, 2)


def derive(code, salt):
    bits = hashlib.pbkdf2_hmac("sha256", code.encode(), salt, ITERATIONS, dklen=48)
    return bits[:32], bits[32:].hex()  # AES key, lookup id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="commit and push after building")
    args = ap.parse_args()

    if not SRC.exists():
        sys.exit(f"Missing {SRC}")
    src_mtime = SRC.stat().st_mtime
    if MASTER.exists() and MASTER.stat().st_mtime > src_mtime + 120:
        print("WARNING: the master Scores.xlsx is newer than the extract. "
              "Run ge5072_pseudonymise.py first, or the page shows old scores.")

    with SRC.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    header = rows[0].keys() if rows else []
    missing = [c for c in list(COLUMNS.values()) + list(EXERCISES) if c not in header]
    if missing:
        sys.exit(f"Extract is missing column(s): {missing}")
    extra_ex = [c for c in header if c.startswith("Ex ") and c not in EXERCISES]
    if extra_ex:
        sys.exit(f"New exercise column(s) {extra_ex}: update EXERCISES / PART_A_TOTAL "
                 "(and the 26 Nov post, which says 65) before rebuilding.")

    records = {}
    for r in rows:
        code = r["Code"].strip().upper()
        if not (code.startswith("S-") and len(code) == 6 and set(code[2:]) <= ALPHABET):
            sys.exit(f"Unexpected code format: {code!r}")
        rec = {"g": r["Group_Reg"].strip()}
        for k, col in COLUMNS.items():
            rec[k] = num(r[col])
        rec["ex"] = {e: num(r[e]) for e in EXERCISES if num(r[e]) not in (None, 0)}
        records[code] = rec
    if DEMO_CODE in records:
        sys.exit("A real student holds S-TEST; pick another demo code.")
    over8 = [c for c, rec in records.items() if isinstance(rec["fp"], (int, float)) and rec["fp"] > 8]
    if FP_PRESENTATION_PENDING and over8:
        sys.exit(f"{len(over8)} Final Project mark(s) are above 8, so presentation points look entered. "
                 "Set FP_PRESENTATION_PENDING = False in build_scores.py, then rebuild.")

    # A column nobody has a non-zero mark in has not been entered yet (e.g. the
    # course evaluation, pasted at the end of semester): show it as pending, not 0.
    pending = [k for k in COLUMNS
               if not any(isinstance(rec[k], (int, float)) and rec[k] != 0 for rec in records.values())]
    records[DEMO_CODE] = DEMO

    # Every build uses a fresh salt, so the file always changes. Skip the rebuild
    # when the scores themselves are unchanged (hash kept locally, not published).
    digest = hashlib.sha256(json.dumps([records, pending, FP_PRESENTATION_PENDING], sort_keys=True).encode()).hexdigest()
    stamp = HERE / ".last_data_hash"
    if OUT.exists() and stamp.exists() and stamp.read_text().strip() == digest:
        print("Scores unchanged since the last build; nothing to do.")
        return

    salt = secrets.token_bytes(16)
    out = {}
    for code, rec in records.items():
        key, rid = derive(code, salt)
        iv = secrets.token_bytes(12)
        ct = AESGCM(key).encrypt(iv, json.dumps(rec, ensure_ascii=False, separators=(",", ":")).encode(), None)
        out[rid] = [base64.b64encode(iv).decode(), base64.b64encode(ct).decode()]

    updated = dt.datetime.fromtimestamp(src_mtime).strftime("%Y-%m-%dT%H:%M")
    doc = {"v": 1, "updated": updated, "iter": ITERATIONS,
           "salt": base64.b64encode(salt).decode(), "pending": pending, "fpSplit": FP_PRESENTATION_PENDING,
           "exercises": EXERCISES, "partATotal": PART_A_TOTAL,
           "records": dict(sorted(out.items()))}
    OUT.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    stamp.write_text(digest + "\n")
    print(f"{len(records) - 1} students (+ demo {DEMO_CODE}) -> {OUT.name}; "
          f"data as of {updated}; pending: {', '.join(pending) or 'none'}")

    if args.push:
        os.chdir(HERE)
        subprocess.run(["git", "add", "scores.enc.json"], check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            print("Nothing changed; not pushing.")
            return
        subprocess.run(["git", "commit", "-m", f"Update scores (data as of {updated})"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("Pushed. GitHub Pages redeploys in about a minute.")


if __name__ == "__main__":
    main()

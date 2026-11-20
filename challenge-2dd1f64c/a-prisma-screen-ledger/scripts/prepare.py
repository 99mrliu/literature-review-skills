#!/usr/bin/env python3
"""prisma-screen-ledger :: prepare.py

Defensive normalization of a case snapshot into a canonical record list plus
case metadata, and scaffolding of an honest PENDING result.json.

Usage:
  python3 prepare.py --case /input/case.json --task task.md \
      --work /app/work --out /app/output

Standard library only. Never fabricates metadata: missing fields stay null
and are listed in metadata_gaps.
"""
import argparse
import json
import os
import re
import sys

RECORD_KEYS = ["candidates", "records", "papers", "results", "documents",
               "items", "entries", "hits", "corpus", "snapshot"]
QUESTION_KEYS = ["research_question", "question", "query", "task",
                 "objective", "aim", "problem"]
CONTRACT_KEYS = ["output_contract", "contract", "output_fields",
                 "required_fields", "deliverable"]
ID_KEYS = ["id", "record_id", "paper_id", "doc_id", "uid", "key", "pmid",
           "doi"]
TITLE_KEYS = ["title", "name", "headline"]
ABSTRACT_KEYS = ["abstract", "summary", "description", "content", "text"]
AUTHOR_KEYS = ["authors", "author", "creators", "contributors"]
YEAR_KEYS = ["year", "publication_year", "pub_year", "date", "published",
             "publication_date"]
VENUE_KEYS = ["venue", "journal", "source", "publication", "container"]
DOI_KEYS = ["doi", "DOI"]
URL_KEYS = ["url", "link", "href", "pdf_url", "landing_page"]


def first_key(obj, keys):
    for k in keys:
        if isinstance(obj, dict) and k in obj and obj[k] not in (None, "", []):
            return obj[k]
    return None


def find_records(obj, path=""):
    """Locate the largest list-of-dicts that looks like candidate records."""
    best = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                titled = sum(1 for x in v if first_key(x, TITLE_KEYS))
                if titled >= max(1, len(v) // 2) and len(v) > len(best):
                    best = v
                deeper = find_records(v, path + "/" + k)
                if len(deeper) > len(best):
                    best = deeper
            else:
                deeper = find_records(v, path + "/" + k)
                if len(deeper) > len(best):
                    best = deeper
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            deeper = find_records(v, path + "/[%d]" % i)
            if len(deeper) > len(best):
                best = deeper
    return best


def norm_text(x):
    if x is None:
        return None
    if isinstance(x, list):
        x = "; ".join(str(i) for i in x)
    s = re.sub(r"\s+", " ", str(x)).strip()
    return s or None


def norm_year(x):
    if x is None:
        return None
    m = re.search(r"(19|20)\d{2}", str(x))
    return int(m.group(0)) if m else None


def norm_authors(x):
    if x is None:
        return []
    if isinstance(x, str):
        parts = re.split(r";|\band\b|,", x)
        return [p.strip() for p in parts if p.strip()]
    out = []
    for a in x:
        if isinstance(a, dict):
            nm = a.get("name") or a.get("full_name") or a.get("display_name")
            if nm:
                out.append(str(nm))
        elif a:
            out.append(str(a))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", required=True)
    ap.add_argument("--task", default=None)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    os.makedirs(args.work, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)

    with open(args.case, encoding="utf-8") as fh:
        case = json.load(fh)
    task_text = ""
    if args.task and os.path.exists(args.task):
        with open(args.task, encoding="utf-8") as fh:
            task_text = fh.read()

    case_id = case.get("case_id") or case.get("id") or case.get("name") or "UNKNOWN"
    question = first_key(case, QUESTION_KEYS)
    if question is None and task_text:
        question = task_text.strip().splitlines()[0][:300]
    contract = first_key(case, CONTRACT_KEYS) or []

    raw_records = find_records(case)
    records, gaps = [], []
    seen_ids = set()
    for i, r in enumerate(raw_records):
        rid = None
        for k in ID_KEYS:
            if isinstance(r, dict) and r.get(k):
                rid = "R" + re.sub(r"[^A-Za-z0-9]+", "", str(r[k]))[:24]
                break
        if not rid:
            rid = "R%03d" % (i + 1)
        base, n = rid, 2
        while rid in seen_ids:
            rid = "%s_%d" % (base, n)
            n += 1
        seen_ids.add(rid)
        rec = {
            "record_id": rid,
            "title": norm_text(first_key(r, TITLE_KEYS)),
            "abstract": norm_text(first_key(r, ABSTRACT_KEYS)),
            "authors": norm_authors(first_key(r, AUTHOR_KEYS)),
            "year": norm_year(first_key(r, YEAR_KEYS)),
            "venue": norm_text(first_key(r, VENUE_KEYS)),
            "doi": norm_text(first_key(r, DOI_KEYS)),
            "url": norm_text(first_key(r, URL_KEYS)),
            "raw_keys": sorted(r.keys()) if isinstance(r, dict) else [],
            "provenance_note": norm_text(r.get("_label") or r.get("label")
                                         or r.get("fixture") or
                                         r.get("provenance")) if isinstance(r, dict) else None,
        }
        missing = [f for f in ("title", "abstract", "year") if rec[f] in (None, [], "")]
        if missing:
            gaps.append({"record_id": rid, "missing": missing})
        records.append(rec)

    rec_path = os.path.join(args.work, "records.jsonl")
    with open(rec_path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    meta = {
        "case_id": case_id,
        "research_question": norm_text(question) or "",
        "contract_fields": contract if isinstance(contract, list) else [str(contract)],
        "record_count": len(records),
        "metadata_gaps": gaps,
        "sources": [{"file": os.path.basename(args.case), "role": "case input"}]
        + ([{"file": os.path.basename(args.task), "role": "task brief"}] if task_text else []),
    }
    with open(os.path.join(args.work, "case_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    scaffold = {
        "case_id": case_id,
        "status": "partial",
        "research_question": meta["research_question"] or "PENDING::question",
        "counts": {"total": len(records), "retained": "PENDING::count",
                   "pending": "PENDING::count", "excluded": "PENDING::count"},
        "ranked_results": "PENDING::screening not finished",
        "metadata_gaps": gaps,
        "conflicts": [],
        "uncertainty": "PENDING::screening not finished",
        "sources": meta["sources"],
        "change_log": [],
    }
    with open(os.path.join(args.out, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(scaffold, fh, ensure_ascii=False, indent=2)

    print(json.dumps({
        "case_id": case_id, "records": len(records),
        "metadata_gaps": len(gaps),
        "question_preview": (meta["research_question"] or "")[:120],
        "records_file": rec_path,
        "scaffold": os.path.join(args.out, "result.json"),
    }, ensure_ascii=False, indent=2))
    if not records:
        print("WARNING: no candidate records discovered; check case.json keys.",
              file=sys.stderr)


if __name__ == "__main__":
    main()

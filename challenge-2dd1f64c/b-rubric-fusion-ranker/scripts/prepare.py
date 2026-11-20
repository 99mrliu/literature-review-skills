#!/usr/bin/env python3
"""rubric-fusion-ranker :: prepare.py

Defensive normalization of a literature-screening case snapshot into a
canonical record list plus case metadata, and scaffolding of an honest
PENDING result.json. Also drops the default rubric (rubric.json) into the
work directory so the model can inspect it before scoring.

Usage:
  python3 prepare.py --case /input/case.json --task task.md \
      --work /app/work --out /app/output

Standard library only. Never fabricates metadata: missing fields stay null
and are listed in metadata_gaps. Fixture labels (e.g. "synthetic duplicate
export", "conflicting opinion") are preserved verbatim as provenance and
are never used downstream as ranking evidence.
"""
import argparse
import json
import os
import re
import sys

CANDIDATE_KEYS = ["candidates", "records", "papers", "results", "documents",
                  "items", "entries", "hits", "corpus", "snapshot", "works",
                  "publications", "references"]
QUESTION_KEYS = ["research_question", "question", "query", "task",
                 "objective", "aim", "problem", "topic"]
CONTRACT_KEYS = ["output_contract", "contract", "output_fields",
                 "required_fields", "deliverable", "deliverables"]
TITLE_KEYS = ["title", "name", "headline", "paper_title"]
ABSTRACT_KEYS = ["abstract", "summary", "description", "content", "text",
                 "abstract_text"]
AUTHOR_KEYS = ["authors", "author", "creators", "contributors", "author_list"]
YEAR_KEYS = ["year", "publication_year", "pub_year", "pubyear", "date",
             "published", "publication_date", "pub_date"]
VENUE_KEYS = ["venue", "journal", "source", "publication", "container",
              "journal_name", "conference"]
DOI_KEYS = ["doi", "DOI", "doi_url"]
URL_KEYS = ["url", "link", "href", "pdf_url", "landing_page", "oa_url"]
SOURCE_ID_KEYS = ["id", "record_id", "paper_id", "doc_id", "uid", "key",
                  "pmid", "doi"]
FIXTURE_KEYS = ["_label", "label", "fixture", "_fixture", "synthetic",
                "duplicate_of", "conflict", "conflict_note", "note", "flag",
                "tags", "provenance", "_note", "_tag"]


def pick(obj, keys):
    """First non-empty value among alias keys."""
    if not isinstance(obj, dict):
        return None
    for k in keys:
        v = obj.get(k)
        if v not in (None, "", []):
            return v
    return None


def looks_like_records(lst):
    return (isinstance(lst, list) and lst
            and all(isinstance(x, dict) for x in lst)
            and sum(1 for x in lst if pick(x, TITLE_KEYS)) >= max(1, len(lst) // 2))


def discover_records(obj):
    """Find the candidate-record list: prefer known keys, then fall back to
    the largest list of titled dicts anywhere in the tree."""
    keyed = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in CANDIDATE_KEYS and looks_like_records(v):
                    keyed.append(v)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(obj)
    if keyed:
        return max(keyed, key=len)

    best = []

    def walk2(node):
        nonlocal best
        if isinstance(node, dict):
            for v in node.values():
                walk2(v)
        elif isinstance(node, list):
            if looks_like_records(node) and len(node) > len(best):
                best = node
            for v in node:
                walk2(v)

    walk2(obj)
    return best


def clean_text(x):
    if x is None:
        return None
    if isinstance(x, list):
        x = "; ".join(str(i) for i in x)
    s = re.sub(r"\s+", " ", str(x)).strip()
    return s or None


def clean_year(x):
    if x is None:
        return None
    m = re.search(r"(19|20)\d{2}", str(x))
    return int(m.group(0)) if m else None


def clean_authors(x):
    if x is None:
        return []
    if isinstance(x, str):
        return [p.strip() for p in re.split(r";|\band\b|,", x) if p.strip()]
    out = []
    if isinstance(x, list):
        for a in x:
            if isinstance(a, dict):
                nm = a.get("name") or a.get("full_name") or a.get("display_name")
                if nm:
                    out.append(str(nm).strip())
            elif a not in (None, ""):
                out.append(str(a).strip())
    return out


def extract_provenance(rec):
    prov = {}
    for k in FIXTURE_KEYS:
        if k in rec and rec[k] not in (None, "", []):
            prov[k] = rec[k]
    return prov or None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", required=True, help="path to case.json")
    ap.add_argument("--task", default=None, help="path to task.md (optional)")
    ap.add_argument("--work", required=True, help="work directory")
    ap.add_argument("--out", required=True, help="output directory")
    args = ap.parse_args()

    os.makedirs(args.work, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)

    try:
        with open(args.case, encoding="utf-8") as fh:
            case = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        print("FATAL: cannot parse case file %s: %s" % (args.case, e),
              file=sys.stderr)
        return 2

    task_text = ""
    if args.task and os.path.exists(args.task):
        with open(args.task, encoding="utf-8") as fh:
            task_text = fh.read()

    case_id = case.get("case_id") or case.get("id") or case.get("name") or "UNKNOWN"
    question = pick(case, QUESTION_KEYS)
    if question is None and task_text:
        question = task_text.strip().splitlines()[0][:300]
    contract = pick(case, CONTRACT_KEYS) or []
    if isinstance(contract, dict):
        contract = list(contract.keys())
    elif not isinstance(contract, list):
        contract = [str(contract)]

    raw = discover_records(case)
    records, gaps = [], []
    for i, r in enumerate(raw):
        rid = "R%03d" % (i + 1)
        rec = {
            "record_id": rid,
            "source_id": clean_text(pick(r, SOURCE_ID_KEYS)),
            "title": clean_text(pick(r, TITLE_KEYS)),
            "abstract": clean_text(pick(r, ABSTRACT_KEYS)),
            "authors": clean_authors(pick(r, AUTHOR_KEYS)),
            "year": clean_year(pick(r, YEAR_KEYS)),
            "venue": clean_text(pick(r, VENUE_KEYS)),
            "doi": clean_text(pick(r, DOI_KEYS)),
            "url": clean_text(pick(r, URL_KEYS)),
            "provenance": extract_provenance(r),
            "raw_keys": sorted(r.keys()) if isinstance(r, dict) else [],
        }
        missing = [f for f in ("title", "abstract", "authors", "year")
                   if rec[f] in (None, "", [])]
        if missing:
            gaps.append({"record_id": rid, "missing": missing})
        records.append(rec)

    rec_path = os.path.join(args.work, "records.jsonl")
    with open(rec_path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    meta = {
        "case_id": case_id,
        "research_question": clean_text(question) or "",
        "contract_fields": contract,
        "record_count": len(records),
        "metadata_gaps": gaps,
        "change_log": [],
        "sources": [{"file": os.path.basename(args.case), "role": "case input"}]
        + ([{"file": os.path.basename(args.task), "role": "task brief"}]
           if task_text else []),
    }
    with open(os.path.join(args.work, "case_meta.json"), "w",
              encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    # Default rubric for inspection / optional model adjustment.
    rubric_path = None
    try:
        sys.dont_write_bytecode = True  # keep the skill bundle text-only
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from rank_engine import DEFAULT_RUBRIC
        rubric_path = os.path.join(args.work, "rubric.json")
        with open(rubric_path, "w", encoding="utf-8") as fh:
            json.dump(DEFAULT_RUBRIC, fh, ensure_ascii=False, indent=2)
    except Exception as e:  # rubric dump is best-effort; engine has built-ins
        print("WARNING: could not write default rubric: %s" % e,
              file=sys.stderr)
        rubric_path = None

    scaffold = {
        "case_id": case_id,
        "status": "partial",
        "status_note": "PENDING::scoring pipeline not finished",
        "research_question": meta["research_question"] or "PENDING::question",
        "counts": {"total": len(records), "retained": "PENDING::count",
                   "pending": "PENDING::count", "excluded": "PENDING::count"},
        "ranked_results": "PENDING::scoring not finished",
        "top_k": "PENDING::scoring not finished",
        "metadata_gaps": gaps,
        "uncertainty": "PENDING::scoring not finished",
        "sources": meta["sources"],
        "change_log": [],
    }
    with open(os.path.join(args.out, "result.json"), "w",
              encoding="utf-8") as fh:
        json.dump(scaffold, fh, ensure_ascii=False, indent=2)

    print(json.dumps({
        "case_id": case_id,
        "records": len(records),
        "metadata_gaps": len(gaps),
        "question_preview": (meta["research_question"] or "")[:120],
        "records_file": rec_path,
        "rubric_defaults": rubric_path,
        "scaffold": os.path.join(args.out, "result.json"),
    }, ensure_ascii=False, indent=2))
    if not records:
        print("WARNING: no candidate records discovered; empty candidate set "
              "is legal downstream, but check case.json keys.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

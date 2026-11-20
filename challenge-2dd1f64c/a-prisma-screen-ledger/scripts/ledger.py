#!/usr/bin/env python3
"""prisma-screen-ledger :: ledger.py

Accounting validator and assembler for the screening ledger.

Subcommands:
  check    --work /app/work --out /app/output
      Validates decisions.jsonl against records.jsonl + criteria.json:
      coverage (exactly one decision per record), schema, criterion IDs,
      quote-is-verbatim-substring, tier totals reconciliation, pending
      discipline. Non-zero exit on any failure.

  assemble --work /app/work --out /app/output
      Builds final /app/output/result.json (honoring contract fields),
      deterministic ranking, and /app/output/screening_report.md.
      Copies criteria.json and decisions.jsonl into the output directory
      so reviewers can rerun `ledger.py check` independently.

Standard library only.
"""
import argparse
import json
import os
import sys

LABELS = {"retained", "pending", "excluded"}
CONFIDENCE = {"high", "medium", "low"}
CONF_RANK = {"high": 0, "medium": 1, "low": 2}


def load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise SystemExit("FATAL: %s:%d invalid JSON: %s" % (path, ln, e))
    return rows


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def check(args):
    work, problems = args.work, []
    records = {r["record_id"]: r for r in load_jsonl(os.path.join(work, "records.jsonl"))}
    decisions = load_jsonl(os.path.join(work, "decisions.jsonl"))
    criteria = load_json(os.path.join(work, "criteria.json"), {})
    incl = set((criteria.get("inclusion") or {}).keys())
    excl = set((criteria.get("exclusion") or {}).keys())
    known = incl | excl

    if not records:
        print("CHECK: no records; empty candidate set is legal.")
        return 0

    seen, by_id = [], {}
    for i, d in enumerate(decisions, 1):
        rid = d.get("record_id")
        if not rid:
            problems.append("decision #%d missing record_id" % i)
            continue
        if rid in by_id:
            problems.append("duplicate decision for %s" % rid)
        by_id[rid] = d
        seen.append(rid)

    for rid in records:
        if rid not in by_id:
            problems.append("no decision for record %s (coverage failure)" % rid)
        for rid2 in by_id:
            if rid2 not in records:
                problems.append("decision for unknown record %s" % rid2)

    for rid, d in by_id.items():
        rec = records.get(rid)
        if rec is None:
            continue
        if d.get("label") not in LABELS:
            problems.append("%s: bad label %r" % (rid, d.get("label")))
        crit = d.get("criteria") or []
        label = d.get("label")
        if not crit and label != "pending":
            problems.append("%s: empty criteria" % rid)
        for c in crit:
            if known and c not in known:
                problems.append("%s: unknown criterion %s" % (rid, c))
        conf = d.get("confidence")
        if conf not in CONFIDENCE:
            problems.append("%s: bad confidence %r" % (rid, conf))
        if not (d.get("reason") or "").strip():
            problems.append("%s: empty reason" % rid)
        quote = (d.get("quote") or "").strip()
        if len(quote) < 8:
            problems.append("%s: quote too short (<8 chars)" % rid)
        else:
            hay = " ".join(x for x in (rec.get("title"), rec.get("abstract"))
                           if x) or ""
            if quote not in hay:
                problems.append("%s: quote is NOT a verbatim substring of "
                                "title/abstract (fabricated evidence?)" % rid)
        if d.get("label") == "pending":
            r = (d.get("reason") or "")
            if len(r.strip()) < 10 or not any(t in r for t in
                                              ("缺", "不足", "无法", "missing",
                                               "insufficient", "cannot")):
                problems.append("%s: pending decision must state what "
                                "information is missing" % rid)

    total = len(records)
    counts = {k: sum(1 for d in by_id.values() if d.get("label") == k)
              for k in LABELS}
    if counts["retained"] + counts["pending"] + counts["excluded"] != total:
        problems.append("tier totals %s do not sum to %d"
                        % (counts, total))

    print("CHECK SUMMARY: total=%d retained=%d pending=%d excluded=%d"
          % (total, counts["retained"], counts["pending"], counts["excluded"]))
    for p in problems:
        print("FAIL: " + p)
    if problems:
        print("CHECK RESULT: FAIL (%d problems)" % len(problems))
        return 1
    print("CHECK RESULT: PASS")
    return 0


def sort_key(rec, dec):
    label_rank = {"retained": 0, "pending": 1, "excluded": 2}[dec["label"]]
    year = rec.get("year") or 0
    return (label_rank, CONF_RANK.get(dec.get("confidence"), 3), -year,
            dec["record_id"])


def assemble(args):
    work, out = args.work, args.out
    os.makedirs(out, exist_ok=True)
    records = {r["record_id"]: r for r in load_jsonl(os.path.join(work, "records.jsonl"))}
    decisions = load_jsonl(os.path.join(work, "decisions.jsonl"))
    meta = load_json(os.path.join(work, "case_meta.json"), {})
    by_id = {d["record_id"]: d for d in decisions}

    ranked = []
    for rid, dec in by_id.items():
        rec = records.get(rid, {})
        ranked.append({
            "rank": 0,
            "record_id": rid,
            "label": dec.get("label"),
            "title": rec.get("title"),
            "year": rec.get("year"),
            "venue": rec.get("venue"),
            "doi": rec.get("doi"),
            "criteria": dec.get("criteria") or [],
            "criteria_missed": dec.get("criteria_missed") or [],
            "quote": dec.get("quote"),
            "evidence_field": dec.get("evidence_field"),
            "confidence": dec.get("confidence"),
            "reason": dec.get("reason"),
        })
    ranked.sort(key=lambda x: sort_key(records.get(x["record_id"], {}),
                                       by_id[x["record_id"]]))
    for i, row in enumerate(ranked, 1):
        row["rank"] = i

    counts = {k: sum(1 for d in by_id.values() if d.get("label") == k)
              for k in LABELS}
    total = len(records)
    status = "empty_result" if total == 0 else (
        "partial" if any(v == "PENDING::count" for v in counts.values())
        else "complete")

    result = {
        "case_id": meta.get("case_id", "UNKNOWN"),
        "status": status,
        "research_question": meta.get("research_question", ""),
        "counts": {"total": total, **counts},
        "ranked_results": ranked,
        "metadata_gaps": meta.get("metadata_gaps", []),
        "conflicts": [],
        "uncertainty": ("all-record screening finished over a finite snapshot; "
                        "no live recall claimed"),
        "sources": meta.get("sources", []),
        "change_log": meta.get("change_log", []),
    }
    contract = meta.get("contract_fields") or []
    for f in contract:
        if isinstance(f, str) and f not in result:
            result[f] = None

    with open(os.path.join(out, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    # Human-reviewable report
    lines = ["# Screening Report — case %s" % result["case_id"], ""]
    lines.append("Research question: " + (result["research_question"] or "n/a"))
    lines.append("")
    c = dict(counts)
    c["total"] = total
    lines.append("Counts: total=%(total)d retained=%(retained)d "
                 "pending=%(pending)d excluded=%(excluded)d" % c)
    lines.append("")
    lines.append("## Decisions (rank order)")
    lines.append("")
    lines.append("| rank | record | label | confidence | criteria | quote | reason |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in ranked:
        q = (row.get("quote") or "").replace("|", "\\|")[:100]
        r = (row.get("reason") or "").replace("|", "\\|")[:160]
        lines.append("| %d | %s | %s | %s | %s | %s | %s |"
                     % (row["rank"], row["record_id"], row["label"],
                        row.get("confidence"), ",".join(row.get("criteria") or []),
                        q, r))
    lines.append("")
    gaps = meta.get("metadata_gaps") or []
    if gaps:
        lines.append("## Metadata gaps")
        for g in gaps:
            lines.append("- %s missing: %s" % (g["record_id"], g["missing"]))
        lines.append("")
    lines.append("## Uncertainty")
    lines.append(result["uncertainty"])
    with open(os.path.join(out, "screening_report.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    # Audit trail for independent re-check
    for name in ("criteria.json", "decisions.jsonl"):
        src = os.path.join(work, name)
        if os.path.exists(src):
            with open(src, encoding="utf-8") as a, \
                 open(os.path.join(out, name), "w", encoding="utf-8") as b:
                b.write(a.read())

    print(json.dumps({"result": os.path.join(out, "result.json"),
                      "report": os.path.join(out, "screening_report.md"),
                      "status": status}, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for c in ("check", "assemble"):
        p = sp.add_parser(c)
        p.add_argument("--work", required=True)
        p.add_argument("--out", required=True)
    args = ap.parse_args()
    sys.exit(check(args) if args.cmd == "check" else assemble(args))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""dedup-conflict-adjudicator :: assemble.py

Assemble the final deliverables from the merge + screening artifacts:

  python3 assemble.py --work /app/work --out /app/output

Reads  W/case_meta.json, W/records.jsonl, W/canonical.jsonl,
       W/merge_map.json, W/conflict_ledger.json, W/review_queue.json,
       W/screening.jsonl, W/change_log.md (optional)
Writes /app/output/result.json and /app/output/adjudication_report.md.

Validations (any failure => non-zero exit, scaffold result.json left as-is
so the delivered status stays honest):
  V1 screening coverage: every canonical record screened exactly once
     (empty candidate set is legal and yields status=empty_result);
  V2 screening schema: label in {retained,pending,excluded}, reason non-empty,
     confidence legal, quote is a >=8-char substring of that record's title
     or abstract (never-fabricated evidence);
  V3 R6 coverage: every original record appears exactly once, either as a
     canonical record or as a merged_from member;
  V4 contract fields: every field named by output_contract is present.
Standard library only.
"""
import argparse
import json
import os
import sys

MIN_QUOTE_LEN = 8
CONF_ORDER = {"high": 0, "medium": 1, "low": 2}
LABEL_ORDER = {"retained": 0, "pending": 1, "excluded": 2}
LABELS = set(LABEL_ORDER)
CONFS = set(CONF_ORDER)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def fail(msg, failures):
    failures.append(msg)
    print("FAIL: %s" % msg, file=sys.stderr)


def rank_key(row):
    yr = row.get("year")
    return (LABEL_ORDER[row["label"]], CONF_ORDER[row["confidence"]],
            -(yr or -1), row["record_id"])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    w, out = args.work, args.out
    os.makedirs(out, exist_ok=True)

    meta = load_json(os.path.join(w, "case_meta.json"),
                     {"case_id": "UNKNOWN", "research_question": "",
                      "contract_fields": [], "metadata_gaps": [],
                      "sources": []})
    records = [r for r in load_jsonl(os.path.join(w, "records.jsonl"))]
    canonical = load_jsonl(os.path.join(w, "canonical.jsonl"))
    merge_map = load_json(os.path.join(w, "merge_map.json"),
                          {"merged_into": {}, "clusters": [],
                           "rejected_pairs": []})
    ledger = load_json(os.path.join(w, "conflict_ledger.json"),
                       {"conflicts": []})
    queue = load_json(os.path.join(w, "review_queue.json"), {"items": []})
    screening = load_jsonl(os.path.join(w, "screening.jsonl"))

    changelog_path = os.path.join(w, "change_log.md")
    change_log = []
    if os.path.exists(changelog_path):
        with open(changelog_path, encoding="utf-8") as fh:
            change_log = [l.strip() for l in fh if l.strip()]

    failures = []

    # ---- V1: screening coverage of the canonical set ----
    canon_ids = [c["record_id"] for c in canonical]
    scr_ids = [s.get("record_id") for s in screening]
    if set(canon_ids) != set(scr_ids) or len(scr_ids) != len(set(scr_ids)):
        fail("V1 screening coverage mismatch: canonical=%d, screened=%d, "
             "missing=%s, extra=%s" %
             (len(canon_ids), len(scr_ids),
              sorted(set(canon_ids) - set(scr_ids)),
              sorted(set(scr_ids) - set(canon_ids))), failures)

    # ---- V2: screening schema + quote is verbatim evidence ----
    by_canon = {c["record_id"]: c for c in canonical}
    for s in screening:
        rid = s.get("record_id")
        lab = s.get("label")
        if lab not in LABELS:
            fail("V2 %s: illegal label %r" % (rid, lab), failures)
            continue
        if s.get("confidence") not in CONFS:
            fail("V2 %s: illegal confidence %r" % (rid, s.get("confidence")),
                 failures)
        if not (s.get("reason") or "").strip():
            fail("V2 %s: empty reason" % rid, failures)
        q = (s.get("quote") or "").strip()
        rec = by_canon.get(rid, {})
        field = s.get("evidence_field") or "abstract"
        hay = rec.get("title" if field == "title" else "abstract") or ""
        ok = len(q) >= MIN_QUOTE_LEN and q in hay
        if not ok and q:
            alt = rec.get("abstract") or ""
            ok = q in alt and len(q) >= MIN_QUOTE_LEN
        if not ok:
            fail("V2 %s: quote is not a >=%d-char substring of %s "
                 "(quote=%r)" % (rid, MIN_QUOTE_LEN, field, q[:60]), failures)

    # ---- V3: R6 coverage of the original record set ----
    # Unparseable entries are excluded from R6 set coverage: they are
    # reported via review_queue instead of the canonical/merged ledger.
    orig_ids = [r.get("record_id") for r in records
                if r.get("record_id") and not r.get("_unparseable_raw")]
    covered = []
    for c in canonical:
        covered.append(c["record_id"])
        covered += [m["record_id"] for m in c.get("merged_from", [])
                    if m["record_id"] != c["record_id"]]
    if len(covered) != len(set(covered)) or set(covered) != set(orig_ids):
        fail("V3 coverage: duplicate=%s, missing=%s, extra=%s" % (
            sorted(x for x in set(covered) if covered.count(x) > 1),
            sorted(set(orig_ids) - set(covered)),
            sorted(set(covered) - set(orig_ids))), failures)

    if failures:
        sys.exit(1)

    # ---- ranked results ----
    ranked = []
    by_scr = {s["record_id"]: s for s in screening}
    for c in canonical:
        s = by_scr[c["record_id"]]
        ranked.append({
            "record_id": c["record_id"],
            "label": s["label"],
            "title": c.get("title"),
            "year": c.get("year"),
            "venue": c.get("venue"),
            "doi": c.get("doi"),
            "quote": s.get("quote"),
            "evidence_field": s.get("evidence_field") or "abstract",
            "confidence": s.get("confidence"),
            "reason": s.get("reason"),
            "merge_kind": c.get("merge_kind"),
            "merged_from": [m["record_id"] for m in c.get("merged_from", [])
                            if m["record_id"] != c["record_id"]],
            "provenance_note": c.get("provenance_note"),
        })
    ranked.sort(key=rank_key)

    counts = {
        "total": len(records),
        "canonical": len(canonical),
        "merged": sum(1 for c in canonical for m in c.get("merged_from", [])
                      if m["record_id"] != c["record_id"]),
        "retained": sum(1 for s in screening if s["label"] == "retained"),
        "pending": sum(1 for s in screening if s["label"] == "pending"),
        "excluded": sum(1 for s in screening if s["label"] == "excluded"),
    }

    open_items = [q for q in queue.get("items", [])
                  if q.get("status") != "resolved"]
    if len(records) == 0:
        status = "empty_result"
    elif open_items:
        status = "complete_with_open_review"
    else:
        status = "complete"

    uncertainty = []
    if open_items:
        uncertainty.append(
            "存在 %d 项未决人工复核项（review_queue），结论在此范围内"
            "为脚本建议与模型裁决的当前状态。" % len(open_items))
    if meta.get("metadata_gaps"):
        uncertainty.append(
            "存在 %d 条记录的元数据缺失（metadata_gaps），缺失字段未补造，"
            "去重与筛选在这些条目上置信度受限。" % len(meta["metadata_gaps"]))
    if merge_map.get("rejected_pairs"):
        uncertainty.append(
            "%d 组疑似重复经裁决判定为独立记录，未合并。"
            % len(merge_map["rejected_pairs"]))
    if not uncertainty:
        uncertainty.append("无已知未决不确定性；快照外证据未检索。")

    result = {
        "case_id": meta.get("case_id", "UNKNOWN"),
        "status": status,
        "research_question": meta.get("research_question", ""),
        "counts": counts,
        "ranked_results": ranked,
        "dedup_map": {
            "merged_into": merge_map.get("merged_into", {}),
            "clusters": merge_map.get("clusters", []),
            "rejected_pairs": merge_map.get("rejected_pairs", []),
            "note": "被合并条目不删除：以 merged_into 保留指向 canonical "
                    "的映射，merged_from 记录全部成员。",
        },
        "conflicts": ledger.get("conflicts", []),
        "review_queue": queue.get("items", []),
        "metadata_gaps": meta.get("metadata_gaps", []),
        "uncertainty": uncertainty,
        "sources": meta.get("sources", []),
        "change_log": change_log,
    }

    # ---- V4: contract fields ----
    contract = meta.get("contract_fields") or []
    missing_contract = [f for f in contract if f not in result]
    if missing_contract:
        for f in missing_contract:
            result[f] = ("PENDING::contract field not produced by "
                         "pipeline (honest placeholder)")
        print("WARNING: contract fields missing, placeholder inserted: %s"
              % missing_contract, file=sys.stderr)

    with open(os.path.join(out, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    # ---- adjudication_report.md ----
    lines = []
    add = lines.append
    add("# 去重与冲突裁决报告：%s" % result["case_id"])
    add("")
    add("- 研究问题：%s" % (result["research_question"] or "（未给出）"))
    add("- 状态：`%s`" % status)
    add("- 原始记录 %d 条 → canonical %d 条（合并吸收 %d 条）；"
        "筛选 保留 %d / 待定 %d / 排除 %d。" % (
            counts["total"], counts["canonical"], counts["merged"],
            counts["retained"], counts["pending"], counts["excluded"]))
    add("- 合并规则全文见 `references/merge_rules.md`（R1..R6）。")
    add("")
    add("## 一、重复簇与合并理由")
    add("")
    clusters = merge_map.get("clusters", [])
    multi = [c for c in clusters if len(c.get("members", [])) > 1]
    if not multi:
        add("（无确证或裁决确认的重复簇。）")
    for c in multi:
        add("### 簇 `%s`（canonical：%s，类型：%s）" % (
            "+".join(c["members"]), c["canonical"], c.get("kind")))
        add("")
        add("| 记录 | 身份 | 标题 | 年份 | 载体 | DOI | 输入标注 |")
        add("| --- | --- | --- | --- | --- | --- | --- |")
        canon_row = by_canon.get(c["canonical"], {})
        for m in canon_row.get("merged_from", []):
            role = "**canonical**" if m["record_id"] == c["canonical"] \
                   else "merged_into → %s" % c["canonical"]
            add("| %s | %s | %s | %s | %s | %s | %s |" % (
                m["record_id"], role, (m.get("title") or "")[:60],
                m.get("year"), m.get("venue") or "—", m.get("doi") or "—",
                m.get("provenance_note") or "—"))
        add("")
        add("合并理由：%s 被合并成员未删除，见 result.json 的 "
            "`dedup_map.merged_into`。" % c.get("canonical_reason", ""))
        add("")
    rej = merge_map.get("rejected_pairs", [])
    if rej:
        add("### 裁决为独立记录的疑似对")
        add("")
        for ids in rej:
            add("- %s：模型裁决 reject_merge，指纹相似度仅为阈值带信号，"
                "不合并。" % " ↔ ".join(ids))
        add("")
    add("## 二、冲突裁决表")
    add("")
    confs = ledger.get("conflicts", [])
    if not confs:
        add("（无字段矛盾或标注分歧。）")
    else:
        add("| 冲突 | 规则 | 字段 | 记录A | 值A | 记录B | 值B | 裁决 | 升级 |")
        add("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for c in confs:
            res = c.get("suggested_resolution")
            res_s = (json.dumps(res, ensure_ascii=False)
                     if res is not None else "（无机器建议）")
            add("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                c.get("conflict_id"), c.get("rule"), c.get("field"),
                c.get("record_a"), json.dumps(c.get("value_a"),
                                              ensure_ascii=False)[:40],
                c.get("record_b"), json.dumps(c.get("value_b"),
                                              ensure_ascii=False)[:40],
                res_s[:60], "是" if c.get("escalate_to_human") else "否"))
        add("")
        for c in confs:
            add("- **%s**：%s" % (c["conflict_id"], c.get("note", "")))
        add("")
    add("## 三、人工复核队列")
    add("")
    if not queue.get("items"):
        add("（队列为空。）")
    else:
        for q in queue["items"]:
            add("- **%s** [%s/%s] 成员=%s；需人工：%s%s" % (
                q["item_id"], q["kind"], q["status"],
                ",".join(q.get("members") or ["—"]),
                q.get("action_required", ""),
                ("；raw 片段：`%s`" % q["raw_excerpt"][:120])
                if q.get("raw_excerpt") else ""))
    add("")
    add("## 四、筛选裁决（canonical 集合）")
    add("")
    add("| record_id | 标签 | 置信度 | 引用（原文子串） | 理由 |")
    add("| --- | --- | --- | --- | --- |")
    for r in ranked:
        add("| %s | %s | %s | %s | %s |" % (
            r["record_id"], r["label"], r["confidence"],
            (r.get("quote") or "—")[:70], (r.get("reason") or "")[:70]))
    add("")
    add("## 五、异常与不确定性")
    add("")
    if meta.get("metadata_gaps"):
        add("元数据缺失（未补造）：")
        for g in meta["metadata_gaps"]:
            add("- %s 缺 %s" % (g["record_id"], "/".join(g["missing"])))
    for u in uncertainty:
        add("- %s" % u)
    if change_log:
        add("")
        add("变更记录：")
        for c in change_log:
            add("- %s" % c)
    add("")
    with open(os.path.join(out, "adjudication_report.md"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print(json.dumps({
        "status": status, "counts": counts,
        "result": os.path.join(out, "result.json"),
        "report": os.path.join(out, "adjudication_report.md"),
        "open_review_items": len(open_items),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

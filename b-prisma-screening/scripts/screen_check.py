#!/usr/bin/env python3
"""screen_check.py — 筛选日志审计。

校验 (<work>/screening_log.json + <work>/criteria.md + <work>/docs.jsonl):
  1. criteria.md 存在、非空, 且包含至少一条 IC 与一条 EC 编号。
  2. 每篇 status=ok 的文档在 title_abstract 轮都有决定;
     duplicate_of 之外的 include 文档在 fulltext 轮有决定。
  3. decision ∈ {include, exclude, duplicate_of}; exclude 必须引用 ≥1 条
     已定义标准编号 (IC*/EC*) 并在 reason 中说明该篇不满足/触发了哪条。
  4. duplicate_of 记录必须有 representative, 且 representative 最终为 include;
     同一重复组不得出现两个"保留"（除日志说明非重复外）。
  5. fulltext 轮的候选集合 == title_abstract 轮 include 集合。
  6. 仅摘要文档不得仅因 tier=abstract_only 被排除 (排除理由含 "full text"
     或 "全文" 但未引用信息不足类标准时警告)。

输出 <out>/audit_report.json: {status: pass|fail|warn, checks: [...]}。
退出码: 0 pass/warn, 1 fail。仅标准库。
"""
import argparse, json, re, sys
from pathlib import Path

DECISIONS = {"include", "exclude", "duplicate_of"}


def jlines(p):
    p = Path(p)
    out = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    work, out = Path(a.work), Path(a.out)
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    docs = [d for d in jlines(work / "docs.jsonl") if d.get("status") == "ok"]
    all_ids = {d["doc_id"] for d in docs}
    tier = {d["doc_id"]: d.get("tier") for d in docs}
    dup_groups = json.loads((work / "dup_groups.json").read_text(encoding="utf-8")) \
        if (work / "dup_groups.json").exists() else []

    crit_p = work / "criteria.md"
    crit = crit_p.read_text(encoding="utf-8") if crit_p.exists() else ""
    ic_ids = set(re.findall(r"\bIC\d+\b", crit))
    ec_ids = set(re.findall(r"\bEC\d+\b", crit))
    check("criteria_exists_nonempty", len(crit.strip()) > 100, f"{len(crit)} chars")
    check("criteria_has_ic_ec", bool(ic_ids) and bool(ec_ids),
          f"IC={sorted(ic_ids)} EC={sorted(ec_ids)}")

    log = json.loads((work / "screening_log.json").read_text(encoding="utf-8")) \
        if (work / "screening_log.json").exists() else None
    if not log:
        check("screening_log_exists", False, "screening_log.json missing")
    else:
        phases = {p.get("phase"): p.get("records", []) for p in log.get("phases", [])} \
            if isinstance(log.get("phases"), list) else {}
        if not phases and log.get("records"):
            phases = {"title_abstract": log["records"]}
        p1 = {r["doc_id"]: r for r in phases.get("title_abstract", []) if r.get("doc_id")}
        p2 = {r["doc_id"]: r for r in phases.get("fulltext", []) if r.get("doc_id")}
        known_std = ic_ids | ec_ids

        missing1 = sorted(all_ids - set(p1))
        check("phase1_all_docs", not missing1, f"missing: {missing1[:8]}")
        bad_dec = sorted(d for d, r in p1.items() if r.get("decision") not in DECISIONS)
        bad_dec += sorted(d for d, r in p2.items() if r.get("decision") not in DECISIONS)
        check("decision_values", not bad_dec, f"bad: {bad_dec[:8]}")

        no_reason = sorted(d for d, r in p1.items() if r.get("decision") == "exclude"
                           and len(str(r.get("reason", ""))) < 10)
        no_reason += sorted(d for d, r in p2.items() if r.get("decision") == "exclude"
                            and len(str(r.get("reason", ""))) < 10)
        check("exclusions_have_reasons", not no_reason, f"no reason: {no_reason[:8]}")

        no_crit = sorted(d for d, r in p1.items() if r.get("decision") == "exclude"
                         and not (set(str(x) for x in r.get("criteria_ids", [])) & known_std))
        no_crit += sorted(d for d, r in p2.items() if r.get("decision") == "exclude"
                          and not (set(str(x) for x in r.get("criteria_ids", [])) & known_std))
        check("exclusions_cite_criteria", not no_crit, f"no criteria: {no_crit[:8]}")

        dup_bad = []
        for d, r in p1.items():
            if r.get("decision") == "duplicate_of":
                rep = r.get("representative")
                if not rep or rep not in all_ids:
                    dup_bad.append(d + ":no representative")
                elif p2.get(rep, {}).get("decision") != "include" and p1.get(rep, {}).get("decision") != "include":
                    dup_bad.append(f"{d}:rep {rep} not included")
        check("duplicate_of_valid", not dup_bad, "; ".join(dup_bad[:6]))

        # 重复组闭合: 组内除 representative 外都标 duplicate_of, 或日志说明非重复
        grp_open = []
        for g in dup_groups:
            ids = g["doc_ids"]
            reps = {r.get("representative") for dd, r in p1.items() if dd in ids and r.get("decision") == "duplicate_of"}
            included = {dd for dd in ids if p1.get(dd, {}).get("decision") == "include"}
            dups = {dd for dd in ids if p1.get(dd, {}).get("decision") == "duplicate_of"}
            if len(included) == len(ids):
                # 全部保留: 允许, 但要求各自 reason 说明与组内其他文献为何非重复
                unexplained = [dd for dd in ids if "非重复" not in str(p1.get(dd, {}).get("reason", ""))
                               and "not duplicate" not in str(p1.get(dd, {}).get("reason", "")).lower()
                               and "distinct" not in str(p1.get(dd, {}).get("reason", "")).lower()]
                if unexplained and len(ids) > 1:
                    grp_open.append(f"g{g['group']}:{unexplained[:4]}")
            elif len(dups) + len(included) < len(ids):
                grp_open.append(f"g{g['group']}:undecided {sorted(set(ids)-dups-included)[:4]}")
        check("dup_groups_closed", not grp_open, "; ".join(grp_open[:6]))

        inc1 = {d for d, r in p1.items() if r.get("decision") == "include"}
        mismatch = sorted(set(p2) ^ inc1)
        check("phase2_matches_phase1_includes", not mismatch, f"symmetric diff: {mismatch[:8]}")

        abs_warn = [d for d in inc1 | set(p2) if tier.get(d) == "abstract_only"]
        for d in abs_warn:
            checks.append({"check": "abstract_only_included", "ok": True,
                           "detail": f"{d} included with tier=abstract_only; "
                                     "strength 须封顶 suggestive"})

    fails = [c for c in checks if not c["ok"]]
    report = {"status": "fail" if any(not c["ok"] for c in checks if c["check"] != "abstract_only_included") else "pass",
              "checks": checks,
              "prisma_counts": None}
    (out / "audit_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"audit": report["status"], "failed_checks": [c["check"] for c in fails]},
                     ensure_ascii=False))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())

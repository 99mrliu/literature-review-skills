#!/usr/bin/env python3
"""prisma_flow.py — 从筛选日志推导 PRISMA 流程计数与流程表。

计数一律由脚本计算, 禁止从日志外的手写数字复制。
输出 <out>/prisma_flow.json 与 <out>/prisma_flow.md。
仅标准库。
"""
import argparse, json, sys
from pathlib import Path


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
    docs = jlines(work / "docs.jsonl")
    log_p = work / "screening_log.json"
    flow = {"identified_records": len(docs),
            "records_after_dedup": None,
            "title_abstract_screened": 0, "title_abstract_excluded": 0,
            "fulltext_assessed": 0, "fulltext_excluded": 0, "included": 0,
            "notes": []}
    if log_p.exists():
        log = json.loads(log_p.read_text(encoding="utf-8"))
        phases = {p.get("phase"): p.get("records", []) for p in log.get("phases", [])} \
            if isinstance(log.get("phases"), list) else {}
        if not phases and log.get("records"):
            phases = {"title_abstract": log["records"]}
        p1, p2 = phases.get("title_abstract", []), phases.get("fulltext", [])
        inc1 = [r for r in p1 if r.get("decision") == "include"]
        exc1 = [r for r in p1 if r.get("decision") == "exclude"]
        dups = [r for r in p1 if r.get("decision") == "duplicate_of"]
        inc2 = [r for r in p2 if r.get("decision") == "include"]
        exc2 = [r for r in p2 if r.get("decision") == "exclude"]
        flow.update({
            "records_after_dedup": len(docs) - len(dups),
            "title_abstract_screened": len(p1),
            "title_abstract_excluded": len(exc1),
            "fulltext_assessed": len(p2),
            "fulltext_excluded": len(exc2),
            "included": len(inc2) if p2 else len(inc1)})
        excl_summary = {}
        for r in exc1 + exc2:
            for c in r.get("criteria_ids", ["unspecified"]):
                excl_summary[c] = excl_summary.get(c, 0) + 1
        flow["exclusion_reasons"] = excl_summary
    else:
        flow["notes"].append("screening_log.json 缺失, 流程计数不可用")

    (out / "prisma_flow.json").write_text(json.dumps(flow, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# PRISMA 流程记录（由 prisma_flow.py 从筛选日志推导）", "",
          f"- 识别文献: {flow['identified_records']}",
          f"- 去重后保留: {flow['records_after_dedup']}",
          f"- 题录/摘要筛序: {flow['title_abstract_screened']}（排除 {flow['title_abstract_excluded']}）",
          f"- 全文复核: {flow['fulltext_assessed']}（排除 {flow['fulltext_excluded']}）",
          f"- 最终纳入: {flow['included']}", ""]
    if flow.get("exclusion_reasons"):
        md += ["## 排除理由分布（标准编号 → 篇数）", ""]
        md += [f"- {k}: {v}" for k, v in sorted(flow["exclusion_reasons"].items())]
    (out / "prisma_flow.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"flow": "written", "included": flow["included"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

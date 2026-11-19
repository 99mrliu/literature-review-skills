#!/usr/bin/env python3
"""build_result.py — prisma-repro-screening 的 result.json 组装。

原则:
  1. mirror case.json 中 output_contract 全部字段, 不遗漏;
  2. 恒含 case_id / status / sources / uncertainties / change_log;
  3. audit fail 且未修复 → status 封顶 partial; 零可用文献 → blocked;
  4. 缺失内容填 null 并在 uncertainties 说明, 不伪造。
仅标准库。
"""
import argparse, json
from pathlib import Path


def deep_find(obj, keys):
    low = {k.lower() for k in keys}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in low:
                return v
        for v in obj.values():
            r = deep_find(v, keys)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = deep_find(v, keys)
            if r is not None:
                return r
    return None


def jload(p, default=None):
    p = Path(p)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


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
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--status", default=None)
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    work, out = Path(a.work), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    case = jload(a.case, {}) or {}
    meta = jload(work / "case_meta.json", {}) or {}
    case_id = meta.get("case_id") or deep_find(case, ["case_id", "caseId", "id"]) or Path(a.case).stem
    contract = meta.get("output_contract")
    if contract is None:
        contract = deep_find(case, ["output_contract", "contract", "output_fields", "required_fields"])

    docs = jlines(work / "docs.jsonl")
    em = jload(work / "extract_meta.json", {}) or {}
    audit = jload(out / "audit_report.json", None)
    flow = jload(out / "prisma_flow.json", None)
    ledger = jlines(work / "evidence_table.jsonl")
    log_p = work / "screening_log.json"
    screening_log = jload(log_p, None)
    criteria = (work / "criteria.md").read_text(encoding="utf-8") if (work / "criteria.md").exists() else None
    themes = (work / "themes.md").read_text(encoding="utf-8") if (work / "themes.md").exists() else None
    draft_p = out / "review_draft.md"
    draft = draft_p.read_text(encoding="utf-8") if draft_p.exists() else None

    uncertainties = []
    if not any(d.get("status") == "ok" for d in docs):
        uncertainties.append("零可用文献: 语料为空或全部解析失败, 结果为 blocked 说明")
    uncertainties += [f"extract failure {f['doc_id']}: {f['reason']}" for f in em.get("failures", [])]
    uncertainties += [d["doc_id"] + " tier=abstract_only" for d in docs if d.get("tier") == "abstract_only"]
    if audit and audit.get("status") == "fail":
        bad = [c["check"] for c in audit.get("checks", []) if not c.get("ok")]
        uncertainties.append("audit 未通过: " + ",".join(bad))
    if not screening_log:
        uncertainties.append("screening_log.json 缺失")
    if not ledger:
        uncertainties.append("evidence_table.jsonl 缺失")
    if not draft:
        uncertainties.append("review_draft.md 缺失, 综述未完成")

    if a.status:
        status = a.status
    else:
        n_ok = sum(1 for d in docs if d.get("status") == "ok")
        ok = (draft is not None and screening_log is not None and audit is not None
              and audit.get("status") in ("pass", "warn") and ledger and n_ok > 0)
        if ok and not em.get("failures"):
            status = "completed"
        elif n_ok == 0:
            status = "blocked"
        else:
            status = "partial"

    change_log = []
    rl = work / "run_log.jsonl"
    if rl.exists():
        change_log = [ln.strip() for ln in rl.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if a.note:
        change_log.append(a.note)

    default = {
        "case_id": case_id,
        "status": status,
        "research_product": {
            "question": meta.get("research_question"),
            "themes_note": themes[:4000] if themes else None,
            "draft": draft,
            "draft_path": str(draft_p) if draft else None,
        },
        "screening_log": {
            "criteria_md": criteria,
            "decisions": screening_log,
            "prisma_flow": flow,
        },
        "evidence_matrix": ledger,
        "uncertainties": uncertainties,
        "sources": [{"doc_id": d["doc_id"], "path": d.get("path"), "sha256": d.get("sha256"),
                     "tier": d.get("tier"), "extract_method": d.get("extract_method"),
                     "dup_group": d.get("dup_group"),
                     "title": d.get("title") or (d.get("meta") or {}).get("title"),
                     "status": d.get("status")} for d in docs],
        "change_log": change_log,
    }

    result = dict(default)
    if isinstance(contract, (list, dict)):
        keys = contract if isinstance(contract, list) else list(contract)
        for k in keys:
            if isinstance(k, str) and k not in result:
                result[k] = default.get(k)
                if result[k] is None:
                    uncertainties.append(f"output_contract 字段 {k} 无对应内容, 置 null")
    result["uncertainties"] = uncertainties
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"result": str(out / "result.json"), "status": status,
                      "case_id": case_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""build_result.py — 组装 /app/output/result.json。

原则:
  1. mirror case.json 中的 output_contract 全部字段(列表或字典), 不遗漏;
  2. 恒含 case_id / status / sources / uncertainties / change_log;
  3. 证据表只收 verified 行; 若 gate_report 显示降级且未修复, status 封顶 partial;
  4. 任何缺失内容填 null 并在 uncertainties 说明, 不伪造。

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
    ap.add_argument("--status", default=None, help="强制 status (init 阶段用 in_progress/blocked)")
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
    gate = jload(out / "gate_report.json", None)
    ledger = jlines(work / "evidence_verified.jsonl") or jlines(work / "evidence_ledger.jsonl")
    screening_md = (work / "screening.md").read_text(encoding="utf-8") if (work / "screening.md").exists() else None
    themes_md = (work / "themes.md").read_text(encoding="utf-8") if (work / "themes.md").exists() else None
    draft_p = out / "review_draft.md"
    draft = draft_p.read_text(encoding="utf-8") if draft_p.exists() else None

    uncertainties = []
    if not any(d.get("status") == "ok" for d in docs):
        uncertainties.append("零可用文献: 语料为空或全部解析失败, 结果为 blocked 说明")
    uncertainties += [f"extract failure {f['doc_id']}: {f['reason']}" for f in em.get("failures", [])]
    uncertainties += [d["doc_id"] + " tier=abstract_only" for d in docs if d.get("tier") == "abstract_only"]
    if gate:
        if gate.get("status") == "degraded":
            uncertainties.append("gate: 草稿存在未通过核验的引证, 相关句子已降级 (gate_report.json)")
        if gate.get("status") == "no_draft":
            uncertainties.append("draft 缺失, 综述正文未完成")
    if not screening_md:
        uncertainties.append("screening.md 缺失, 筛选标准与决定未留痕")
    if not themes_md:
        uncertainties.append("themes.md 缺失, 主题归纳未完成")

    # status 决策
    if a.status:
        status = a.status
    else:
        n_docs = len(docs)
        n_failed = len(em.get("failures", []))
        ok = (draft is not None and screening_md is not None and themes_md is not None
              and n_docs > 0 and gate is not None and gate.get("status") == "pass")
        if ok and n_failed == 0:
            status = "completed"
        elif n_docs == 0 or (n_docs > 0 and n_docs == n_failed):
            status = "blocked"
        else:
            status = "partial"

    log_p = work / "run_log.jsonl"
    change_log = []
    if log_p.exists():
        change_log = [ln.strip() for ln in log_p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if a.note:
        change_log.append(a.note)

    sources = [{"doc_id": d["doc_id"], "path": d.get("path"), "sha256": d.get("sha256"),
                "tier": d.get("tier"), "extract_method": d.get("extract_method"),
                "title": d.get("title") or (d.get("meta") or {}).get("title"),
                "status": d.get("status")} for d in docs]
    evidence = [r for r in ledger if r.get("verified") or r.get("strength") == "no_adverse_found"]

    screening = {"criteria_note": "见 screening.md (含 IC/EC 编号与逐篇决定)" if screening_md else None,
                 "tiers": em.get("tiers", {}), "doc_count": len(docs)}
    if screening_md:
        screening["raw"] = screening_md

    product = {
        "research_question": meta.get("research_question"),
        "themes_note": themes_md[:4000] if themes_md else None,
        "draft": draft,
        "draft_path": str(draft_p) if draft else None,
    }

    default = {
        "case_id": case_id,
        "status": status,
        "research_product": product,
        "evidence_matrix": evidence,
        "screening_log": screening,
        "uncertainties": uncertainties,
        "sources": sources,
        "change_log": change_log,
    }

    # mirror output_contract
    result = dict(default)
    if isinstance(contract, list):
        for k in contract:
            if isinstance(k, str) and k not in result:
                result[k] = default.get(k)
                if result[k] is None:
                    uncertainties.append(f"output_contract 字段 {k} 无对应内容, 置 null")
    elif isinstance(contract, dict):
        for k in contract:
            if k not in result:
                result[k] = default.get(k)
                if result[k] is None:
                    uncertainties.append(f"output_contract 字段 {k} 无对应内容, 置 null")
    result["uncertainties"] = uncertainties

    (out / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"result": str(out / "result.json"), "status": status,
                      "case_id": case_id, "fields": list(result)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    main()

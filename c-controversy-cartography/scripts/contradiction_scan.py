#!/usr/bin/env python3
"""contradiction_scan.py — 同主题方向相反 / 数值冲突的论断对扫描。

输入: <work>/claims.jsonl (模型裁定, 字段含 claim_id, doc_id, anchor, statement,
direction, topic_hint, metric?, value?) 与 <work>/themes.md (脚本只取主题→文档映射,
用 themes_map.json 优先: 若不存在则从 themes.md 解析 "[T1]" 行后的文档列表)。

输出 <work>/controversy_candidates.json:
  {"pairs": [{"pair_id":"X1","claim_a":"C1","claim_b":"C5","theme":"T2",
              "kind":"opposite_direction|metric_conflict","detail":"..."}]}
模型随后逐对裁决写入 controversy_matrix.md。
仅标准库。
"""
import argparse, json, re, sys
from pathlib import Path


def load_theme_map(work):
    tm = work / "themes_map.json"
    if tm.exists():
        return json.loads(tm.read_text(encoding="utf-8"))
    # 从 themes.md 解析: 行内含主题编号与 D# 列表
    out = {}
    tp = work / "themes.md"
    if tp.exists():
        cur = None
        for line in tp.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*[-*]?\s*(T\d+)\b", line)
            if m:
                cur = m.group(1)
            ids = re.findall(r"\bD\d+\b", line)
            if cur and ids:
                out.setdefault(cur, []).extend(ids)
    return out


def num_of(v):
    if v is None:
        return None
    m = re.search(r"[-+]?\d+(\.\d+)?", str(v))
    return float(m.group(0)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    work = Path(a.work)
    claims = []
    cp = work / "claims.jsonl"
    if cp.exists():
        for line in cp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    claims.append(json.loads(line))
                except Exception:
                    continue
    theme_map = load_theme_map(work)
    theme_of = {}
    for t, ids in theme_map.items():
        for i in ids:
            theme_of[i] = t
    pairs, seen = [], set()
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            A, B = claims[i], claims[j]
            if A.get("doc_id") == B.get("doc_id"):
                continue
            ta = theme_of.get(A.get("doc_id"))
            tb = theme_of.get(B.get("doc_id"))
            if not ta or ta != tb:
                continue
            da, db = A.get("direction"), B.get("direction")
            kind = None
            if {da, db} == {"positive", "negative"}:
                kind = "opposite_direction"
            elif (A.get("metric") and A.get("metric") == B.get("metric")
                  and num_of(A.get("value")) is not None and num_of(B.get("value")) is not None
                  and num_of(A.get("value")) * num_of(B.get("value")) < 0):
                kind = "metric_conflict"
            if kind:
                key = tuple(sorted([str(A.get("claim_id")), str(B.get("claim_id"))]))
                if key in seen:
                    continue
                seen.add(key)
                pairs.append({"pair_id": f"X{len(pairs)+1}",
                              "claim_a": A.get("claim_id"), "claim_b": B.get("claim_id"),
                              "theme": ta, "kind": kind,
                              "detail_a": str(A.get("statement"))[:120],
                              "detail_b": str(B.get("statement"))[:120]})
    out = {"pairs": pairs, "note": "候选冲突对; 由模型在 controversy_matrix.md 裁决为 explained 或 unresolved_conflict"}
    (work / "controversy_candidates.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"conflict_pairs": len(pairs)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

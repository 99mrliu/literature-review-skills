#!/usr/bin/env python3
"""gap_map.py — 从证据分布推导研究空白候选。

规则（每条空白必须可指回证据分布）:
  G1 单源主题: 主题仅 1 篇文献支撑 → coverage 空白;
  G2 未裁决冲突: 主题存在 unresolved_conflict 对 → 裁决证据缺口;
  G3 负面集中: 主题内 negative 论断数 >= positive 且 >=2 → 效果存疑空白;
  G4 维度缺失: 语料无任何文献覆盖研究问题方面(对象/场景/长期)时,
     仅当可从 task.md 或研究问题分解确认该维度被明确提出才生成。

输入: claims.jsonl, themes_map.json/themes.md, controversy_matrix.md(解析 unresolved 标记)。
输出 <work>/gap_candidates.json: {"gaps":[{"gap_id":"G1","theme":"T2","type":"single_source",
  "evidence":"仅 D5 支撑该主题", "statement_scaffold":"..."}]}
模型据此写 gaps.md。仅标准库。
"""
import argparse, json, re, sys
from collections import defaultdict
from pathlib import Path


def theme_map_of(work):
    tm = work / "themes_map.json"
    if tm.exists():
        return json.loads(tm.read_text(encoding="utf-8"))
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    work = Path(a.work)
    tmap = theme_map_of(work)
    claims = []
    cp = work / "claims.jsonl"
    if cp.exists():
        for line in cp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    claims.append(json.loads(line))
                except Exception:
                    continue
    by_theme = defaultdict(list)
    for c in claims:
        t = None
        for th, ids in tmap.items():
            if c.get("doc_id") in ids:
                t = th
                break
        by_theme[t or "misc"].append(c)

    unresolved = defaultdict(list)
    cm = work / "controversy_matrix.md"
    if cm.exists():
        cur = None
        for line in cm.read_text(encoding="utf-8").splitlines():
            m = re.search(r"\b(X\d+)\b", line)
            if m:
                cur = m.group(1)
            if cur and "unresolved" in line.lower():
                tm = re.search(r"\b(T\d+)\b", line)
                unresolved[tm.group(1) if tm else "?"].append(cur)

    gaps = []
    for t, ids in sorted(tmap.items()):
        cs = by_theme.get(t, [])
        docs = sorted(set(ids), key=lambda x: int(x[1:]))
        if len(docs) == 1:
            gaps.append({"gap_id": f"G{len(gaps)+1}", "theme": t, "type": "single_source",
                         "evidence": f"该主题仅 {docs[0]} 一篇支撑",
                         "statement_scaffold": "该方向的证据仅有单篇来源，缺乏独立复现"})
        if unresolved.get(t):
            gaps.append({"gap_id": f"G{len(gaps)+1}", "theme": t, "type": "unresolved_conflict",
                         "evidence": f"未裁决冲突对: {', '.join(unresolved[t])}",
                         "statement_scaffold": "文献间结论冲突且现有对象/条件差异无法解释，缺乏 head-to-head 比较"})
        pos = sum(1 for c in cs if c.get("direction") == "positive")
        neg = sum(1 for c in cs if c.get("direction") == "negative")
        if neg >= 2 and neg >= pos and len(docs) > 1:
            gaps.append({"gap_id": f"G{len(gaps)+1}", "theme": t, "type": "negative_dominant",
                         "evidence": f"negative {neg} 条 vs positive {pos} 条",
                         "statement_scaffold": "负面结果占多数，该方向的效果主张证据不足"})
    out = {"gaps": gaps,
           "note": "空白候选; statement 必须由模型按 gaps.md 规范具体化并绑定触发证据"}
    (work / "gap_candidates.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"gap_candidates": len(gaps)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

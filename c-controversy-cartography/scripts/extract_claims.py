#!/usr/bin/env python3
"""extract_claims.py — 候选论断句抽取。

从 <work>/pages/<doc_id>.jsonl 抽取含结果谓词或数值的句子,
带 p<页>.¶<段> 定位, 写 <work>/claims_candidates.jsonl:
  {"doc_id":..., "anchor":"p3.¶2", "sentence":"...", "has_number":true, "cues":[...]}

句子切分: 按 .!?。！？ 断句; 段内编号。仅作模型阅读索引与裁定输入,
候选不等于论断。仅标准库。
"""
import argparse, json, re, sys
from pathlib import Path

CUES = [
    "improve", "improves", "improved", "improvement", "reduce", "reduces", "reduced",
    "reduction", "outperform", "outperforms", "outperformed", "significant", "significantly",
    "demonstrat", "show", "shows", "shown", "achieve", "achieved", "increase", "increased",
    "decrease", "decreased", "better", "worse", "superior", "inferior", "fail", "failed",
    "no effect", "did not", "do not", "not significant", "提升", "提高", "降低", "减少",
    "优于", "差于", "显著", "表明", "显示", "证实", "有效", "无效", "改善", "下降", "增长",
    "失败", "未发现", "没有显著", "相当", "媲美",
]
NUM_RE = re.compile(r"\d+(\.\d+)?\s*(%|percent|points?|pp|倍|个)?", re.I)
SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")


def split_paras(page_text):
    chunks = re.split(r"\n\s*\n", page_text)
    return [re.sub(r"\s+", " ", c).strip() for c in chunks if len(c.strip()) > 40]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    work = Path(a.work)
    docs_p = work / "docs.jsonl"
    if not docs_p.exists():
        print(json.dumps({"error": "docs.jsonl missing"}, ensure_ascii=False))
        return 1
    out = []
    for line in docs_p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("status") != "ok":
            continue
        pgf = work / "pages" / (d["doc_id"] + ".jsonl")
        if not pgf.exists():
            continue
        for ln in pgf.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            pg = json.loads(ln)
            for j, para in enumerate(split_paras(pg["text"]), 1):
                for sent in SENT_SPLIT.split(para):
                    s = sent.strip()
                    if len(s) < 20 or len(s) > 600:
                        continue
                    sl = s.lower()
                    cues = [c for c in CUES if c in sl]
                    has_num = bool(NUM_RE.search(s))
                    if cues or has_num:
                        out.append({"doc_id": d["doc_id"],
                                    "anchor": f"p{pg['page']}.¶{j}",
                                    "sentence": s[:500],
                                    "has_number": has_num, "cues": cues[:5]})
    with open(work / "claims_candidates.jsonl", "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"claim_candidates": len(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

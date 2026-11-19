#!/usr/bin/env python3
"""cluster_themes.py — 文档词项向量连通聚类，产出主题脚手架。

对每个 status=ok 的文档: 分词(英文小写词干前缀5字符 + 中文二字组),
去停用词, 得词频向量; 文档对余弦相似度 >= 0.25 连边; 连通分量为主题候选。
写 <work>/theme_scaffold.json:
  {"themes": [{"theme_id":"T1","doc_ids":[...],"top_terms":[...],"size":k}], "unclustered":[...],
   "threshold": 0.25, "note": "脚手架; 语义命名与拆分/合并由模型在 themes.md 完成"}

仅标准库。
"""
import argparse, json, math, re, sys
from collections import Counter
from pathlib import Path

STOP = set(("the a an of to in on for and or with by is are was were be been this that these those "
            "we our us it its as at from into not no can could may might will would shall should "
            "have has had do does did than then thus such more most other also between using use used "
            "based their they them he she his her which while where when who whom what how all each both "
            "study paper results result method methods approach approaches however therefore here there "
            "本文 我们 他们 以及 其中 对于 通过 进行 基于 结果 方法 研究 实验 表明 使用 一个 这种 可以 本文中").split())


def tokens(text):
    out = []
    for w in re.findall(r"[a-z][a-z0-9-]+", text.lower()):
        w = w.strip("-")
        if len(w) >= 3 and w not in STOP:
            out.append(w[:5])
    for w in re.findall(r"[一-鿿]{2}", text):
        if w not in STOP:
            out.append(w)
    return out


def tf(text):
    return Counter(tokens(text))


def cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--threshold", type=float, default=0.25)
    a = ap.parse_args()
    work = Path(a.work)
    docs = []
    for line in (work / "docs.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            if d.get("status") == "ok":
                docs.append(d)
    vecs = {}
    for d in docs:
        pgf = work / "pages" / (d["doc_id"] + ".jsonl")
        text = ""
        if pgf.exists():
            text = "\n".join(json.loads(l).get("text", "") for l in
                             pgf.read_text(encoding="utf-8").splitlines() if l.strip())
        vecs[d["doc_id"]] = tf(text)

    parent = {d["doc_id"]: d["doc_id"] for d in docs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ids = list(vecs)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if cosine(vecs[ids[i]], vecs[ids[j]]) >= a.threshold:
                parent[find(ids[i])] = find(ids[j])
    clusters = {}
    for i in ids:
        clusters.setdefault(find(i), []).append(i)
    order = sorted(clusters.values(), key=lambda v: (-len(v), v[0]))

    themes = []
    for n, members in enumerate(order, 1):
        agg = Counter()
        for m in members:
            agg.update(vecs[m])
        themes.append({"theme_id": f"T{n}",
                       "doc_ids": sorted(members, key=lambda x: int(x[1:])),
                       "top_terms": [t for t, _ in agg.most_common(12)],
                       "size": len(members)})
    scaffold = {"themes": themes, "unclustered": [], "threshold": a.threshold,
                "note": "聚类脚手架。模型须检查语义一致性, 必要时在 themes.md 拆分/合并并重命名; 每篇文档最终必须归属且仅归属一个主题(或 misc)。"}
    (work / "theme_scaffold.json").write_text(json.dumps(scaffold, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"themes": len(themes), "sizes": [t["size"] for t in themes]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

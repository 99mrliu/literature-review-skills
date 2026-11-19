#!/usr/bin/env python3
"""dedup.py — 标题归一化 + 重复分组。

读取 <work>/docs.jsonl, 按 (1) 归一化标题全哈希 (2) 前 40 字符前缀哈希
产生疑似重复分组, 写 <work>/dup_groups.json:
  [{"group": 1, "doc_ids": ["D2","D5"], "titles": [...], "basis": "exact|prefix"}]
并把 group 编号回写 <work>/docs.jsonl 的 dup_group 字段。
重复判定只是"疑似": 最终是否算重复由筛选日志的 duplicate_of 决定显式给出。
仅标准库。
"""
import argparse, hashlib, json, re, sys
from pathlib import Path


def norm(t):
    t = re.sub(r"[^a-z0-9一-鿿]+", " ", (t or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    work = Path(a.work)
    docs = []
    p = work / "docs.jsonl"
    if not p.exists():
        print(json.dumps({"error": "docs.jsonl missing"}, ensure_ascii=False))
        return 1
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            docs.append(json.loads(line))

    def title_of(d):
        if d.get("title"):
            return d["title"]
        mt = (d.get("meta") or {}).get("title")
        if mt:
            return mt
        # 回退: 用第 1 页首行非空文本作为题名字符串
        pp = work / "pages" / (d["doc_id"] + ".jsonl")
        if pp.exists():
            try:
                first = json.loads(pp.read_text(encoding="utf-8").splitlines()[0])
                head = " ".join(first.get("text", "").split())[:150]
                if head:
                    return head
            except Exception:
                pass
        return Path(d["path"]).stem if d.get("path") else d["doc_id"]

    exact, prefix = {}, {}
    for d in docs:
        n = norm(title_of(d))
        if not n:
            continue
        exact.setdefault(hashlib.sha1(n.encode()).hexdigest(), []).append(d["doc_id"])
        prefix.setdefault(hashlib.sha1(n[:40].encode()).hexdigest(), []).append(d["doc_id"])

    # 词集合 Jaccard >= 0.6 的疑似同研究标题（语料 <= 200 篇时成对比较）
    jac_groups = []
    if len(docs) <= 200:
        toks = {d["doc_id"]: set(norm(title_of(d)).split()) for d in docs}
        parent = {d["doc_id"]: d["doc_id"] for d in docs}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        ids = list(toks)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = toks[ids[i]], toks[ids[j]]
                if not a or not b:
                    continue
                inter = len(a & b)
                union = len(a | b)
                contain = inter / max(1, min(len(a), len(b)))
                if inter >= 4 and (inter / union >= 0.6 or contain >= 0.7):
                    parent[find(ids[i])] = find(ids[j])
        clusters = {}
        for i in ids:
            clusters.setdefault(find(i), []).append(i)
        jac_groups = [sorted(v, key=lambda x: int(x[1:])) for v in clusters.values() if len(v) > 1]

    groups, seen = [], set()
    gi = 0
    for basis, table in (("exact", exact), ("prefix", prefix)):
        for h, ids in table.items():
            key = tuple(sorted(ids))
            if len(ids) > 1 and key not in seen:
                seen.add(key)
                gi += 1
                groups.append({"group": gi, "doc_ids": sorted(ids, key=lambda x: int(x[1:])),
                               "titles": [title_of(next(d for d in docs if d["doc_id"] == i))[:80] for i in ids],
                               "basis": basis})
    for ids in jac_groups:
        key = tuple(sorted(ids))
        if key not in seen:
            seen.add(key)
            gi += 1
            groups.append({"group": gi, "doc_ids": ids,
                           "titles": [title_of(next(d for d in docs if d["doc_id"] == i))[:80] for i in ids],
                           "basis": "jaccard>=0.6"})
    gmap = {}
    for g in groups:
        for i in g["doc_ids"]:
            gmap[i] = g["group"]
    for d in docs:
        d["dup_group"] = gmap.get(d["doc_id"])
    with open(work / "docs.jsonl", "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    (work / "dup_groups.json").write_text(json.dumps(groups, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"dup_groups": len(groups), "docs_in_groups": len(gmap)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

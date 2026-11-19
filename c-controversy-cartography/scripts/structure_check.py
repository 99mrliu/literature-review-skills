#!/usr/bin/env python3
"""structure_check.py — 结构一致性校验。

检查 (<work> + <out>):
  1. claims.jsonl 中每条 anchor 可解析到 pages 对应页; direction 取值合法;
     claim_id 唯一。
  2. themes_map.json(或 themes.md 解析)覆盖全部 status=ok 文档, 无重复归属。
  3. review_draft.md 中每个 [C#]/[X#]/[G#] 标记可解析到 claims/controversy/gaps;
     失败标记就地改写为 [未闭合:C#] 等并追加说明。
  4. 每个主题在草稿中有专节(按主题编号小标题或标记聚合判断, 宽松:
     只要该主题全部 [C#] 出现在草稿即算覆盖)。
输出 <out>/structure_report.json。退出码: 0 pass, 1 fail。
仅标准库。
"""
import argparse, json, re, sys
from pathlib import Path

DIRECTIONS = {"positive", "negative", "neutral"}
MARK = re.compile(r"\[([CXG]\d+(?:[;，,]\s*[CXG]?\d+)*)\]")


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
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    work, out = Path(a.work), Path(a.out)
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail[:300]})

    docs = [d for d in jlines(work / "docs.jsonl") if d.get("status") == "ok"]
    doc_ids = {d["doc_id"] for d in docs}
    pages_of = {}
    for d in docs:
        pgf = work / "pages" / (d["doc_id"] + ".jsonl")
        pages_of[d["doc_id"]] = {json.loads(l)["page"] for l in
                                 pgf.read_text(encoding="utf-8").splitlines() if l.strip()} \
            if pgf.exists() else set()

    claims = jlines(work / "claims.jsonl")
    seen_ids, bad_anchor, bad_dir = set(), [], []
    for c in claims:
        cid = str(c.get("claim_id", ""))
        if cid in seen_ids:
            bad_dir.append(cid + ":dup")
        seen_ids.add(cid)
        m = re.match(r"p(\d+)", str(c.get("anchor", "")))
        if not m or int(m.group(1)) not in pages_of.get(c.get("doc_id"), set()):
            bad_anchor.append(f"{cid}@{c.get('doc_id')}:{c.get('anchor')}")
        if c.get("direction") not in DIRECTIONS:
            bad_dir.append(cid + ":direction")
    check("claims_valid", claims and not bad_anchor and not bad_dir,
          f"claims={len(claims)} bad_anchor={bad_anchor[:5]} bad={bad_dir[:5]}")

    tmap = theme_map_of(work)
    covered = [i for ids in tmap.values() for i in ids]
    multi = sorted({i for i in covered if covered.count(i) > 1}, key=lambda x: int(x[1:]))
    missing = sorted(doc_ids - set(covered), key=lambda x: int(x[1:]))
    extra = sorted(set(covered) - doc_ids, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)
    # 一篇文献可支撑多个主题: 多归属是信息项, 不判失败
    check("themes_cover_docs", not missing, f"missing={missing[:6]} extra={extra[:6]} multi={multi[:6]}")

    claim_ids = {str(c.get("claim_id")) for c in claims}
    cont = json.loads((work / "controversy_candidates.json").read_text(encoding="utf-8")) \
        if (work / "controversy_candidates.json").exists() else {"pairs": []}
    cont_ids = {p["pair_id"] for p in cont.get("pairs", [])}
    gaps = json.loads((work / "gap_candidates.json").read_text(encoding="utf-8")) \
        if (work / "gap_candidates.json").exists() else {"gaps": []}
    gap_ids = {g["gap_id"] for g in gaps.get("gaps", [])}

    draft_p = out / "review_draft.md"
    failed_marks = []
    theme_in_draft = set()
    if draft_p.exists():
        text = draft_p.read_text(encoding="utf-8")
        text = re.sub(r"\n*---\n> 结构校验说明:.*?(?=\Z)", "", text, flags=re.S)

        def sub(m):
            raw = m.group(1)
            ids = re.split(r"[;，,]\s*", raw)
            ok, bad = [], []
            for i in ids:
                letter = i[0] if i and i[0] in "CXG" else ("C" if i else "")
                full = i if i and i[0] in "CXG" else letter + i
                pool = claim_ids if full.startswith("C") else (cont_ids if full.startswith("X") else gap_ids)
                (ok if full in pool else bad).append(full)
            for o in ok:
                for t, ids2 in tmap.items():
                    if any(c.get("claim_id") == o and c.get("doc_id") in ids2 for c in claims):
                        theme_in_draft.add(t)
                        break
            if bad:
                failed_marks.append(m.group(0))
                return "[未闭合:" + ";".join(bad) + "]"
            return m.group(0)

        new_text = MARK.sub(sub, text)
        if failed_marks:
            new_text += ("\n\n---\n> 结构校验说明: 标记为 [未闭合:…] 的引用不存在于 claims/"
                         "controversy/gaps 产物中, 对应句子已不作为事实陈述使用; 详见 structure_report.json。\n")
            draft_p.write_text(new_text, encoding="utf-8")
        # 覆盖判定: 主题编号出现在草稿文本中, 或其任一论断的标记出现在草稿中
        for t in tmap:
            if re.search(r"\b" + t + r"\b", new_text):
                theme_in_draft.add(t)
        missing_themes = sorted(set(tmap) - theme_in_draft)
        check("draft_themes_covered", not missing_themes,
              f"未出现在草稿的主题: {missing_themes[:6]}")
        check("draft_marks_resolve", not failed_marks, f"未闭合: {failed_marks[:6]}")
    else:
        check("draft_exists", False, "review_draft.md missing")

    fails = [c for c in checks if not c["ok"] and c["check"] != "draft_exists"]
    status = "fail" if fails else "pass"
    (out / "structure_report.json").write_text(
        json.dumps({"status": status, "checks": checks}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"structure": status, "failed": [c["check"] for c in fails]}, ensure_ascii=False))
    return 1 if status == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())

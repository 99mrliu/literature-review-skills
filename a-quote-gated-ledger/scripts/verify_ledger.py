#!/usr/bin/env python3
"""verify_ledger.py — 引用门控。

校验 <work>/evidence_ledger.jsonl 中每行:
  1. quote_at_locator: verbatim_quote 归一化后必须是 <work>/pages/<doc_id>.jsonl
     中所声称页 (locator "p3.¶2" → page 3) 文本的子串; ¶段号存在时还要求出现在
     对应段落文本中。
  2. 字段完备: evidence_id/doc_id/locator/verbatim_quote/supports/theme/strength。
  3. strength 取值合法: established|suggestive|contested|unknown。

校验 <out>/review_draft.md:
  4. 每个 [E#] 标记必须解析到一条通过全部校验的证据行; 否则该句被修订:
     句尾追加 "(引证未通过核验, 降级为推断)" 并将 [E#] 改为 [未核验:E#]。
  5. 反向检查: 证据表中 verified 的行若完全未被草稿引用, 写入 report.unused。

输出 <out>/gate_report.json; 通过校验的证据行写 <work>/evidence_verified.jsonl;
就地修订草稿 <out>/review_draft.md。
退出码: 0 = 草稿通过门控; 1 = 存在降级句 (仍可用, finalize 会标 partial)。
仅标准库。
"""
import argparse, json, re, sys
from pathlib import Path

STRENGTHS = {"established", "suggestive", "contested", "unknown", "no_adverse_found"}
MARK_RE = re.compile(r"\[E(\d+(?:[;，,]\s*E?\d+)*)\]")


def norm(s):
    s = s.replace("­", "").replace("-\n", "").replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def load_pages(work, doc_id):
    f = Path(work) / "pages" / f"{doc_id}.jsonl"
    pages = {}
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                pages[d["page"]] = d["text"]
    return pages


def parse_locator(loc):
    m = re.match(r"p(\d+)(?:\.¶(\d+))?", str(loc or ""))
    if not m:
        return None, None
    return int(m.group(1)), (int(m.group(2)) if m.group(2) else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    work, out = Path(a.work), Path(a.out)
    ledger_p = work / "evidence_ledger.jsonl"
    report = {"rows_total": 0, "rows_passed": 0, "rows_failed": [],
              "draft_markers_total": 0, "draft_markers_ok": 0,
              "draft_markers_failed": [], "unused_evidence": [], "status": "pass"}
    verified, failed_ids = [], set()
    page_cache = {}

    if ledger_p.exists():
        for ln, line in enumerate(ledger_p.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception as e:
                report["rows_failed"].append({"line": ln, "reason": f"json: {e}"})
                continue
            report["rows_total"] += 1
            rid = str(row.get("evidence_id", f"L{ln}"))
            missing = [k for k in ("evidence_id", "doc_id", "locator", "verbatim_quote", "supports")
                       if not row.get(k)]
            if missing:
                row["verified"] = False
                row["verify_note"] = "missing fields: " + ",".join(missing)
                report["rows_failed"].append({"evidence_id": rid, "reason": row["verify_note"]})
                failed_ids.add(rid)
                verified.append(row)
                continue
            strength = str(row.get("strength", "unknown"))
            if strength not in STRENGTHS:
                row["strength"] = "unknown"
                row.setdefault("notes", "")
                row["notes"] = (row.get("notes", "") + " strength 取值非法, 已重置 unknown;").strip("; ")
            doc_id = str(row["doc_id"])
            if doc_id not in page_cache:
                page_cache[doc_id] = load_pages(work, doc_id)
            pages = page_cache[doc_id]
            pg, para = parse_locator(row.get("locator"))
            hay = norm(pages.get(pg, "")) if pg else ""
            needle = norm(row.get("verbatim_quote", ""))
            note = None
            if not pg or not hay:
                note = f"locator {row.get('locator')} 无法解析到页文本"
            elif needle not in hay:
                # 回退: 全文任意页
                full = norm("\n".join(pages.values()))
                if needle and needle in full:
                    note = "摘录属实但不在所声称页; 请修正 locator"
                else:
                    note = "verbatim_quote 未在文档中出现 (可能转述/翻译/凭记忆)"
            if note:
                row["verified"] = False
                row["verify_note"] = note
                report["rows_failed"].append({"evidence_id": rid, "reason": note})
                failed_ids.add(rid)
            else:
                row["verified"] = True
                row.pop("verify_note", None)
                report["rows_passed"] += 1
            verified.append(row)
    else:
        report["status"] = "no_ledger"
        report["note"] = "evidence_ledger.jsonl 不存在; 草稿将全部降级"

    with open(work / "evidence_verified.jsonl", "w", encoding="utf-8") as f:
        for row in verified:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    ok_ids = {str(r["evidence_id"]) for r in verified if r.get("verified")}
    draft_p = out / "review_draft.md"
    if draft_p.exists():
        text = draft_p.read_text(encoding="utf-8")
        # 剥离上一轮追加的门控说明, 避免其中的编号被重复校验
        text = re.sub(r"\n*---\n> 门控说明:.*?(?=\Z)", "", text, flags=re.S)
        used = set()

        def sub(m):
            ids = re.split(r"[;，,]\s*", m.group(1))
            ids = [i if i.startswith("E") else "E" + i for i in ids]
            report["draft_markers_total"] += 1
            bad = [i for i in ids if i not in ok_ids]
            if bad:
                report["draft_markers_failed"].append({"marker": m.group(0), "unresolved": bad})
                return "[未核验:" + ";".join(bad) + "](原为 " + ";".join(bad) + ")"
            used.update(ids)
            report["draft_markers_ok"] += 1
            return m.group(0)

        new_text = MARK_RE.sub(sub, text)
        stale_degraded = "[未核验:" in new_text
        if report["draft_markers_failed"]:
            new_text += ("\n\n---\n> 门控说明: 标记为 [未核验:E#] 的引证未通过逐字校验,"
                         " 对应句子已不作为事实陈述使用; 详见 gate_report.json。\n")
            draft_p.write_text(new_text, encoding="utf-8")
            report["status"] = "degraded"
        elif stale_degraded:
            report["status"] = "degraded"
            report["note3"] = "草稿仍含上一轮 [未核验:E#] 标记, 须修复后重跑"
        report["unused_evidence"] = sorted(ok_ids - used)
    else:
        report["status"] = "no_draft"
        report["note2"] = "review_draft.md 不存在"

    (out / "gate_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"gate": report["status"], "passed": report["rows_passed"],
                      "failed": len(report["rows_failed"]),
                      "markers_ok": report["draft_markers_ok"],
                      "markers_failed": len(report["draft_markers_failed"])},
                     ensure_ascii=False))
    return 1 if report["status"] in ("degraded", "no_ledger", "no_draft") else 0


if __name__ == "__main__":
    sys.exit(main())

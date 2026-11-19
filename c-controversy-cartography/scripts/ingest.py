#!/usr/bin/env python3
"""ingest.py — controversy-gap-cartography 阶段0: 防御式解析 + 材料发现 + 文本抽取。

产出 (<work>): case_meta.json, case_echo.json, task_echo.md, docs.jsonl,
pages/<doc_id>.jsonl, extract_meta.json。
抽取: pdftotext -layout → pypdf → 纯文本。分级: fulltext(>=300词)/abstract_only/failed。
仅标准库。
"""
import argparse, hashlib, json, re, shutil, subprocess, sys
from pathlib import Path

ID_KEYS = ["case_id", "caseId", "id", "cid"]
RQ_KEYS = ["research_question", "question", "topic", "title", "objective", "rq", "problem"]
DOC_KEYS = ["documents", "papers", "references", "files", "literature", "corpus", "materials", "records"]
PATH_KEYS = ["path", "file", "pdf", "filename", "filepath", "document", "local_path"]
TITLE_KEYS = ["title", "name", "paper_title"]
CONTRACT_KEYS = ["output_contract", "contract", "output_fields", "required_fields"]


def deep_find(obj, keys, path=""):
    low = {k.lower() for k in keys}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in low:
                return k, v, f"{path}.{k}" if path else k
        for k, v in obj.items():
            r = deep_find(v, keys, f"{path}.{k}" if path else str(k))
            if r:
                return r
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            r = deep_find(v, keys, f"{path}[{i}]")
            if r:
                return r
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--task", default="/input/task.md")
    ap.add_argument("--input-dir", default="/input")
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    work = Path(a.work)
    (work / "pages").mkdir(parents=True, exist_ok=True)

    case_p = Path(a.case)
    case_err = None
    if not case_p.exists():
        cands = sorted(case_p.parent.glob("*.json")) if case_p.parent.exists() else []
        case_p = cands[0] if cands else case_p
        if not case_p.exists():
            case, case_err = {}, "case.json not found"
    if case_err is None:
        try:
            case = json.loads(case_p.read_text(encoding="utf-8"))
        except Exception as e:
            case, case_err = {}, f"case.json parse failed: {e}"
    (work / "case_echo.json").write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")
    task_p = Path(a.task)
    (work / "task_echo.md").write_text(
        task_p.read_text(encoding="utf-8", errors="replace") if task_p.exists() else "", encoding="utf-8")

    case_id = None
    r = deep_find(case, ID_KEYS)
    if r:
        case_id = str(r[1])
    if not case_id:
        case_id = case_p.stem
    rq = None
    r = deep_find(case, RQ_KEYS)
    if r and isinstance(r[1], (str, int, float)):
        rq = str(r[1])
    contract = None
    for ck in CONTRACT_KEYS:
        r = deep_find(case, [ck])
        if r:
            contract = r[1]
            break
    (work / "case_meta.json").write_text(json.dumps(
        {"case_id": case_id, "research_question": rq, "output_contract": contract,
         "case_error": case_err, "case_path": str(case_p)}, ensure_ascii=False, indent=1), encoding="utf-8")

    in_dir = Path(a.input_dir)
    docs, r = [], deep_find(case, DOC_KEYS)
    entries = r[1] if r and isinstance(r[1], list) else (list(r[1].values()) if r and isinstance(r[1], dict) else [])
    for i, e in enumerate(entries):
        path_val, title, extra = None, None, {}
        if isinstance(e, str):
            path_val = e
        elif isinstance(e, dict):
            for pk in PATH_KEYS:
                if e.get(pk):
                    path_val = e[pk]
                    break
            for tk in TITLE_KEYS:
                if e.get(tk):
                    title = str(e[tk])
                    break
            extra = {k: v for k, v in e.items() if isinstance(v, (str, int, float, bool))}
        if path_val or title:
            docs.append({"entry_idx": i, "path": path_val, "title": title, "meta": extra})
    known = {d["path"] for d in docs if d["path"]}
    exts = [".pdf", ".txt", ".md", ".html", ".htm"]
    if in_dir.exists():
        for p in sorted(in_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in exts and str(p) not in known \
               and p.name not in ("case.json", "task.md"):
                docs.append({"entry_idx": None, "path": str(p), "title": None, "meta": {}})

    def extract_pdf(p):
        pt = shutil.which("pdftotext")
        if pt:
            try:
                rr = subprocess.run([pt, "-layout", str(p), "-"], capture_output=True, text=True, timeout=300)
                if rr.returncode == 0 and rr.stdout.strip():
                    return rr.stdout.split("\f"), "pdftotext", None
            except Exception:
                pass
        try:
            import pypdf
            reader = pypdf.PdfReader(str(p))
            pages = [(pg.extract_text() or "") for pg in reader.pages]
            if any(x.strip() for x in pages):
                return pages, "pypdf", None
            return pages, "pypdf_empty", "no extractable text (scanned?)"
        except ImportError:
            return [], "none", "pdftotext unavailable, pypdf missing"
        except Exception as e:
            return [], "pypdf_error", str(e)

    recs, fails = [], []
    for i, d in enumerate(docs):
        doc_id = f"D{i+1}"
        rec = {"doc_id": doc_id, "path": d["path"], "title": d["title"], "meta": d["meta"],
               "sha256": None, "words": 0, "tier": "missing", "extract_method": None,
               "pages": 0, "status": "ok"}
        p = Path(d["path"]) if d["path"] else None
        if p is None or not p.exists():
            cand = None
            if d["title"] and in_dir.exists():
                tl = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9一-鿿]+", " ", d["title"].lower())).strip()[:40]
                for q in sorted(in_dir.rglob("*")):
                    if q.is_file() and q.suffix.lower() in exts and tl and tl in \
                       re.sub(r"\s+", " ", re.sub(r"[^a-z0-9一-鿿]+", " ", q.stem.lower())):
                        cand = q
                        break
            if cand is None and in_dir.exists():
                rest = sorted(in_dir.rglob("*.pdf"))
                cand = rest[0] if len(rest) == 1 else None
            if cand is None:
                rec["status"] = "metadata_only" if (d["path"] or "").startswith(("http",)) else "missing"
                rec["tier"] = "failed"
                recs.append(rec)
                fails.append({"doc_id": doc_id, "reason": "file not found: %s" % d["path"]})
                continue
            p = cand
            rec["path"] = str(p)
        rec["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
        if p.suffix.lower() == ".pdf":
            pages, method, err = extract_pdf(p)
        else:
            try:
                pages, method = [p.read_text(encoding="utf-8", errors="replace")], "text"
                err = None
            except Exception as e:
                pages, method, err = [], "text_error", str(e)
        if not pages or not any(x.strip() for x in pages):
            rec.update(tier="failed", extract_method=method or "none", status="failed")
            recs.append(rec)
            fails.append({"doc_id": doc_id, "reason": err or "empty text"})
            continue
        rec["extract_method"] = method
        rec["pages"] = len(pages)
        rec["words"] = len(re.findall(r"[A-Za-z0-9一-鿿]+", "\n".join(pages)))
        rec["tier"] = "fulltext" if rec["words"] >= 300 else "abstract_only"
        with open(work / "pages" / f"{doc_id}.jsonl", "w", encoding="utf-8") as f:
            for n, pg in enumerate(pages, 1):
                f.write(json.dumps({"page": n, "text": pg}, ensure_ascii=False) + "\n")
        recs.append(rec)

    with open(work / "docs.jsonl", "w", encoding="utf-8") as f:
        for rec in recs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    em = {"total": len(recs), "tiers": {}, "failures": fails,
          "note": "scanned pdf without text layer: use OCR if environment provides it"}
    for rec in recs:
        em["tiers"][rec["tier"]] = em["tiers"].get(rec["tier"], 0) + 1
    (work / "extract_meta.json").write_text(json.dumps(em, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"docs": len(recs), "tiers": em["tiers"], "failures": len(fails)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

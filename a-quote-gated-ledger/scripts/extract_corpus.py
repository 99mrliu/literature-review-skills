#!/usr/bin/env python3
"""extract_corpus.py — 阶段0: 防御式解析 + 文献发现 + 文本抽取 + 锚点化 + 去重检测。

产出 (<work> 下):
  case_echo.json        case.json 原样拷贝 + 解析到的关键字段
  task_echo.md          task.md 文本
  docs.jsonl            每文档一行 {doc_id,path,sha256,chars,tier,extract_method,status,...}
  pages/<doc_id>.jsonl  每页一行 {"page":n,"text":...}
  anchors/<doc_id>.json 锚点表 {"p3.¶2": {"page":3,"para":2,"text_head":...}, ...}
  dup_groups.json       近重复标题分组
  extract_meta.json     解析方式统计与失败清单

文本抽取顺序: pdftotext -layout → pypdf → 纯文本读取。
分级: fulltext(>=300词) / abstract_only / failed。
仅标准库。
"""
import argparse, hashlib, json, re, shutil, subprocess, sys
from pathlib import Path

ID_KEYS = ["case_id", "caseId", "id", "cid"]
RQ_KEYS = ["research_question", "question", "topic", "title", "objective", "rq", "problem", "researchQuestion"]
DOC_KEYS = ["documents", "papers", "references", "files", "literature", "corpus", "materials", "records", "sources"]
PATH_KEYS = ["path", "file", "pdf", "filename", "filepath", "document", "local_path"]
TITLE_KEYS = ["title", "name", "paper_title"]
CONTRACT_KEYS = ["output_contract", "contract", "output_fields", "required_fields", "outputs"]


def deep_find(obj, keys, path=""):
    """递归查找第一个命中的 (key, value, path)。key 大小写不敏感。"""
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


def read_case(case_path):
    p = Path(case_path)
    if not p.exists():
        # 同目录任何 json
        cands = sorted(p.parent.glob("*.json")) if p.parent.exists() else []
        if cands:
            p = cands[0]
        else:
            return {}, "case.json not found", None
    try:
        return json.loads(p.read_text(encoding="utf-8")), None, p
    except Exception as e:
        return {}, f"case.json parse failed: {e}", p


def extract_pdf_pages(path):
    """返回 (pages[list of str], method, err)。pages 可能为空 list。"""
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        try:
            r = subprocess.run([pdftotext, "-layout", str(path), "-"],
                               capture_output=True, text=True, timeout=300)
            if r.returncode == 0 and r.stdout.strip():
                pages = r.stdout.split("\f")
                return [p for p in pages], "pdftotext", None
        except Exception:
            pass
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        pages = [(pg.extract_text() or "") for pg in reader.pages]
        if any(p.strip() for p in pages):
            return pages, "pypdf", None
        return pages, "pypdf_empty", "no extractable text (scanned pdf?)"
    except ImportError:
        return [], "none", "pypdf not installed and pdftotext unavailable/empty"
    except Exception as e:
        return [], "pypdf_error", str(e)


def split_paras(page_text):
    """把一页文本切成段: 空行分隔。"""
    chunks = re.split(r"\n\s*\n", page_text)
    return [re.sub(r"\s+", " ", c).strip() for c in chunks if len(c.strip()) > 40]


def norm_title(t):
    t = re.sub(r"[^a-z0-9一-鿿]+", " ", (t or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def title_hash(t):
    n = norm_title(t)
    return hashlib.sha1(n.encode("utf-8")).hexdigest()[:12]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--task", default="/input/task.md")
    ap.add_argument("--input-dir", default="/input")
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    work = Path(a.work)
    (work / "pages").mkdir(parents=True, exist_ok=True)
    (work / "anchors").mkdir(parents=True, exist_ok=True)
    (work / "digests").mkdir(parents=True, exist_ok=True)

    case, case_err, case_path = read_case(a.case)
    (work / "case_echo.json").write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")
    task_p = Path(a.task)
    task_text = task_p.read_text(encoding="utf-8", errors="replace") if task_p.exists() else ""
    (work / "task_echo.md").write_text(task_text, encoding="utf-8")

    case_id = None
    r = deep_find(case, ID_KEYS)
    if r:
        case_id = str(r[1])
    if not case_id and case_path:
        case_id = case_path.stem
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
    meta = {"case_id": case_id, "research_question": rq, "output_contract": contract,
            "case_error": case_err, "case_path": str(case_path) if case_path else None}
    (work / "case_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    # 文献发现
    in_dir = Path(a.input_dir)
    docs = []
    r = deep_find(case, DOC_KEYS)
    entries = []
    if r and isinstance(r[1], list):
        entries = r[1]
    elif r and isinstance(r[1], dict):
        entries = list(r[1].values())
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
        if path_val is None and title is None:
            continue
        docs.append({"entry_idx": i, "path": path_val, "title": title, "meta": extra})
    # 补充: input-dir 下未列出的材料文件
    known = {d["path"] for d in docs if d["path"]}
    exts = [".pdf", ".txt", ".md", ".html", ".htm"]
    if in_dir.exists():
        for p in sorted(in_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in exts:
                rel = str(p)
                if rel not in known and p.name not in ("case.json", "task.md"):
                    docs.append({"entry_idx": None, "path": rel, "title": None, "meta": {}})

    docs_out, fails, dup_groups, seen_hash = [], [], {}, {}
    for i, d in enumerate(docs):
        doc_id = f"D{i+1}"
        rec = {"doc_id": doc_id, "path": d["path"], "title": d["title"],
               "meta": d["meta"], "sha256": None, "chars": 0,
               "words": 0, "tier": "missing", "extract_method": None,
               "pages": 0, "status": "ok", "dup_of": None}
        p = Path(d["path"]) if d["path"] else None
        if p is None or not p.exists():
            cand = None
            if d["title"] and in_dir.exists():
                tl = norm_title(d["title"])[:40]
                for q in sorted(in_dir.rglob("*")):
                    if q.is_file() and q.suffix.lower() in exts and tl and tl in norm_title(q.stem):
                        cand = q
                        break
            if cand is None and in_dir.exists():
                rest = [q for q in sorted(in_dir.rglob("*.pdf"))]
                if len(rest) == 1:
                    cand = rest[0]
            if cand is None:
                rec["status"] = "missing"
                if d["path"] and str(d["path"]).startswith(("http://", "https://")):
                    rec["status"] = "metadata_only"
                rec["tier"] = "failed"
                docs_out.append(rec)
                fails.append({"doc_id": doc_id, "reason": "file not found: %s" % d["path"]})
                continue
            p = cand
            rec["path"] = str(p)
        rec["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
        suffix = p.suffix.lower()
        pages, method, err = None, None, None
        if suffix == ".pdf":
            pages, method, err = extract_pdf_pages(p)
        else:
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
                pages, method = [txt], "text"
            except Exception as e:
                pages, method, err = [], "text_error", str(e)
        if not pages or not any(pg.strip() for pg in pages):
            rec.update(tier="failed", extract_method=method or "none", status="failed")
            docs_out.append(rec)
            fails.append({"doc_id": doc_id, "reason": err or "empty text"})
            continue
        rec["extract_method"] = method
        rec["pages"] = len(pages)
        full = "\n".join(pages)
        rec["chars"] = len(full)
        rec["words"] = len(re.findall(r"[A-Za-z0-9一-鿿]+", full))
        rec["tier"] = "fulltext" if rec["words"] >= 300 else "abstract_only"
        # 落盘 pages 与 anchors
        with open(work / "pages" / f"{doc_id}.jsonl", "w", encoding="utf-8") as f:
            for n, pg in enumerate(pages, 1):
                f.write(json.dumps({"page": n, "text": pg}, ensure_ascii=False) + "\n")
        anchors = {}
        for n, pg in enumerate(pages, 1):
            for j, para in enumerate(split_paras(pg), 1):
                anchors[f"p{n}.¶{j}"] = {"page": n, "para": j, "text_head": para[:120]}
        (work / "anchors" / f"{doc_id}.json").write_text(
            json.dumps(anchors, ensure_ascii=False, indent=1), encoding="utf-8")
        # 去重检测
        t = d["title"] or (d["meta"].get("title") if isinstance(d["meta"], dict) else None) or p.stem
        h = title_hash(t)
        if h in seen_hash:
            rec["dup_of"] = seen_hash[h]
            dup_groups.setdefault(h, [seen_hash[h]]).append(doc_id)
        else:
            seen_hash[h] = doc_id
        docs_out.append(rec)

    with open(work / "docs.jsonl", "w", encoding="utf-8") as f:
        for rec in docs_out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (work / "dup_groups.json").write_text(
        json.dumps([g for g in dup_groups.values()], ensure_ascii=False, indent=1), encoding="utf-8")
    em = {"total": len(docs_out),
          "tiers": {},
          "methods": {},
          "failures": fails,
          "dup_groups": len(dup_groups),
          "note": "scanned pdf with no text layer: consider OCR tool if provided by environment"}
    for rec in docs_out:
        em["tiers"][rec["tier"]] = em["tiers"].get(rec["tier"], 0) + 1
        m = rec["extract_method"] or "none"
        em["methods"][m] = em["methods"].get(m, 0) + 1
    (work / "extract_meta.json").write_text(json.dumps(em, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"docs": len(docs_out), "tiers": em["tiers"], "failures": len(fails)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

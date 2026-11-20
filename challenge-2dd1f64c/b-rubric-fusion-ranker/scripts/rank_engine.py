#!/usr/bin/env python3
"""rubric-fusion-ranker :: rank_engine.py

Deterministic rubric-fusion ranking for literature candidate snapshots.
Standard library only. All arithmetic happens here; the model only writes
criteria_terms.json (a one-shot translation of the research question into
term lists) and spot-checks the verbatim evidence snippets.

Subcommands:

  score --work W --terms criteria_terms.json --rubric rubric.json --out W/scored.jsonl
      Scores every record on six signals (S1 topic, S2 population,
      S3 method, S4 evidence level, S5 recency, S6 metadata completeness),
      fuses them with rubric weights, and suggests a three-tier label.
      Every evidence snippet is re-verified as a verbatim substring of the
      record's title/abstract (or venue); a failed check zeroes the signal
      and raises a warning instead of crashing.

  sensitivity --work W --k 5 [--rubric rubric.json]
      One-factor +/-25% weight perturbation per signal, re-ranking under
      each perturbation. Writes W/sensitivity.json and
      W/sensitivity_report.md: top-k membership changes, max rank
      displacement, and a stable/unstable verdict per baseline top-k entry.

  assemble --work W --out O --k 5 [--rubric rubric.json]
      Final deterministic ranking with the documented tie protocol
      (total -> per-signal priority -> newer year -> record_id; residual
      exact ties are grouped and flagged, and a top-k boundary that cuts a
      tie group pulls the whole group in). Writes O/result.json and
      O/ranking_report.md, plus audit copies of the inputs.
"""
import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Default rubric (single source of truth; prepare.py dumps it to work dir)
# ---------------------------------------------------------------------------

DEFAULT_RUBRIC = {
    "version": "1.0",
    "description": "rubric-fusion-ranker 默认评分卡。权重脚本侧归一化；"
                   "阈值、平局协议、敏感性扰动幅度的语义见 references/rubric.md。",
    "signals": {
        "S1_topic": {
            "weight": 0.30,
            "title_weight": 0.7,
            "definition": "主题词命中：标题覆盖率权重高于摘要覆盖率"},
        "S2_population": {
            "weight": 0.20,
            "definition": "对象/人群词在标题+摘要中的覆盖率"},
        "S3_method": {
            "weight": 0.15,
            "definition": "方法/设计词在标题+摘要中的覆盖率"},
        "S4_evidence_level": {
            "weight": 0.15,
            "definition": "证据层级：摘要/标题设计关键词 + venue 预印本启发"},
        "S5_recency": {
            "weight": 0.10,
            "definition": "发表时间在时间窗内的新近度（线性衰减）"},
        "S6_metadata": {
            "weight": 0.10,
            "definition": "元数据完整度/来源质量（六字段加权占比）"},
    },
    "tie_break_order": ["S1_topic", "S2_population", "S3_method",
                        "S4_evidence_level", "S5_recency", "S6_metadata"],
    "thresholds": {"retained": 0.65, "pending": 0.40},
    "tie_epsilon": 1e-6,
    "recency_window_years": 10,
    "sensitivity_perturb_pct": 0.25,
}

SIGNAL_NAMES = list(DEFAULT_RUBRIC["signals"].keys())
SIGNAL_SHORT = {
    "S1_topic": "S1主题",
    "S2_population": "S2人群",
    "S3_method": "S3方法",
    "S4_evidence_level": "S4证据层级",
    "S5_recency": "S5时间",
    "S6_metadata": "S6元数据",
}

EVIDENCE_LEVELS = ["meta_analysis", "rct", "systematic_review", "cohort",
                   "case_control", "cross_sectional", "review", "preprint",
                   "unknown"]

LEVEL_PATTERNS = [
    ("meta_analysis", [r"meta[- ]analys", r"pooled analysis",
                       r"network meta[- ]analys"]),
    ("rct", [r"randomi[sz]ed controlled", r"randomi[sz]ed (clinical )?trial",
             r"\brct\b", r"double[- ]blind", r"placebo[- ]controlled",
             r"sham[- ]controlled", r"randomly assigned", r"randomi[sz]ed\b"]),
    ("systematic_review", [r"systematic (literature )?review", r"\bprisma\b"]),
    ("cohort", [r"\bcohort\b", r"prospective stud", r"longitudinal stud",
                r"follow[- ]up stud"]),
    ("case_control", [r"case[- ]control"]),
    ("cross_sectional", [r"cross[- ]sectional"]),
    ("review", [r"\b(scoping|narrative|literature|rapid|umbrella) review\b",
                r"\breview\b"]),
    ("preprint", [r"\bpreprint\b", r"not peer[- ]reviewed"]),
]

PREPRINT_VENUE_HINTS = ["arxiv", "biorxiv", "medrxiv", "chemrxiv", "ssrn",
                        "preprints.org", "research square", "preprint"]

S6_FIELD_WEIGHTS = {"title": 0.25, "abstract": 0.30, "year": 0.15,
                    "authors": 0.10, "venue": 0.10, "doi": 0.10}

LABELS = ("retained", "pending", "excluded")

# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


def load_json(path, default=None, fatal=False):
    if not os.path.exists(path):
        if fatal:
            raise SystemExit("FATAL: required file missing: %s" % path)
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise SystemExit("FATAL: invalid JSON in %s: %s" % (path, e))


def load_jsonl(path, fatal=False):
    if not os.path.exists(path):
        if fatal:
            raise SystemExit("FATAL: required file missing: %s" % path)
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise SystemExit("FATAL: %s:%d invalid JSON: %s"
                                 % (path, ln, e))
    return rows


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)


def resolve_rubric(args):
    path = getattr(args, "rubric", None)
    if not path:
        cand = os.path.join(args.work, "rubric.json")
        path = cand if os.path.exists(cand) else None
    rubric = load_json(path, default=None) if path else None
    if not isinstance(rubric, dict):
        return dict(DEFAULT_RUBRIC), "built-in defaults"
    merged = dict(DEFAULT_RUBRIC)
    merged.update({k: v for k, v in rubric.items() if k != "signals"})
    sig = dict(DEFAULT_RUBRIC["signals"])
    for name, spec in (rubric.get("signals") or {}).items():
        if name in sig and isinstance(spec, dict):
            s = dict(sig[name])
            s.update(spec)
            sig[name] = s
    merged["signals"] = sig
    return merged, (path or "built-in defaults")


# ---------------------------------------------------------------------------
# Term matching (evidence snippets are always verbatim slices of the source)
# ---------------------------------------------------------------------------


def find_term(text, term):
    """Return the verbatim substring of text matching term, or None.

    ASCII terms are matched with alphanumeric boundaries to avoid false
    positives inside longer words; non-ASCII (e.g. Chinese) terms use plain
    case-insensitive substring search.
    """
    if not text or not term:
        return None
    if term.isascii():
        m = re.search(r"(?<![A-Za-z0-9])" + re.escape(term)
                      + r"(?![A-Za-z0-9])", text, re.IGNORECASE)
        return m.group(0) if m else None
    i = text.lower().find(term.lower())
    return text[i:i + len(term)] if i >= 0 else None


def collect_hits(text, terms, field):
    hits = []
    for t in terms:
        snip = find_term(text, t)
        if snip is not None:
            hits.append({"term": t, "snippet": snip, "field": field})
    return hits


def detect_evidence_level(title, abstract, venue):
    hay = (title or "") + " . " + (abstract or "")
    for level, patterns in LEVEL_PATTERNS:
        for p in patterns:
            m = re.search(p, hay, re.IGNORECASE)
            if m:
                field = "title" if m.start() < len(title or "") else "abstract"
                return level, {"snippet": m.group(0), "field": field}
    v = (venue or "").lower()
    if v and any(h in v for h in PREPRINT_VENUE_HINTS):
        return "preprint", {"snippet": venue, "field": "venue"}
    return "unknown", None


# ---------------------------------------------------------------------------
# Terms validation
# ---------------------------------------------------------------------------


def _term_list(terms, key, warnings):
    raw = terms.get(key) or []
    if not isinstance(raw, list):
        warnings.append("terms key %r is not a list; treated as empty" % key)
        return []
    out = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        else:
            warnings.append("terms key %r: dropped non-string/empty entry %r"
                            % (key, item))
    return out


def load_terms(path):
    raw = load_json(path, fatal=True)
    if not isinstance(raw, dict):
        raise SystemExit("FATAL: criteria_terms.json must be a JSON object")
    warnings = []
    parsed = {
        "research_question": raw.get("research_question") or "",
        "topic_terms": _term_list(raw, "topic_terms", warnings),
        "population_terms": _term_list(raw, "population_terms", warnings),
        "method_terms": _term_list(raw, "method_terms", warnings),
        "exclusion_terms": _term_list(raw, "exclusion_terms", warnings),
    }
    pref = raw.get("evidence_level_preference")
    if isinstance(pref, list):
        ok = [p for p in pref if p in EVIDENCE_LEVELS]
        bad = [p for p in pref if p not in EVIDENCE_LEVELS]
        if bad:
            warnings.append("evidence_level_preference: unknown levels "
                            "dropped: %r" % bad)
        parsed["evidence_level_preference"] = ok or list(EVIDENCE_LEVELS)
    else:
        parsed["evidence_level_preference"] = list(EVIDENCE_LEVELS)
    ry = raw.get("recency_years")
    if isinstance(ry, (int, float)) and ry > 0:
        parsed["recency_years"] = float(ry)
    else:
        parsed["recency_years"] = None
        if ry is not None:
            warnings.append("recency_years %r invalid; rubric default used"
                            % (ry,))
    if not parsed["topic_terms"]:
        raise SystemExit(
            "FATAL: criteria_terms.json has no usable 'topic_terms'. The "
            "model must translate the research question into a non-empty "
            "topic term list before scoring; fix the file and rerun score.")
    return parsed, warnings


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------


def compute_signals(rec, terms, rubric, ref_year, warnings):
    title = rec.get("title") or ""
    abstract = rec.get("abstract") or ""
    venue = rec.get("venue") or ""
    both = (title + " " + abstract).strip()
    signals = {}

    # S1 topic: title coverage weighted above abstract coverage
    topic = terms["topic_terms"]
    t_hits = collect_hits(title, topic, "title")
    a_hits = collect_hits(abstract, topic, "abstract")
    tw = float(rubric["signals"]["S1_topic"].get("title_weight", 0.7))
    tw = min(max(tw, 0.0), 1.0)
    n_t = len({h["term"] for h in t_hits})
    n_a = len({h["term"] for h in a_hits}) if abstract else 0
    score = tw * (n_t / len(topic)) + (1.0 - tw) * (n_a / len(topic))
    signals["S1_topic"] = {
        "score": round(score, 4),
        "hits": sorted({h["term"] for h in t_hits + a_hits}),
        "evidence": t_hits + a_hits,
        "note": "标题命中 %d/%d 词，摘要命中 %d/%d 词（标题权重 %.2f）"
                % (n_t, len(topic), n_a, len(topic), tw),
    }

    # S2 population / S3 method: coverage over title+abstract
    for name, key in (("S2_population", "population_terms"),
                      ("S3_method", "method_terms")):
        tlist = terms[key]
        if not tlist:
            signals[name] = {"score": None, "hits": [], "evidence": [],
                             "note": "词表为空，信号不适用（权重按比例再分配）"}
            continue
        hits = collect_hits(both, tlist, "title_or_abstract")
        n_h = len({h["term"] for h in hits})
        signals[name] = {
            "score": round(n_h / len(tlist), 4),
            "hits": sorted({h["term"] for h in hits}),
            "evidence": hits,
            "note": "命中 %d/%d 词" % (n_h, len(tlist)),
        }

    # S4 evidence level
    level, ev = detect_evidence_level(title, abstract, venue)
    pref = terms["evidence_level_preference"]
    n = len(pref)
    idx = pref.index(level) if level in pref else n - 1
    s4 = round((n - idx) / n, 4)
    signals["S4_evidence_level"] = {
        "score": s4,
        "level": level,
        "hits": [level],
        "evidence": ([dict(ev, term=level)] if ev else []),
        "note": ("判定层级 %s（偏好序位 %d/%d）" % (level, idx + 1, n))
                + ("" if ev else "；无设计关键词与预印本 venue 线索"),
    }

    # S5 recency
    window = terms.get("recency_years") or rubric.get(
        "recency_window_years", 10)
    year = rec.get("year")
    if year is None:
        signals["S5_recency"] = {"score": None, "hits": [], "evidence": [],
                                 "note": "年份缺失，信号不可用（权重按比例再分配）"}
    else:
        age = max(0, (ref_year or year) - year)
        if age <= window:
            s5 = 1.0
        else:
            s5 = max(0.0, 1.0 - (age - window) / float(window))
        signals["S5_recency"] = {
            "score": round(s5, 4), "hits": [], "evidence": [],
            "note": "出版年 %d，参考年 %d，年龄 %d 年，窗口 %d 年"
                    % (year, ref_year, age, window),
        }

    # S6 metadata completeness / source quality
    present, missing = [], []
    for f in S6_FIELD_WEIGHTS:
        (present if rec.get(f) not in (None, "", []) else missing).append(f)
    s6 = sum(S6_FIELD_WEIGHTS[f] for f in present)
    signals["S6_metadata"] = {
        "score": round(s6, 4),
        "hits": present,
        "evidence": [{"field": f, "status": "present"} for f in present]
                    + [{"field": f, "status": "missing"} for f in missing],
        "note": "字段齐备 %d/6；缺失：%s"
                % (len(present), "、".join(missing) if missing else "无"),
    }

    # Evidence self-check: every snippet must be a verbatim substring of the
    # claimed source field. A failed check zeroes the signal and warns.
    haystacks = {"title": title, "abstract": abstract, "venue": venue,
                 "title_or_abstract": both}
    for name, sig in signals.items():
        bad = []
        for item in sig.get("evidence", []):
            snip = item.get("snippet")
            if not snip:
                continue
            hay = haystacks.get(item.get("field"), both)
            if snip not in hay and snip not in both and snip not in venue:
                bad.append(snip)
        if bad:
            sig["score"] = 0.0
            sig["note"] += "；证据自检失败（非原文子串：%r），信号计 0" % bad
            warnings.append("%s: signal %s evidence self-check FAILED; "
                            "signal zeroed" % (rec["record_id"], name))

    # Hard exclusion signal
    excl = collect_hits(title, terms["exclusion_terms"], "title") + \
        collect_hits(abstract, terms["exclusion_terms"], "abstract")
    return signals, excl


def weighted_total(signal_scores, weights):
    """Fuse available signal scores; unavailable (None) signals get their
    weight redistributed proportionally. Returns (total, applied_weights)."""
    avail = [(n, max(0.0, float(weights.get(n, 0.0))), s)
             for n, s in signal_scores.items()
             if s is not None and float(weights.get(n, 0.0)) > 0]
    denom = sum(w for _, w, _ in avail)
    if denom <= 0:
        return 0.0, {n: 0.0 for n in signal_scores}
    applied = {n: 0.0 for n in signal_scores}
    total = 0.0
    for n, w, s in avail:
        applied[n] = round(w / denom, 4)
        total += w * s
    return round(total / denom, 4), applied


# ---------------------------------------------------------------------------
# score subcommand
# ---------------------------------------------------------------------------


def cmd_score(args):
    records = load_jsonl(os.path.join(args.work, "records.jsonl"), fatal=True)
    terms, term_warnings = load_terms(args.terms)
    rubric, rubric_src = resolve_rubric(args)
    weights = {n: float(rubric["signals"][n].get("weight", 0.0))
               for n in SIGNAL_NAMES}
    th = rubric.get("thresholds") or {}
    t_ret = float(th.get("retained", 0.65))
    t_pen = float(th.get("pending", 0.40))
    if t_pen > t_ret:
        print("WARNING: pending threshold %.2f > retained threshold %.2f; "
              "swapping" % (t_pen, t_ret), file=sys.stderr)
        t_ret, t_pen = t_pen, t_ret

    warnings = list(term_warnings)
    if not records:
        out = args.out or os.path.join(args.work, "scored.jsonl")
        open(out, "w", encoding="utf-8").close()
        print(json.dumps({"records": 0, "note": "empty candidate set; legal, "
                          "assemble will deliver status=empty_result",
                          "warnings": warnings}, ensure_ascii=False, indent=2))
        return 0

    years = [r["year"] for r in records if r.get("year")]
    ref_year = max(years) if years else None
    if ref_year is None:
        warnings.append("no record has a year; S5 recency unavailable for "
                        "all records (weight redistributed)")

    rows = []
    for rec in records:
        rec_warnings = []
        signals, excl = compute_signals(rec, terms, rubric, ref_year,
                                        rec_warnings)
        scores = {n: signals[n].get("score") for n in SIGNAL_NAMES}
        total, applied = weighted_total(scores, weights)
        if excl:
            label, basis = "excluded", "exclusion_signal_hit"
        elif not rec.get("abstract"):
            label, basis = "pending", "insufficient_metadata_no_abstract"
        elif total >= t_ret:
            label, basis = "retained", "total_score %.3f >= retained %.2f" % (total, t_ret)
        elif total >= t_pen:
            label, basis = "pending", "total_score %.3f in pending band [%.2f, %.2f)" % (total, t_pen, t_ret)
        else:
            label, basis = "excluded", "total_score %.3f < pending %.2f" % (total, t_pen)
        rows.append({
            "record_id": rec["record_id"],
            "signals": signals,
            "signal_scores": scores,
            "exclusion_hits": excl,
            "total_score": total,
            "applied_weights": applied,
            "label": label,
            "label_basis": basis,
            "warnings": rec_warnings,
        })
        warnings.extend(rec_warnings)

    out = args.out or os.path.join(args.work, "scored.jsonl")
    with open(out, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    counts = {k: sum(1 for r in rows if r["label"] == k) for k in LABELS}
    print(json.dumps({
        "records": len(rows), "counts": counts, "ref_year": ref_year,
        "rubric": rubric_src, "thresholds": {"retained": t_ret, "pending": t_pen},
        "out": out, "warnings": warnings,
    }, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# Ranking with the documented tie protocol
# ---------------------------------------------------------------------------


def rank_entries(entries, rubric):
    """entries: list of dicts with record_id, total, signal_scores, year.
    Deterministic order: total desc -> per-signal priority desc -> newer
    year -> record_id. Residual exact ties are grouped and flagged."""
    order = rubric.get("tie_break_order") or SIGNAL_NAMES
    eps = float(rubric.get("tie_epsilon", 1e-6))

    def sig_val(e, n):
        v = e["signal_scores"].get(n)
        return v if v is not None else -1.0

    def sort_key(e):
        return tuple([-e["total"]]
                     + [-sig_val(e, n) for n in order]
                     + [-(e.get("year") or 0), e["record_id"]])

    ranked = sorted(entries, key=sort_key)

    def same(a, b):
        if abs(a["total"] - b["total"]) > eps:
            return False
        if any(abs(sig_val(a, n) - sig_val(b, n)) > eps for n in order):
            return False
        return (a.get("year") or 0) == (b.get("year") or 0)

    gid, i = 0, 0
    while i < len(ranked):
        j = i + 1
        while j < len(ranked) and same(ranked[i], ranked[j]):
            j += 1
        if j - i > 1:
            gid += 1
            members = [r["record_id"] for r in ranked[i:j]]
            for r in ranked[i:j]:
                r["tie_group"] = "T%d" % gid
                r["tie_members"] = members
        i = j
    for pos, r in enumerate(ranked, 1):
        r["rank"] = pos
    return ranked


def entries_from_scored(scored, records, rubric, weights=None):
    weights = weights or {n: float(rubric["signals"][n].get("weight", 0.0))
                          for n in SIGNAL_NAMES}
    by_id = {r["record_id"]: r for r in records}
    entries = []
    for row in scored:
        total, _ = weighted_total(row["signal_scores"], weights)
        entries.append({
            "record_id": row["record_id"],
            "total": total,
            "signal_scores": row["signal_scores"],
            "year": by_id.get(row["record_id"], {}).get("year"),
        })
    return entries


def topk_ids(ranked, k):
    return [r["record_id"] for r in ranked[:max(0, min(k, len(ranked)))]]


# ---------------------------------------------------------------------------
# sensitivity subcommand
# ---------------------------------------------------------------------------


def cmd_sensitivity(args):
    rubric, rubric_src = resolve_rubric(args)
    scored = load_jsonl(os.path.join(args.work, "scored.jsonl"), fatal=True)
    records = load_jsonl(os.path.join(args.work, "records.jsonl"), fatal=True)
    k = int(args.k)
    pct = float(rubric.get("sensitivity_perturb_pct", 0.25))
    base_weights = {n: float(rubric["signals"][n].get("weight", 0.0))
                    for n in SIGNAL_NAMES}

    report = {
        "k": k, "perturb_pct": pct, "rubric": rubric_src,
        "note": "敏感性比较采用严格前 k（不做平局组扩展）",
        "baseline_weights": base_weights,
        "perturbations": [], "stability": {},
    }

    if not scored:
        report["note"] = "空候选集：无排序可扰动，报告为空属正常。"
        write_json(os.path.join(args.work, "sensitivity.json"), report)
        with open(os.path.join(args.work, "sensitivity_report.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("# 敏感性报告\n\n空候选集，无排序可扰动。\n")
        print(json.dumps({"records": 0, "note": report["note"]},
                         ensure_ascii=False))
        return 0

    base_entries = entries_from_scored(scored, records, rubric)
    base_ranked = rank_entries([dict(e) for e in base_entries], rubric)
    base_rank = {r["record_id"]: r["rank"] for r in base_ranked}
    base_top = topk_ids(base_ranked, k)
    report["baseline_topk"] = base_top

    perturbable = [n for n in SIGNAL_NAMES if base_weights.get(n, 0) > 0]
    for name in perturbable:
        for factor, tag in ((1.0 + pct, "+%d%%" % round(pct * 100)),
                            (1.0 - pct, "-%d%%" % round(pct * 100))):
            pw = dict(base_weights)
            pw[name] = base_weights[name] * factor
            entries = entries_from_scored(scored, records, rubric, pw)
            pr = rank_entries(entries, rubric)
            p_top = topk_ids(pr, k)
            p_rank = {r["record_id"]: r["rank"] for r in pr}
            added = [x for x in p_top if x not in base_top]
            removed = [x for x in base_top if x not in p_top]
            disp = max((abs(p_rank[rid] - base_rank[rid])
                        for rid in p_rank), default=0)
            report["perturbations"].append({
                "signal": name, "direction": tag,
                "weight_before": base_weights[name],
                "weight_after_raw": round(pw[name], 4),
                "topk": p_top, "added": added, "removed": removed,
                "max_rank_displacement": disp,
            })

    n_pert = len(report["perturbations"])
    for rid in base_top:
        fails = ["%s %s" % (p["signal"], p["direction"])
                 for p in report["perturbations"] if rid not in p["topk"]]
        report["stability"][rid] = {
            "verdict": ("stable" if not fails else "unstable"),
            "fails_under": fails,
        }
    stable_n = sum(1 for v in report["stability"].values()
                   if v["verdict"] == "stable")
    report["summary"] = ("基线 top-%d 共 %d 条；%d 个单因子 ±%d%% 扰动下，"
                         "%d 条全程稳定在 top-%d，%d 条不稳定。"
                         % (k, len(base_top), n_pert, round(pct * 100),
                            stable_n, k, len(base_top) - stable_n))

    write_json(os.path.join(args.work, "sensitivity.json"), report)

    lines = ["# 敏感性（稳健性）报告", "",
             "- k = %d；单因子扰动幅度 ±%d%%（扰动后权重归一化重排）"
             % (k, round(pct * 100)),
             "- 基线权重："
             + "，".join("%s=%.2f" % (n, w) for n, w in base_weights.items()),
             "- 基线 top-%d：%s" % (k, "、".join(base_top) or "（空）"), "",
             "| 扰动信号 | 方向 | top-k 新增 | top-k 移出 | 最大名次位移 |",
             "|---|---|---|---|---|"]
    for p in report["perturbations"]:
        lines.append("| %s | %s | %s | %s | %d |"
                     % (p["signal"], p["direction"],
                        "、".join(p["added"]) or "—",
                        "、".join(p["removed"]) or "—",
                        p["max_rank_displacement"]))
    lines += ["", "## 稳定性判定", "",
              "| 基线 top-k 记录 | 判定 | 失守扰动 |", "|---|---|---|"]
    for rid in base_top:
        st = report["stability"][rid]
        lines.append("| %s | %s | %s |"
                     % (rid, st["verdict"],
                        "、".join(st["fails_under"]) or "—"))
    lines += ["", report["summary"], ""]
    with open(os.path.join(args.work, "sensitivity_report.md"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print(json.dumps({"records": len(scored), "perturbations": n_pert,
                      "summary": report["summary"],
                      "out": [os.path.join(args.work, "sensitivity.json"),
                              os.path.join(args.work, "sensitivity_report.md")]},
                     ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# assemble subcommand
# ---------------------------------------------------------------------------


def confidence_for(rec, row):
    if not rec.get("abstract"):
        return "low"
    if row["signal_scores"].get("S4_evidence_level") is not None and \
            row["signals"].get("S4_evidence_level", {}).get("level") == "unknown":
        return "medium"
    if any(v is None for v in row["signal_scores"].values()):
        return "medium"
    return "high"


def build_rationale(rec, row, rubric):
    bits = ["加权总分 %.3f" % row["total_score"]]
    for n in SIGNAL_NAMES:
        sig = row["signals"].get(n, {})
        s = row["signal_scores"].get(n)
        if s is None:
            bits.append("%s 不可用（%s）" % (SIGNAL_SHORT[n],
                                             sig.get("note", "")))
            continue
        snips = []
        for ev in sig.get("evidence", [])[:3]:
            if ev.get("snippet"):
                snips.append("『%s』" % ev["snippet"])
        extra = ""
        if n == "S4_evidence_level" and sig.get("level"):
            extra = "（层级 %s）" % sig["level"]
        elif n == "S6_metadata" and sig.get("evidence"):
            miss = [e["field"] for e in sig["evidence"]
                    if e.get("status") == "missing"]
            extra = "（缺：%s）" % "、".join(miss) if miss else "（字段齐备）"
        bits.append("%s=%.2f%s%s"
                    % (SIGNAL_SHORT[n], s, extra,
                       ("，证据 " + "、".join(snips)) if snips else ""))
    if row["exclusion_hits"]:
        bits.append("排除信号命中："
                    + "、".join("『%s』" % h["snippet"]
                                for h in row["exclusion_hits"][:3]))
    bits.append("标签 %s（依据：%s）" % (row["label"], row["label_basis"]))
    return "；".join(bits)


def cmd_assemble(args):
    rubric, rubric_src = resolve_rubric(args)
    scored = load_jsonl(os.path.join(args.work, "scored.jsonl"), fatal=True)
    records = load_jsonl(os.path.join(args.work, "records.jsonl"), fatal=True)
    meta = load_json(os.path.join(args.work, "case_meta.json"), default={})
    by_id = {r["record_id"]: r for r in records}
    k = int(args.k)
    os.makedirs(args.out, exist_ok=True)

    sensitivity = load_json(os.path.join(args.work, "sensitivity.json"),
                            default=None)
    stability_map = (sensitivity or {}).get("stability") or {}
    sens_missing = sensitivity is None and len(scored) > 0

    ranked_rows = []
    if scored:
        entries = entries_from_scored(scored, records, rubric)
        ranked_entries = rank_entries(entries, rubric)
        score_by_id = {r["record_id"]: r for r in scored}
        for e in ranked_entries:
            row = score_by_id[e["record_id"]]
            rec = by_id.get(e["record_id"], {})
            entry = {
                "rank": e["rank"],
                "record_id": e["record_id"],
                "title": rec.get("title"),
                "year": rec.get("year"),
                "venue": rec.get("venue"),
                "doi": rec.get("doi"),
                "label": row["label"],
                "label_basis": row["label_basis"],
                "confidence": confidence_for(rec, row),
                "total_score": e["total"],
                "signal_breakdown": {
                    n: {"score": row["signal_scores"].get(n),
                        "weight_applied": row["applied_weights"].get(n),
                        "hits": row["signals"][n].get("hits", []),
                        "evidence": row["signals"][n].get("evidence", []),
                        "note": row["signals"][n].get("note", "")}
                    for n in SIGNAL_NAMES
                },
                "exclusion_hits": row["exclusion_hits"],
                "tie_group": e.get("tie_group"),
                "tie_members": e.get("tie_members"),
                "stability": stability_map.get(e["record_id"], {}).get(
                    "verdict", "not_assessed"),
                "rationale": build_rationale(rec, row, rubric),
                "warnings": row.get("warnings", []),
                "provenance": rec.get("provenance"),
            }
            ranked_rows.append(entry)

    # top-k with tie-group extension
    top_rows = ranked_rows[:k]
    k_note = None
    if ranked_rows and len(ranked_rows) > k:
        boundary = ranked_rows[k - 1]
        if boundary.get("tie_group"):
            extra = [r for r in ranked_rows[k:]
                     if r.get("tie_group") == boundary["tie_group"]]
            if extra:
                top_rows = ranked_rows[:k] + extra
                k_note = ("top-%d 边界落在平局组 %s 上，整组 %d 条一并纳入"
                          % (k, boundary["tie_group"], len(top_rows)))
    for r in ranked_rows:
        r["in_top_k"] = r in top_rows or r["record_id"] in {
            t["record_id"] for t in top_rows}

    counts = {lb: sum(1 for r in ranked_rows if r["label"] == lb)
              for lb in LABELS}
    total = len(records)
    if total == 0:
        status, status_note = "empty_result", "候选集为空；计分、排序、敏感性均为空属合法交付。"
    elif sens_missing:
        status, status_note = "partial", "缺少 sensitivity.json：稳定性未评估，其余结果完整。"
    else:
        status, status_note = "complete", "评分、排序、敏感性检验均已执行。"

    th = rubric.get("thresholds") or {}
    weights = {n: float(rubric["signals"][n].get("weight", 0.0))
               for n in SIGNAL_NAMES}
    result = {
        "case_id": meta.get("case_id", "UNKNOWN"),
        "status": status,
        "status_note": status_note,
        "research_question": meta.get("research_question", ""),
        "counts": {"total": total, **counts},
        "k": k,
        "top_k": [r["record_id"] for r in top_rows],
        "top_k_note": k_note,
        "ranked_results": ranked_rows,
        "rubric_applied": {
            "source": rubric_src,
            "weights": weights,
            "thresholds": {"retained": th.get("retained", 0.65),
                           "pending": th.get("pending", 0.40)},
            "tie_break_order": rubric.get("tie_break_order") or SIGNAL_NAMES,
            "recency_window_years": rubric.get("recency_window_years", 10),
            "sensitivity_perturb_pct": rubric.get("sensitivity_perturb_pct",
                                                  0.25),
        },
        "tie_groups": sorted({r["tie_group"] for r in ranked_rows
                              if r.get("tie_group")}),
        "sensitivity_summary": (sensitivity or {}).get("summary",
                                "敏感性检验未运行（sensitivity.json 缺失）"),
        "metadata_gaps": meta.get("metadata_gaps", []),
        "provenance_notes": [
            {"record_id": r["record_id"], "provenance": r["provenance"]}
            for r in ranked_rows if r.get("provenance")],
        "uncertainty": ("排序基于有限候选快照内的标题/摘要级证据与固定评分卡，"
                        "未做联网检索、不声称全局召回；权重带内的稳定性见敏感性"
                        "报告，标记 unstable 的条目在权重微调下可能跌出 top-k。"
                        "输入夹具标注（provenance）仅作来源记录，未作为排序依据。"),
        "sources": meta.get("sources", []),
        "change_log": meta.get("change_log", []),
    }
    for f in meta.get("contract_fields") or []:
        if isinstance(f, str) and f not in result:
            result[f] = None

    write_json(os.path.join(args.out, "result.json"), result)

    # ---- human-reviewable report ----
    lines = ["# 排序报告 — case %s" % result["case_id"], "",
             "研究问题：%s" % (result["research_question"] or "n/a"), "",
             "状态：%s（%s）" % (status, status_note), "",
             "## 权重与阈值", "",
             "| 信号 | 定义 | 权重 |", "|---|---|---|"]
    for n in SIGNAL_NAMES:
        spec = rubric["signals"][n]
        lines.append("| %s | %s | %.2f |"
                     % (SIGNAL_SHORT[n], spec.get("definition", ""),
                        weights[n]))
    lines += ["", "- 阈值：retained ≥ %.2f；pending ∈ [%.2f, %.2f)；"
              "低于 pending 阈值 → excluded；排除信号命中 → 硬 excluded；"
              "无摘要 → pending（信息不足）。"
              % (result["rubric_applied"]["thresholds"]["retained"],
                 result["rubric_applied"]["thresholds"]["pending"],
                 result["rubric_applied"]["thresholds"]["retained"]),
              "- 平局协议：总分 → 信号优先级 %s → 年份新→旧 → record_id；"
              "仍相同进 tie_group 并整组标注。"
              % " → ".join(rubric.get("tie_break_order") or SIGNAL_NAMES), "",
              "## 评分卡总表（排序结果）", "",
              "| rank | record | 总分 | %s | 标签 | 置信 | 平局组 | 稳定性 |"
              % " | ".join(SIGNAL_SHORT[n] for n in SIGNAL_NAMES),
              "|" + "---|" * (len(SIGNAL_NAMES) + 6)]
    for r in ranked_rows:
        sig_cells = []
        for n in SIGNAL_NAMES:
            s = r["signal_breakdown"][n]["score"]
            sig_cells.append("n/a" if s is None else "%.2f" % s)
        lines.append("| %d | %s | %.3f | %s | %s | %s | %s | %s |"
                     % (r["rank"], r["record_id"], r["total_score"],
                        " | ".join(sig_cells), r["label"], r["confidence"],
                        r["tie_group"] or "—", r["stability"]))
    lines += ["", "top-%d：%s%s" % (k, "、".join(result["top_k"]) or "（空）",
                                    ("；" + k_note) if k_note else ""), "",
              "## 逐条理由（可复核）", ""]
    for r in ranked_rows:
        lines.append("### #%d %s — %s（%s，总分 %.3f）"
                     % (r["rank"], r["record_id"], r["label"],
                        r["confidence"], r["total_score"]))
        lines.append("- 标题：%s" % (r["title"] or "（缺失）"))
        lines.append("- 理由：%s" % r["rationale"])
        if r.get("provenance"):
            lines.append("- provenance（输入夹具标注，不作裁决依据）：%s"
                         % json.dumps(r["provenance"], ensure_ascii=False))
        if r.get("warnings"):
            lines.append("- 告警：%s" % "；".join(r["warnings"]))
        lines.append("")
    lines += ["## 敏感性摘要", "",
              result["sensitivity_summary"], ""]
    gaps = meta.get("metadata_gaps") or []
    if gaps:
        lines += ["## 元数据缺口（未补造）", ""]
        for g in gaps:
            lines.append("- %s 缺失：%s" % (g["record_id"],
                                            "、".join(g["missing"])))
        lines.append("")
    lines += ["## 不确定性", "", result["uncertainty"], ""]
    with open(os.path.join(args.out, "ranking_report.md"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    # audit copies so a reviewer can rerun score/sensitivity independently
    for name in ("records.jsonl", "scored.jsonl", "criteria_terms.json",
                 "rubric.json", "sensitivity.json", "sensitivity_report.md"):
        src = os.path.join(args.work, name)
        if os.path.exists(src):
            with open(src, encoding="utf-8") as a, \
                    open(os.path.join(args.out, name), "w",
                         encoding="utf-8") as b:
                b.write(a.read())

    print(json.dumps({"result": os.path.join(args.out, "result.json"),
                      "report": os.path.join(args.out, "ranking_report.md"),
                      "status": status, "counts": result["counts"],
                      "top_k": result["top_k"]},
                     ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("score", help="score all records on six signals")
    p.add_argument("--work", required=True)
    p.add_argument("--terms", required=True, help="criteria_terms.json path")
    p.add_argument("--rubric", default=None,
                   help="rubric.json path (default: work/rubric.json, "
                        "else built-in)")
    p.add_argument("--out", default=None,
                   help="output jsonl (default: work/scored.jsonl)")
    p.set_defaults(fn=cmd_score)

    p = sp.add_parser("sensitivity", help="one-factor weight perturbation")
    p.add_argument("--work", required=True)
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--rubric", default=None)
    p.set_defaults(fn=cmd_sensitivity)

    p = sp.add_parser("assemble", help="final ranking + deliverables")
    p.add_argument("--work", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--rubric", default=None)
    p.set_defaults(fn=cmd_assemble)

    args = ap.parse_args()
    if hasattr(args, "k") and args.k < 1:
        raise SystemExit("FATAL: --k must be >= 1")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

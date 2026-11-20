#!/usr/bin/env python3
"""dedup-conflict-adjudicator :: dedup_engine.py

Deterministic duplicate detection, conflict scanning, and canonical merge.

Subcommands:
  fingerprint    --work W   -> W/pairs.jsonl + W/clusters.json
  conflicts      --work W   -> W/conflict_ledger.json
  merge          --work W --adjudications W/adjudications.jsonl
                             -> W/canonical.jsonl + W/merge_map.json
  queue          --work W   -> W/review_queue.json

All decisions follow references/merge_rules.md (rules R1..R6). Script output
is advisory: the model's adjudications.jsonl may confirm or override script
suggestions (rule R4), but anything unresolved is escalated, never guessed.
Standard library only.
"""
import argparse
import itertools
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Rule R1 thresholds (mirrors references/merge_rules.md; script is normative).
# ---------------------------------------------------------------------------
AUTO_TITLE_J = 0.95        # near-identical title + shared authors => confirmed
VERSION_TITLE_J = 0.85     # same work, different venue/year => version variant
SUSPECT_TITLE_J = 0.60     # lower band bound => suspected, needs adjudication
AUTHOR_OV_MIN = 0.5        # author overlap required for title-similarity tiers
SUSPECT_YEAR_SPAN = 2      # suspected pairs must be within this many years
MIN_QUOTE_LEN = 8          # screening evidence quote minimum length

STOPWORDS = {"the", "a", "an", "and", "or", "of", "on", "in", "for", "to",
             "with", "by", "at", "from", "is", "are", "was", "were", "using",
             "use", "via", "between", "among", "into", "their", "its"}
CJK_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")
PREPRINT_PAT = re.compile(r"(arxiv|biorxiv|medrxiv|chemrxiv|preprint|"
                          r"working paper|discussion paper)", re.I)


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    out.append({"_unparseable_raw": line[:200]})
    return out


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Fingerprints (rule R1)
# ---------------------------------------------------------------------------

def title_tokens(title):
    if not title:
        return set()
    if CJK_RE.search(title):
        s = re.sub(r"[^\w\u4e00-\u9fff]", "", title.lower())
        return {s[i:i + 2] for i in range(max(1, len(s) - 1))} or {s}
    s = re.sub(r"[^a-z0-9 ]", " ", title.lower())
    toks = [t for t in s.split() if t and t not in STOPWORDS]
    return set(toks)


def jaccard(a, b):
    if not a and not b:
        return 0.0
    u = a | b
    return len(a & b) / len(u) if u else 0.0


def surname(author):
    if not author:
        return None
    s = str(author).strip()
    if "," in s:
        s = s.split(",", 1)[0]
    else:
        s = s.split()[0]
    return re.sub(r"[^a-z\u4e00-\u9fff]", "", s.lower()) or None


def surname_set(authors):
    return {x for x in (surname(a) for a in (authors or [])) if x}


def author_overlap(auth_a, auth_b):
    sa, sb = surname_set(auth_a), surname_set(auth_b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    return inter / min(len(sa), len(sb))


def first_author_year_key(rec):
    sn = surname((rec.get("authors") or [None])[0])
    yr = rec.get("year")
    return "%s|%s" % (sn, yr) if sn and yr else None


def is_preprint(rec):
    blob = " ".join(str(rec.get(k) or "") for k in ("venue", "url", "title"))
    return bool(PREPRINT_PAT.search(blob))


def completeness(rec):
    """Metadata completeness score (rule R2, tie-break 2)."""
    score = 0
    for f in ("title", "abstract", "year", "venue", "doi", "url"):
        if rec.get(f) not in (None, "", []):
            score += 1
    score += min(len(rec.get("authors") or []), 3)
    return score


def pair_verdict(rec_a, rec_b):
    """Return (verdict, signals list) for a record pair per rule R1."""
    ta = title_tokens(rec_a.get("title"))
    tb = title_tokens(rec_b.get("title"))
    tj = jaccard(ta, tb)
    ao = author_overlap(rec_a.get("authors"), rec_b.get("authors"))
    ya, yb = rec_a.get("year"), rec_b.get("year")
    ydiff = abs(ya - yb) if (ya and yb) else None
    doi_a = (rec_a.get("doi") or "").lower()
    doi_b = (rec_b.get("doi") or "").lower()
    venue_a = (rec_a.get("venue") or "").strip().lower()
    venue_b = (rec_b.get("venue") or "").strip().lower()

    if doi_a and doi_b and doi_a == doi_b:
        return "confirmed_duplicate", ["doi_match"]
    if ta and ta == tb and tj == 1.0:
        if (ya and yb and ya != yb) or (venue_a and venue_b and venue_a != venue_b):
            return "version_variant", ["exact_title", "venue_or_year_differs"]
        return "confirmed_duplicate", ["exact_title", "same_year"]
    if tj >= AUTO_TITLE_J and ao >= AUTHOR_OV_MIN:
        return "confirmed_duplicate", ["near_title_j=%.2f" % tj,
                                       "author_overlap=%.2f" % ao]
    if tj >= VERSION_TITLE_J and ao >= AUTHOR_OV_MIN:
        if (ya and yb and ya != yb) or (venue_a and venue_b and venue_a != venue_b):
            return "version_variant", ["same_work_diff_venue_or_year",
                                       "title_j=%.2f" % tj]
        return "suspected_duplicate", ["title_j=%.2f" % tj,
                                       "author_overlap=%.2f" % ao,
                                       "no_version_signal"]
    if (tj >= SUSPECT_TITLE_J and ao >= AUTHOR_OV_MIN and
            (ydiff is None or ydiff <= SUSPECT_YEAR_SPAN)):
        return "suspected_duplicate", ["title_j=%.2f" % tj,
                                       "author_overlap=%.2f" % ao]
    fa_key_a = first_author_year_key(rec_a)
    if (fa_key_a and fa_key_a == first_author_year_key(rec_b)
            and tj >= 0.5 and tj > 0):
        return "suspected_duplicate", ["first_author_year_match",
                                       "title_j=%.2f" % tj]
    return "independent", []


# ---------------------------------------------------------------------------
# cmd: fingerprint
# ---------------------------------------------------------------------------

def cmd_fingerprint(args):
    work = args.work
    records = [r for r in load_jsonl(os.path.join(work, "records.jsonl"))
               if not r.get("_unparseable_raw")]
    by_id = {r["record_id"]: r for r in records if r.get("record_id")}

    pairs_path = os.path.join(work, "pairs.jsonl")
    edges_conf, edges_ver, edges_sus = [], [], []
    with open(pairs_path, "w", encoding="utf-8") as fh:
        for a, b in itertools.combinations(records, 2):
            ra, rb = a["record_id"], b["record_id"]
            verdict, signals = pair_verdict(a, b)
            ta = title_tokens(a.get("title"))
            tb = title_tokens(b.get("title"))
            ya, yb = a.get("year"), b.get("year")
            row = {
                "pair": sorted([ra, rb]),
                "title_jaccard": round(jaccard(ta, tb), 4),
                "author_overlap": round(author_overlap(a.get("authors"),
                                                       b.get("authors")), 4),
                "year_diff": abs(ya - yb) if (ya and yb) else None,
                "doi_match": bool((a.get("doi") or "").lower() and
                                  (a.get("doi") or "").lower() ==
                                  (b.get("doi") or "").lower()),
                "title_fp_equal": bool(ta and ta == tb),
                "first_author_year_match": bool(
                    first_author_year_key(a) and
                    first_author_year_key(a) == first_author_year_key(b)),
                "verdict": verdict,
                "signals": signals,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            edge = tuple(sorted((ra, rb)))
            if verdict == "confirmed_duplicate":
                edges_conf.append(edge)
            elif verdict == "version_variant":
                edges_ver.append(edge)
            elif verdict == "suspected_duplicate":
                edges_sus.append(edge)

    def clusters_from(edges):
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            parent[find(x)] = find(y)

        for x, y in edges:
            union(x, y)
        groups = {}
        for x in list(parent):
            groups.setdefault(find(x), set()).add(x)
        return [sorted(g) for g in groups.values() if len(g) > 1]

    clusters = {
        "rule": "R1",
        "auto_threshold": AUTO_TITLE_J,
        "version_threshold": VERSION_TITLE_J,
        "suspect_band": [SUSPECT_TITLE_J, AUTO_TITLE_J],
        "confirmed_clusters": [
            {"cluster_id": "CC%02d" % (i + 1), "members": m,
             "kind": "confirmed_duplicate"}
            for i, m in enumerate(clusters_from(edges_conf))],
        "version_variant_clusters": [
            {"cluster_id": "VV%02d" % (i + 1), "members": m,
             "kind": "version_variant"}
            for i, m in enumerate(clusters_from(edges_ver))],
        "suspected_pairs": [
            {"pair_id": "SP%02d" % (i + 1), "members": list(p),
             "kind": "suspected_duplicate"}
            for i, p in enumerate(edges_sus)],
        "independent_records": sorted(
            {r["record_id"] for r in records} -
            {x for e in edges_conf + edges_ver + edges_sus for x in e}),
    }
    with open(os.path.join(work, "clusters.json"), "w", encoding="utf-8") as fh:
        json.dump(clusters, fh, ensure_ascii=False, indent=2)
    print(json.dumps({
        "records": len(records),
        "confirmed_clusters": len(clusters["confirmed_clusters"]),
        "version_variant_clusters": len(clusters["version_variant_clusters"]),
        "suspected_pairs": len(clusters["suspected_pairs"]),
        "pairs_file": pairs_path,
    }, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# cmd: conflicts (rule R3, R5)
# ---------------------------------------------------------------------------

FIXTURE_DUP_PAT = re.compile(r"(合成重复|synthetic duplicate|duplicate export|"
                             r"重复导出|conflicting opinions|冲突意见)", re.I)


def source_priority(rec):
    """Rule R3 field priority: DOI-bearing export > peer-reviewed > preprint."""
    if rec.get("doi"):
        return 3
    if rec.get("venue") and not is_preprint(rec):
        return 2
    if is_preprint(rec):
        return 1
    return 0


def cmd_conflicts(args):
    work = args.work
    records = [r for r in load_jsonl(os.path.join(work, "records.jsonl"))
               if not r.get("_unparseable_raw")]
    by_id = {r["record_id"]: r for r in records if r.get("record_id")}
    clusters = load_json(os.path.join(work, "clusters.json"), {}) or {}
    pairs = [p for p in load_jsonl(os.path.join(work, "pairs.jsonl"))
             if not p.get("_unparseable_raw")]

    # Field contradictions are scanned inside *confirmed* duplicate groups only
    # (same work, same export family). Version-variant clusters legitimately
    # differ in venue/year by definition (preprint vs published), so their
    # venue/year differences are identity information, not contradictions.
    dup_groups = []
    for c in clusters.get("confirmed_clusters", []):
        dup_groups.append(c["members"])
    for p in pairs:
        if p.get("doi_match") and p["verdict"] != "confirmed_duplicate":
            dup_groups.append(p["pair"])  # same DOI, other verdict

    ledger = []

    def add(kind, field, ra, rb, va, vb, suggestion, escalate, rule, note):
        ledger.append({
            "conflict_id": "CF%02d" % (len(ledger) + 1),
            "rule": rule,
            "kind": kind,
            "field": field,
            "record_a": ra, "record_b": rb,
            "value_a": va, "value_b": vb,
            "suggested_resolution": suggestion,
            "escalate_to_human": bool(escalate),
            "note": note,
        })

    seen_group_pairs = set()
    for members in dup_groups:
        for ra, rb in itertools.combinations(sorted(members), 2):
            if (ra, rb) in seen_group_pairs:
                continue
            seen_group_pairs.add((ra, rb))
            a, b = by_id.get(ra), by_id.get(rb)
            if not a or not b:
                continue
            # DOI contradiction inside a duplicate group (R3).
            da, db = (a.get("doi") or "").lower(), (b.get("doi") or "").lower()
            if da and db and da != db:
                add("field_contradiction", "doi", ra, rb, a.get("doi_raw"),
                    b.get("doi_raw"), None, True, "R3",
                    "重复组内 DOI 不一致；快照无法判定哪个 DOI 正确，升级人工。")
            # Year contradiction between exports of the same work (R3).
            ya, yb = a.get("year"), b.get("year")
            if ya and yb and ya != yb:
                pri_a, pri_b = source_priority(a), source_priority(b)
                if pri_a != pri_b:
                    winner = ra if pri_a > pri_b else rb
                    add("field_contradiction", "year", ra, rb, ya, yb,
                        {"adopt_record": winner, "value": by_id[winner]["year"]},
                        True, "R3",
                        "同一成果的不同导出版本年份矛盾；按 R3 优先级建议取值"
                        "，但年份矛盾属于导出错误信号，必须人工复核。")
                else:
                    add("field_contradiction", "year", ra, rb, ya, yb,
                        None, True, "R3",
                        "双方来源优先级相同，年份矛盾无法机器裁决，升级人工。")
            # Venue contradiction (non-escalating if priorities differ).
            va_ = (a.get("venue") or "").strip()
            vb_ = (b.get("venue") or "").strip()
            if va_ and vb_ and va_.lower() != vb_.lower():
                pri_a, pri_b = source_priority(a), source_priority(b)
                if pri_a != pri_b:
                    winner = ra if pri_a > pri_b else rb
                    add("field_contradiction", "venue", ra, rb, va_, vb_,
                        {"adopt_record": winner,
                         "value": by_id[winner]["venue"]},
                        False, "R3", "按 R3 来源优先级取值。")
                else:
                    add("field_contradiction", "venue", ra, rb, va_, vb_,
                        None, True, "R3",
                        "双方来源优先级相同，venue 矛盾升级人工。")
            # Author list contradiction (same first author but disjoint sets).
            sa, sb = surname_set(a.get("authors")), surname_set(b.get("authors"))
            if sa and sb and not (sa & sb):
                add("field_contradiction", "authors", ra, rb,
                    a.get("authors"), b.get("authors"), None, True, "R3",
                    "重复组内作者集合不相交，与重复判定矛盾，升级人工。")

    # Rule R5: fixture annotation is provenance-only; verify independently
    # and record agreement or disagreement explicitly.
    ann_records = [r for r in records
                   if r.get("provenance_note")
                   and FIXTURE_DUP_PAT.search(r["provenance_note"])]
    if ann_records:
        merged_edges = set()
        for c in clusters.get("confirmed_clusters", []) + \
                clusters.get("version_variant_clusters", []):
            for x, y in itertools.combinations(sorted(c["members"]), 2):
                merged_edges.add((x, y))
        for r in ann_records:
            partners = sorted(e[1] if e[0] == r["record_id"] else e[0]
                              for e in merged_edges if r["record_id"] in e)
            if partners:
                add("fixture_annotation_check", "provenance_note",
                    r["record_id"], None, r["provenance_note"], None,
                    {"fingerprint_verdict": "duplicate",
                     "partners": partners}, False, "R5",
                    "标注声称重复导出；指纹独立验证为重复（依据 %s），结论与"
                    "标注一致。标注仅作 provenance 提示，未作为裁决依据。"
                    % "+".join(partners))
            else:
                add("fixture_annotation_disagreement",
                    "provenance_note", r["record_id"], None,
                    r["provenance_note"], None, None, True, "R5",
                    "输入标注为“合成重复导出/冲突意见”，但指纹未将其归入任何"
                    "重复簇；标注仅作 provenance 提示保留，不作为裁决依据，"
                    "差异升级人工复核。")

    with open(os.path.join(work, "conflict_ledger.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"rule": "R3/R5", "conflicts": ledger}, fh,
                  ensure_ascii=False, indent=2)
    print(json.dumps({"conflicts": len(ledger),
                      "escalated": sum(1 for c in ledger
                                       if c["escalate_to_human"]),
                      "ledger": os.path.join(work, "conflict_ledger.json")},
                     ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# cmd: merge (rule R2, R4, R6)
# ---------------------------------------------------------------------------

def choose_canonical(members, by_id, hints):
    """Rule R2 order: peer-reviewed > preprint; completeness; newer; id."""
    for m in members:
        if m in hints:
            return m

    def key(rid):
        r = by_id.get(rid) or {}
        return (0 if (r.get("venue") and not is_preprint(r)) else 1,
                -completeness(r),
                -(r.get("year") or 0),
                rid)

    return sorted(members, key=key)[0]


def cmd_merge(args):
    work = args.work
    records = [r for r in load_jsonl(os.path.join(work, "records.jsonl"))
               if not r.get("_unparseable_raw")]
    by_id = {r["record_id"]: r for r in records if r.get("record_id")}
    clusters = load_json(os.path.join(work, "clusters.json"), {}) or {}
    adjudications = [a for a in load_jsonl(args.adjudications)
                     if not a.get("_unparseable_raw")]

    # Union-find over confirmed edges + model-confirmed suspected pairs.
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        if x in by_id and y in by_id:
            parent.setdefault(x, x)
            parent.setdefault(y, y)
            parent[find(x)] = find(y)

    for c in clusters.get("confirmed_clusters", []) + \
            clusters.get("version_variant_clusters", []):
        for x, y in itertools.combinations(sorted(c["members"]), 2):
            union(x, y)

    overrides = {}   # pair tuple -> "merge" | "independent"
    canonical_hints = set()
    rejected_pairs = []
    for a in adjudications:
        ids = a.get("ids") or a.get("members") or []
        if len(ids) < 2:
            continue
        ids = sorted(ids)
        decision = a.get("decision")
        if decision == "confirm_merge":
            for x, y in itertools.combinations(ids, 2):
                overrides[(x, y)] = "merge"
                union(x, y)
        elif decision == "reject_merge":
            for x, y in itertools.combinations(ids, 2):
                overrides[(x, y)] = "independent"
            rejected_pairs.append(ids)
        elif decision == "escalate":
            for x, y in itertools.combinations(ids, 2):
                overrides[(x, y)] = "escalate"
        if a.get("canonical_hint"):
            canonical_hints.add(a["canonical_hint"])

    groups = {}
    for x in list(parent):
        groups.setdefault(find(x), set()).add(x)

    canonical_rows = []
    merge_map = {"rule": "R2/R6", "merged_into": {}, "clusters": []}
    merged_members = set()

    def emit_canonical(members):
        members = sorted(members)
        canon = choose_canonical(members, by_id, canonical_hints)
        src = by_id.get(canon, {})
        merged_from = []
        for m in members:
            r = by_id.get(m, {})
            merged_from.append({
                "record_id": m,
                "title": r.get("title"),
                "year": r.get("year"),
                "venue": r.get("venue"),
                "doi": r.get("doi_raw") or r.get("doi"),
                "source_keys": r.get("source_keys"),
                "provenance_note": r.get("provenance_note"),
            })
            if m != canon:
                merged_members.add(m)
                merge_map["merged_into"][m] = canon
        kind = "singleton"
        if len(members) > 1:
            pre = [m for m in members
                   if is_preprint(by_id.get(m, {})) and m != canon]
            kind = "version_variant" if pre and len(members) == 2 else \
                   "duplicate_merged"
        merge_map["clusters"].append({
            "canonical": canon, "members": members, "kind": kind,
            "canonical_reason": (
                "R2：正式同行评审版优先于预印本；其次元数据完整度、年份新者、"
                "record_id 序。"),
        })
        canonical_rows.append({
            "record_id": canon,
            "title": src.get("title"),
            "abstract": src.get("abstract"),
            "authors": src.get("authors"),
            "year": src.get("year"),
            "venue": src.get("venue"),
            "doi": src.get("doi_raw") or src.get("doi"),
            "url": src.get("url"),
            "provenance_note": src.get("provenance_note"),
            "merged_from": merged_from,
            "merge_kind": kind,
        })

    grouped_ids = set()
    for members in groups.values():
        emit_canonical(members)
        grouped_ids |= set(members)
    for r in records:
        rid = r.get("record_id")
        if rid and rid not in grouped_ids:
            emit_canonical([rid])

    # R6 completeness check: every record exactly once.
    seen = [row["record_id"] for row in canonical_rows]
    for row in canonical_rows:
        seen += [m["record_id"] for m in row["merged_from"]
                 if m["record_id"] != row["record_id"]]
    dup_seen = len(seen) != len(set(seen))
    missing = set(by_id) - set(seen)
    if dup_seen or missing:
        print("FATAL: R6 completeness check failed "
              "(duplicate=%s, missing=%s)" % (dup_seen, sorted(missing)),
              file=sys.stderr)
        sys.exit(3)

    with open(os.path.join(work, "canonical.jsonl"), "w",
              encoding="utf-8") as fh:
        for row in sorted(canonical_rows, key=lambda r: r["record_id"]):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    merge_map["rejected_pairs"] = rejected_pairs
    with open(os.path.join(work, "merge_map.json"), "w",
              encoding="utf-8") as fh:
        json.dump(merge_map, fh, ensure_ascii=False, indent=2)
    print(json.dumps({
        "canonical": len(canonical_rows),
        "merged_away": len(merged_members),
        "clusters": len(merge_map["clusters"]),
        "model_overrides": len(overrides),
        "rejected_pairs": len(rejected_pairs),
    }, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# cmd: queue  (rule R4: everything unresolved lands here, nothing guessed)
# ---------------------------------------------------------------------------

def cmd_queue(args):
    work = args.work
    records = load_jsonl(os.path.join(work, "records.jsonl"))
    clusters = load_json(os.path.join(work, "clusters.json"), {}) or {}
    ledger = load_json(os.path.join(work, "conflict_ledger.json"),
                       {"conflicts": []}) or {"conflicts": []}
    adjudications = [a for a in load_jsonl(
        os.path.join(work, "adjudications.jsonl"))
        if not a.get("_unparseable_raw")]

    resolved = {}
    for a in adjudications:
        ids = sorted(a.get("ids") or a.get("members") or [])
        for x, y in itertools.combinations(ids, 2):
            resolved[(x, y)] = a.get("decision")

    def status_of(members):
        st = {resolved.get(tuple(sorted(p))) for p in
              itertools.combinations(sorted(members), 2)}
        st.discard(None)
        if "escalate" in st:
            return "escalated"
        if st and st <= {"confirm_merge"}:
            return "resolved_merge"
        if st and st <= {"reject_merge"}:
            return "resolved_independent"
        return "open"

    queue = []
    for sp in clusters.get("suspected_pairs", []):
        st = status_of(sp["members"])
        if st in ("open", "escalated"):
            queue.append({"item_id": "RQ%02d" % (len(queue) + 1),
                          "kind": "suspected_duplicate",
                          "members": sp["members"],
                          "status": st,
                          "action_required": "人工裁决是否为重复/版本变体"})
    for c in ledger.get("conflicts", []):
        if c.get("escalate_to_human"):
            pair = sorted(x for x in (c.get("record_a"), c.get("record_b"))
                          if x)
            key = tuple(pair)
            if resolved.get(key) == "confirm_merge" and \
                    c.get("kind") == "fixture_annotation_disagreement":
                continue
            queue.append({"item_id": "RQ%02d" % (len(queue) + 1),
                          "kind": "conflict_escalation",
                          "conflict_id": c.get("conflict_id"),
                          "members": pair,
                          "field": c.get("field"),
                          "status": "escalated",
                          "action_required": "人工给出字段裁决值或确认升级"})
    for r in records:
        if r.get("_unparseable_raw"):
            queue.append({"item_id": "RQ%02d" % (len(queue) + 1),
                          "kind": "unparseable_record",
                          "members": [],
                          "status": "open",
                          "raw_excerpt": r["_unparseable_raw"],
                          "action_required": "人工解析原始记录片段"})
    for g in load_json(os.path.join(work, "case_meta.json"),
                       {"metadata_gaps": []}).get("metadata_gaps", []):
        if g.get("cause") == "unparseable_entry":
            continue  # already queued as unparseable_record
        if "title" in g.get("missing", []):
            queue.append({"item_id": "RQ%02d" % (len(queue) + 1),
                          "kind": "missing_title",
                          "members": [g.get("record_id")],
                          "status": "open",
                          "action_required": "标题缺失，无法可靠去重，需人工确认身份"})

    with open(os.path.join(work, "review_queue.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"rule": "R4", "items": queue}, fh, ensure_ascii=False,
                  indent=2)
    print(json.dumps({"review_items": len(queue),
                      "file": os.path.join(work, "review_queue.json")},
                     ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fingerprint", "conflicts", "queue"):
        p = sub.add_parser(name)
        p.add_argument("--work", required=True)
    p = sub.add_parser("merge")
    p.add_argument("--work", required=True)
    p.add_argument("--adjudications", required=True)
    args = ap.parse_args()
    {"fingerprint": cmd_fingerprint,
     "conflicts": cmd_conflicts,
     "merge": cmd_merge,
     "queue": cmd_queue}[args.cmd](args)


if __name__ == "__main__":
    main()

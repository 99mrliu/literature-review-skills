#!/usr/bin/env python3
"""run_case.py — controversy-gap-cartography 编排器。

  init     阶段0: 解析 case/task, 发现文献, 抽取文本与候选论断句, 主题聚类脚手架,
           partial result。
  check    结构一致性校验: 主题覆盖 / 论断定位 / 矛盾矩阵与空白图引用闭合 / 草稿标记。
  finalize result.json 组装。

仅标准库。判断留痕 <work>/run_log.jsonl。
"""
import argparse, json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def log(work, event, **kw):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    with open(work / "run_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"event": event, **kw}, ensure_ascii=False) + "\n")


def sh(args):
    return subprocess.run(args, capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["init", "check", "finalize"])
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--task", default="/input/task.md")
    ap.add_argument("--input-dir", default="/input")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--out", default="/app/output")
    a = ap.parse_args()
    work, out = Path(a.work), Path(a.out)
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    if a.stage == "init":
        for script in ("ingest.py", "extract_claims.py", "cluster_themes.py"):
            r = sh([sys.executable, str(HERE / script),
                    "--case", a.case, "--task", a.task,
                    "--input-dir", a.input_dir, "--work", str(work)] if script == "ingest.py"
                   else [sys.executable, str(HERE / script), "--work", str(work)])
            sys.stdout.write(r.stdout)
            if r.returncode != 0:
                sys.stderr.write(r.stderr)
                sh([sys.executable, str(HERE / "build_result.py"),
                    "--case", a.case, "--work", str(work), "--out", str(out),
                    "--status", "blocked", "--note", script + " failed: " + r.stderr[:400]])
                return 0
        # 可供模型填空者的初检: 矛盾扫描与空白候选需要模型裁定后的 claims/themes, 这里先跳过
        r2 = sh([sys.executable, str(HERE / "build_result.py"),
                 "--case", a.case, "--work", str(work), "--out", str(out),
                 "--status", "in_progress", "--note", "corpus ingested; claims/themes pending"])
        sys.stdout.write(r2.stdout)
        log(work, "init_done")
        return 0

    if a.stage == "check":
        for script in ("contradiction_scan.py", "gap_map.py", "structure_check.py"):
            r = sh([sys.executable, str(HERE / script), "--work", str(work), "--out", str(out)])
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            if script == "structure_check.py":
                rc = r.returncode
                log(work, "check_done", returncode=rc)
                return rc
        return 0

    if a.stage == "finalize":
        r = sh([sys.executable, str(HERE / "build_result.py"),
                "--case", a.case, "--work", str(work), "--out", str(out)])
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        log(work, "finalize_done", returncode=r.returncode)
        return r.returncode


if __name__ == "__main__":
    sys.exit(main())

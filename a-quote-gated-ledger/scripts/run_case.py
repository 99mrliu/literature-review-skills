#!/usr/bin/env python3
"""run_case.py — quote-gated-evidence-ledger 编排器。

子命令:
  init     阶段0: 防御式解析 case.json/task.md, 发现文献, 抽取文本与锚点,
           写 partial result.json (status=in_progress)。零模型请求。
  verify   引用门控: 校验 evidence_ledger.jsonl 的逐字摘录确实出现在所声称
           定位处, 校验 review_draft.md 中每个 [E#] 可解析到已核验证据行,
           就地修订草稿, 输出 gate_report.json。
  finalize 组装终版 result.json (mirror output_contract + case_id + status
           + sources + uncertainties + change_log)。

用法:
  python3 run_case.py init --case /input/case.json --task /input/task.md \
      --input-dir /input --work /app/work --out /app/output
  python3 run_case.py verify --work /app/work --out /app/output
  python3 run_case.py finalize --case /input/case.json --work /app/work --out /app/output

仅依赖 Python 3 标准库。所有判断留痕于 <work>/run_log.jsonl。
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
    ap.add_argument("stage", choices=["init", "verify", "finalize"])
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
        r = sh([sys.executable, str(HERE / "extract_corpus.py"),
                "--case", a.case, "--task", a.task,
                "--input-dir", a.input_dir, "--work", str(work), "--out", str(out)])
        sys.stdout.write(r.stdout)
        if r.returncode != 0:
            sys.stderr.write(r.stderr)
            # 抽取失败也不允许空手而归: 写 blocked 结果
            sh([sys.executable, str(HERE / "build_result.py"),
                "--case", a.case, "--work", str(work), "--out", str(out),
                "--status", "blocked", "--note", "extract_corpus failed: " + r.stderr[:500]])
            return 0
        r2 = sh([sys.executable, str(HERE / "build_result.py"),
                 "--case", a.case, "--work", str(work), "--out", str(out),
                 "--status", "in_progress", "--note", "corpus parsed; awaiting evidence/draft stages"])
        sys.stdout.write(r2.stdout)
        log(work, "init_done")
        return 0

    if a.stage == "verify":
        r = sh([sys.executable, str(HERE / "verify_ledger.py"),
                "--work", str(work), "--out", str(out)])
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        log(work, "verify_done", returncode=r.returncode)
        return r.returncode

    if a.stage == "finalize":
        r = sh([sys.executable, str(HERE / "build_result.py"),
                "--case", a.case, "--work", str(work), "--out", str(out),
                "--status", "", "--note", ""])
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        log(work, "finalize_done", returncode=r.returncode)
        return r.returncode


if __name__ == "__main__":
    sys.exit(main())

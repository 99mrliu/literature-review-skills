#!/usr/bin/env python3
"""run_case.py — prisma-repro-screening 编排器。

  init     阶段0: 解析 case/task, 发现文献, 抽取文本, 去重分组, partial result。
  audit    阶段1校验: criteria 先行 / 逐篇决定 / 理由引用编号 / 重复组闭合 /
           PRISMA 计数一致; 输出 audit_report.json。
  finalize prisma 流程推导 + result.json 组装。

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
    ap.add_argument("stage", choices=["init", "audit", "finalize"])
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
        for script, args in (("ingest.py", ["--case", a.case, "--task", a.task,
                                            "--input-dir", a.input_dir,
                                            "--work", str(work)]),
                             ("dedup.py", ["--work", str(work)])):
            r = sh([sys.executable, str(HERE / script)] + args)
            sys.stdout.write(r.stdout)
            if r.returncode != 0:
                sys.stderr.write(r.stderr)
                sh([sys.executable, str(HERE / "build_result.py"),
                    "--case", a.case, "--work", str(work), "--out", str(out),
                    "--status", "blocked", "--note", script + " failed: " + r.stderr[:400]])
                return 0
        r2 = sh([sys.executable, str(HERE / "build_result.py"),
                 "--case", a.case, "--work", str(work), "--out", str(out),
                 "--status", "in_progress", "--note", "corpus ingested & deduped; screening pending"])
        sys.stdout.write(r2.stdout)
        log(work, "init_done")
        return 0

    if a.stage == "audit":
        r = sh([sys.executable, str(HERE / "screen_check.py"),
                "--work", str(work), "--out", str(out)])
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        log(work, "audit_done", returncode=r.returncode)
        return r.returncode

    if a.stage == "finalize":
        r0 = sh([sys.executable, str(HERE / "prisma_flow.py"),
                 "--work", str(work), "--out", str(out)])
        sys.stdout.write(r0.stdout)
        r = sh([sys.executable, str(HERE / "build_result.py"),
                "--case", a.case, "--work", str(work), "--out", str(out)])
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        log(work, "finalize_done", returncode=r.returncode)
        return r.returncode


if __name__ == "__main__":
    sys.exit(main())

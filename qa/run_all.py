# -*- coding: utf-8 -*-
"""静澜 Stillwave · QA 总入口（可重复运行）。

按固定顺序执行：
  env_probe → static_contracts → refresh_script → browser → degrade_repeats
每个套件结果写入 qa/results/round<N>/，并合并为 summary.json；
控制台输出逐套件统计与智能路由判定。

Round 2 新增 degrade_repeats：三类故障 × 两组配置 × 各 5 次降级耗时复现，
严格断言 lastDegradeDurationMs ≤ 3000（不放宽）。

用法：
  python3.9 qa/run_all.py --phase preflight --round 1
  python3.9 qa/run_all.py --phase full --round 2
  python3.9 qa/run_all.py --phase full --round 2 --only degrade_repeats
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RESULTS_DIR, ensure_dirs  # noqa: E402

SUITES = ("env_probe", "static_contracts", "refresh_script", "browser",
          "degrade_repeats")


def build_summary(round_dir: str, phase: str, round_no: int,
                  summaries: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    total = sum(x["total"] for x in summaries.values())
    passed = sum(x["passed"] for x in summaries.values())
    failed = sum(x["failed"] for x in summaries.values())
    provisional = sum(x["provisional"] for x in summaries.values())
    skipped = sum(x["skipped"] for x in summaries.values())
    unverified = sum(x["unverified"] for x in summaries.values())
    if phase == "preflight":
        route = "PENDING_CODE_FROZEN（准备阶段，不下最终结论）"
    elif failed > 0:
        route = "Engineer"
    else:
        route = "NoOne"
    return {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "phase": phase,
        "round": round_no,
        "suites": summaries,
        "total": total,
        "passed": passed,
        "failed": failed,
        "provisional": provisional,
        "skipped": skipped,
        "unverified": unverified,
        "formalTotal": passed + failed,
        "formalPassRate": round(passed / (passed + failed) * 100, 1)
        if (passed + failed) else 0.0,
        "ROUTE": route,
        "note": ("环境限制导致的 UNVERIFIED 条目不计入源码失败，"
                 "但必须在 docs/04-qa-report.md 中逐条如实列出"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["preflight", "full"], default="full")
    ap.add_argument("--round", type=int, default=1, choices=[1, 2, 3, 4, 5])
    ap.add_argument("--only", choices=SUITES, default=None,
                    help="只运行指定套件（用于第 2 轮定向回归）")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--no-shots", action="store_true")
    ap.add_argument("--offline-only", action="store_true")
    args = ap.parse_args()

    ensure_dirs()
    # 准备阶段（preflight）单独归档，不占用正式的第 1 / 2 轮编号
    tag = "preflight" if args.phase == "preflight" else "round%d" % args.round
    round_dir = os.path.join(RESULTS_DIR, tag)
    os.makedirs(round_dir, exist_ok=True)
    summaries: Dict[str, Dict[str, Any]] = {}
    # 若 --only，则先载入同轮已有的其它套件结果，保证汇总完整
    for name in SUITES:
        p = os.path.join(round_dir, name + ".json")
        if args.only and name != args.only and os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as fh:
                summaries[name] = json.load(fh)

    selected = [args.only] if args.only else list(SUITES)
    print("=" * 76)
    print("静澜 Stillwave · QA 总入口  phase=%s  round=%d  suites=%s"
          % (args.phase, args.round, ",".join(selected)))
    print("=" * 76, flush=True)

    for name in selected:
        print("\n>>> 运行套件: %s" % name, flush=True)
        t0 = time.time()
        try:
            if name == "env_probe":
                import env_probe
                suite = env_probe.run()
            elif name == "static_contracts":
                import test_static_contracts
                suite = test_static_contracts.run(args.phase)
            elif name == "refresh_script":
                import test_refresh_script
                suite = test_refresh_script.run(args.phase, args.offline_only)
            elif name == "browser":
                import test_browser
                suite = test_browser.run(args.phase, not args.no_audio,
                                         not args.no_shots)
            else:
                import test_degrade_repeats
                suite = test_degrade_repeats.run(args.phase)
            summaries[name] = suite.summary()
            with open(os.path.join(round_dir, name + ".json"), "w",
                      encoding="utf-8") as fh:
                json.dump(summaries[name], fh, ensure_ascii=False, indent=2)
            # 同时刷新默认路径结果，便于单套件查看
            suite.save(name + ".json")
        except Exception as exc:  # noqa: BLE001
            print("[ERROR] 套件 %s 异常: %s: %s" %
                  (name, type(exc).__name__, exc), flush=True)
            summaries[name] = {
                "suite": name, "phase": args.phase, "total": 1,
                "passed": 0, "failed": 1, "provisional": 0,
                "skipped": 0, "unverified": 0, "formalTotal": 1,
                "formalPassRate": 0.0,
                "cases": [{"id": name + "-ERROR", "name": "套件执行异常",
                           "requirement": "QA", "status": "FAIL",
                           "expected": "套件正常执行",
                           "actual": "%s: %s" % (type(exc).__name__, exc)}],
                "artifacts": {},
            }
            with open(os.path.join(round_dir, name + ".json"), "w",
                      encoding="utf-8") as fh:
                json.dump(summaries[name], fh, ensure_ascii=False, indent=2)
        print("<<< %s 完成，耗时 %.1fs" % (name, time.time() - t0), flush=True)

    summary = build_summary(round_dir, args.phase, args.round, summaries)
    with open(os.path.join(round_dir, "summary.json"), "w",
              encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(RESULTS_DIR, "summary.json"), "w",
              encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    print("\n" + "=" * 76)
    print("总计: 用例 %d | 通过 %d | 失败 %d | 预检观察 %d | 跳过 %d | 未验证 %d"
          % (summary["total"], summary["passed"], summary["failed"],
             summary["provisional"], summary["skipped"],
             summary["unverified"]))
    print("正式断言通过率: %s%% (%d/%d)"
          % (summary["formalPassRate"], summary["passed"],
             summary["formalTotal"]))
    print("ROUTE: %s" % summary["ROUTE"])
    print("结果目录: %s" % round_dir)
    print("=" * 76, flush=True)
    return 1 if summary["failed"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

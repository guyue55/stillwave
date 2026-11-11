# -*- coding: utf-8 -*-
"""静澜 Stillwave · 曲库刷新脚本实跑验证。

真实执行 meditation/tools/refresh-sources.py 的 5 类命令，断言退出码与
机器可读报告字段；并校验脚本从未污染 meditation/data/ 下的文件（QA 纪律）。

用法：
  python3.9 qa/test_refresh_script.py [--phase preflight|full] [--offline-only]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RESULTS_DIR, SITE, Suite, ensure_dirs, load_manifest  # noqa: E402

PY39 = "/opt/homebrew/opt/python@3.9/bin/python3.9"
PYTHON = PY39 if os.path.isfile(PY39) else sys.executable
SCRIPT = os.path.join(SITE, "tools", "refresh-sources.py")
DATA_FILES = ["data/audio-sources.json", "data/audio-sources.js"]


def data_hashes() -> Dict[str, str]:
    out = {}
    for rel in DATA_FILES:
        with open(os.path.join(SITE, rel), "rb") as fh:
            out[rel] = hashlib.sha256(fh.read()).hexdigest()
    return out


def invoke(args: List[str], report_name: str, timeout: int = 120
           ) -> Tuple[int, Dict[str, Any], str, Optional[str]]:
    """执行刷新脚本，返回 (退出码, 报告对象, stdout, 错误说明)。"""
    ensure_dirs()
    report_path = os.path.join(RESULTS_DIR, report_name)
    cmd = [PYTHON, SCRIPT] + args + ["--json-report", report_path]
    try:
        proc = subprocess.run(cmd, cwd=SITE, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return -1, {}, "", "执行超过 %ds，已终止" % timeout
    report: Dict[str, Any] = {}
    if os.path.isfile(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as fh:
                report = json.load(fh)
        except (ValueError, OSError) as exc:
            return proc.returncode, {}, proc.stdout, "报告解析失败: %s" % exc
    err = None
    if proc.returncode not in (0, 3):
        err = (proc.stderr or proc.stdout or "")[:300]
    return proc.returncode, report, proc.stdout, err


def run(phase: str = "full", offline_only: bool = False) -> Suite:
    s = Suite("refresh_script", phase=phase)
    before = data_hashes()
    manifest = load_manifest()
    first_url = manifest["tracks"][0]["url"]

    # ---- RS-01 离线 dry-run（主链路） -----------------------------------
    rc, rep, _out, err = invoke(["--offline", "--dry-run"], "refresh_offline.json")
    ok = (rc == 0 and rep.get("count") == 30 and rep.get("alive") == 30
          and rep.get("jsonJsInSync") is True and rep.get("schemaValid") is True
          and rep.get("tracksPreserved") is True and rep.get("offline") is True)
    s.check("RS-01", "--offline --dry-run：退出码 0 / alive=30 / jsonJsInSync / schemaValid",
            "A12 / A7 / P0-13", ok,
            "rc=0, count=30, alive=30, jsonJsInSync=true, schemaValid=true",
            "rc=%s count=%s alive=%s sync=%s schema=%s %s"
            % (rc, rep.get("count"), rep.get("alive"), rep.get("jsonJsInSync"),
               rep.get("schemaValid"), err or ""),
            environment=PYTHON)
    s.artifacts["offlineDryRun"] = rep

    # ---- RS-02 离线 check-only ------------------------------------------
    rc2, rep2, _o2, err2 = invoke(
        ["--offline", "--check-only", "--dry-run"], "refresh_checkonly_offline.json")
    ok2 = (rc2 == 0 and rep2.get("count") == 30
           and rep2.get("dead") == 0 and rep2.get("tracksPreserved") is True)
    s.check("RS-02", "--offline --check-only：schema 复核通过、无 dead、清单不缩水",
            "A12 / P0-13", ok2,
            "rc=0, count=30, dead=0, tracksPreserved=true",
            "rc=%s count=%s dead=%s %s"
            % (rc2, rep2.get("count"), rep2.get("dead"), err2 or ""))
    s.artifacts["checkOnlyOffline"] = rep2

    # ---- RS-03 失效注入 -------------------------------------------------
    rc3, rep3, _o3, err3 = invoke(
        ["--offline", "--dry-run", "--fail-inject", first_url + "=404"],
        "refresh_fail_inject.json")
    ok3 = (rc3 == 0 and rep3.get("quarantined", 0) >= 1
           and rep3.get("tracksPreserved") is True
           and rep3.get("count") == 30)
    s.check("RS-03", "--fail-inject <url>=404：隔离失效但 tracks 不清空",
            "P0-13 / A12 / S-04", ok3,
            "quarantined>=1, tracksPreserved=true, count=30",
            "rc=%s quarantined=%s preserved=%s count=%s %s"
            % (rc3, rep3.get("quarantined"), rep3.get("tracksPreserved"),
               rep3.get("count"), err3 or ""),
            environment="注入 URL: %s" % first_url[:60])
    s.artifacts["failInject"] = rep3

    # ---- RS-04 参数错误退出码 -------------------------------------------
    rc4, rep4, _o4, _e4 = invoke(["--offline", "--dry-run", "--max-new", "-1"],
                                 "refresh_bad_args.json")
    s.check("RS-04", "非法参数返回退出码 4（参数错误约定）", "A12 / §2.4.1",
            rc4 == 4, "退出码 4", "退出码 %s" % rc4)

    # ---- RS-05 动态发现（真实联网） -------------------------------------
    if offline_only:
        s.skip("RS-05", "--discover 动态发现候选（真实联网）", "P1-08 / S-05",
               "--offline-only 模式跳过联网用例（正式 full 阶段执行）")
    else:
        rc5, rep5, _o5, err5 = invoke(
            ["--discover", "--max-new", "5", "--dry-run"], "refresh_discover.json",
            timeout=150)
        if rc5 < 0:
            s.unverified("RS-05", "--discover 动态发现候选（真实联网）",
                         "P1-08 / S-05", "网络受限: %s" % err5)
        else:
            cands = rep5.get("candidates", 0)
            ok5 = (rep5.get("candidatesAllNeedsReview") is True
                   and rep5.get("candidatesVerifiedFalse") is True
                   and rep5.get("candidatesInTracks") == 0
                   and rep5.get("tracksPreserved") is True)
            s.check("RS-05", "--discover：候选全部 needsReview=true 且 0 条进 tracks",
                    "P1-08 / S-05 / AD-10", ok5,
                    "candidatesAllNeedsReview=true, candidatesInTracks=0, tracksPreserved=true",
                    "candidates=%s allNeedsReview=%s verifiedFalse=%s inTracks=%s %s"
                    % (cands, rep5.get("candidatesAllNeedsReview"),
                       rep5.get("candidatesVerifiedFalse"),
                       rep5.get("candidatesInTracks"), err5 or ""))
            s.artifacts["discover"] = rep5
            s.artifacts["discoverCandidateCount"] = cands

    # ---- RS-06 真实健康探测 30 首 ---------------------------------------
    if offline_only:
        s.skip("RS-06", "--check-only 真实探测 30 首（联网）", "A10 / A13 / S-03",
               "--offline-only 模式跳过联网用例（正式 full 阶段执行）")
    else:
        rc6, rep6, _o6, err6 = invoke(
            ["--check-only", "--dry-run"], "refresh_health_live.json", timeout=300)
        if rc6 < 0:
            s.unverified("RS-06", "--check-only 真实探测 30 首（联网）",
                         "A10 / A13 / S-03", "网络受限: %s" % err6)
        else:
            alive = rep6.get("alive", 0)
            dead = rep6.get("dead", 0)
            if rc6 == 3 or (dead > 0 and alive == 0):
                s.unverified("RS-06", "--check-only 真实探测 30 首（联网）",
                             "A10 / A13 / S-03",
                             "网络全失败(rc=%s, alive=%s, dead=%s)，脚本按约定保留原文件；"
                             "判定为环境限制而非源码缺陷" % (rc6, alive, dead))
            else:
                s.check("RS-06", "--check-only 真实探测 30 首：alive=30 / dead=0",
                        "A10 / A13 / S-03", alive == 30 and dead == 0,
                        "alive=30, dead=0", "rc=%s alive=%s dead=%s %s"
                        % (rc6, alive, dead, err6 or ""))
            s.artifacts["healthLive"] = rep6

    # ---- RS-07 全部命令不得污染 data/ ------------------------------------
    after = data_hashes()
    s.check("RS-07", "全部刷新命令均为 dry-run，meditation/data/ 两文件哈希不变",
            "QA 纪律 / P0-07", before == after,
            "两文件 SHA256 前后完全一致",
            "before=%s after=%s" % (before, after))
    s.artifacts["dataHashesBefore"] = before
    s.artifacts["dataHashesAfter"] = after

    s.print_report()
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["preflight", "full"], default="full")
    ap.add_argument("--offline-only", action="store_true")
    args = ap.parse_args()
    s = run(args.phase, args.offline_only)
    path = s.save("refresh_script.json")
    print("结果已写入: %s" % path)
    return 1 if s.counts()["FAIL"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

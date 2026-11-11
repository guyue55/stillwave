# -*- coding: utf-8 -*-
"""静澜 Stillwave · Round 2 降级预算重复复现（CODE_FROZEN 后专用）。

主理人 Round 2 要求：BR-09/10/11 三类故障 × 两组配置
  A) 默认 loadTimeout=3000
  B) inject.setLoadTimeout(2000)
各至少 5 次复现，逐次记录 lastDegradeDurationMs，严格断言 ≤3000（不放宽），
同时断言 playing 恒 true、consoleErrorCount=0、无 dialog/无闪烁、ariaLive=polite。

输出 qa/results/degrade_repeats.json（含 30 次逐次明细），供最终报告引用。
纪律：不放宽断言、不掩盖偶发超标；若仍偶发超标，FAIL 并回传 team-lead。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from common import Suite, ensure_dirs  # noqa: E402
from harness import (  # noqa: E402
    StaticServer, launch_browser, new_page, state, wait_contract,
)
from playwright.sync_api import sync_playwright  # noqa: E402

REPEATS = 5
GROUPS = (("default3000", None), ("injected2000", 2000))
FAULTS = (
    ("404", "BR-09", "404 主源故障注入", "A3 / P0-06 / P0-17"),
    ("timeout", "BR-10", "模拟超时故障注入", "A3 / P0-06 / P0-17"),
    ("network", "BR-11", "断网故障注入", "A3 / P0-06 / P0-14 / P0-17"),
)


def one_run(browser: Any, base_url: str, fast_404: str, kind: str,
            load_ms: Optional[int]) -> Dict[str, Any]:
    """单次注入：返回逐次实测数据。"""
    ctx, page, ev = new_page(browser)
    t0 = time.time()
    row: Dict[str, Any] = {"kind": kind, "loadTimeoutMs": load_ms or 3000}
    try:
        page.goto(base_url, wait_until="load", timeout=20000)
        if not wait_contract(page):
            row.update({"ok": False, "reason": "契约未挂载"})
            return row
        # 组配置：降级链单候选超时窗口
        if load_ms is not None:
            page.evaluate("window.__STILLWAVE__.inject.setLoadTimeout(%d)"
                          % load_ms)
        # 故障注入
        if kind == "404":
            page.evaluate(
                "window.__STILLWAVE__.inject.setManifestOverride(%s)"
                % json.dumps([{"id": "jamendo-122281", "url": fast_404}]))
        elif kind == "timeout":
            page.evaluate("window.__STILLWAVE__.inject.forceTimeoutNext(1)")
        else:
            page.evaluate("window.__STILLWAVE__.inject.setOffline(true)")
        page.evaluate("window.__STILLWAVE__.actions.start()")
        try:
            page.wait_for_function(
                "window.__STILLWAVE__.getState().playing === true",
                timeout=10000)
        except Exception:  # noqa: BLE001
            pass
        degraded = False
        try:
            page.wait_for_function(
                "window.__STILLWAVE__.getState().lastDegradeDurationMs !== null",
                timeout=15000)
            degraded = True
        except Exception:  # noqa: BLE001
            pass
        st = state(page)
        ui = page.evaluate("window.__STILLWAVE__.getUiSnapshot()") or {}
        dur = st.get("lastDegradeDurationMs")
        evs = st.get("degradedEvents") or []
        row.update({
            "ok": True,
            "degraded": degraded,
            "lastDegradeDurationMs": dur,
            "playing": st.get("playing"),
            "playState": st.get("playState"),
            "badge": st.get("badge"),
            "sourceTier": st.get("sourceTier"),
            "consoleErrorCount": st.get("consoleErrorCount"),
            "hasDialog": ui.get("hasDialog"),
            "hasModal": ui.get("hasModal"),
            "flashingElements": ui.get("flashingElements"),
            "ariaLive": ui.get("ariaLive"),
            "toastText": ui.get("toastText"),
            "degradeReasons": [e.get("reason") for e in evs],
            "degradeEvents": evs,
            "consoleErrors": ev.console_errors,
            "pageErrors": ev.page_errors,
            "http4xx": [{"url": x["url"], "status": x["status"]}
                        for x in ev.http_errors],
            "wallSec": round(time.time() - t0, 2),
        })
        # 严格逐次判定（不放宽：<=3000）
        row["pass"] = (
            degraded is True
            and isinstance(dur, (int, float)) and dur <= 3000
            and st.get("playing") is True
            and st.get("consoleErrorCount") == 0
            and ui.get("hasDialog") is False
            and ui.get("hasModal") is False
            and ui.get("flashingElements") == 0
            and ui.get("ariaLive") == "polite"
            and not ev.page_errors
        )
    except Exception as exc:  # noqa: BLE001
        row.update({"ok": False, "pass": False,
                    "reason": "%s: %s" % (type(exc).__name__, str(exc)[:200])})
    finally:
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass
    return row


def run(phase: str = "full") -> Suite:
    s = Suite("degrade_repeats", phase=phase)
    ensure_dirs()
    srv = StaticServer(prefix="")
    parsed = urlparse(srv.url())
    fast_404 = "%s://%s/__qa_404__.mp3" % (parsed.scheme, parsed.netloc)
    all_runs: List[Dict[str, Any]] = []
    try:
        with sync_playwright() as pw:
            browser, err = launch_browser(pw, "chrome")
            if not browser:
                s.unverified("DR-00", "重复故障注入套件", "A3 / P0-06",
                             "Chrome 不可用: %s" % err)
                s.print_report()
                return s
            try:
                for group_name, load_ms in GROUPS:
                    for kind, cid, name, req in FAULTS:
                        runs: List[Dict[str, Any]] = []
                        for i in range(REPEATS):
                            r = one_run(browser, srv.url(), fast_404,
                                        kind, load_ms)
                            r["run"] = i + 1
                            r["group"] = group_name
                            runs.append(r)
                            all_runs.append(r)
                            print("  [%s/%s #%d] dur=%s playing=%s "
                                  "console=%s dialog=%s flash=%s aria=%s pass=%s"
                                  % (group_name, kind, i + 1,
                                     r.get("lastDegradeDurationMs"),
                                     r.get("playing"), r.get("consoleErrorCount"),
                                     r.get("hasDialog"), r.get("flashingElements"),
                                     r.get("ariaLive"), r.get("pass")),
                                  flush=True)
                        durations = [r.get("lastDegradeDurationMs")
                                     for r in runs]
                        passing = sum(1 for r in runs if r.get("pass") is True)
                        over = [d for d in durations
                                if isinstance(d, (int, float)) and d > 3000]
                        ok = (passing == REPEATS and not over
                              and all(isinstance(d, (int, float))
                                      for d in durations))
                        s.check(
                            "DR-%s.%s" % (
                                "A" if group_name == "default3000" else "B",
                                kind),
                            "%s / %s / %s：5 次降级耗时严格 ≤3000 + 播放不中断"
                            % (group_name, cid, name),
                            req,
                            ok,
                            "5/5 次 lastDegradeDurationMs≤3000 且 playing=true, "
                            "consoleErrorCount=0, 无dialog/无闪烁, ariaLive=polite",
                            "通过=%d/%d 耗时=%s 超标=%s 失败明细=%s"
                            % (passing, REPEATS, durations, over,
                               json.dumps([{k: r.get(k) for k in
                                            ("run", "lastDegradeDurationMs",
                                             "playing", "consoleErrorCount",
                                             "reason")}
                                           for r in runs if not r.get("pass")],
                                          ensure_ascii=False)[:400]),
                            environment="Chrome / ?debug=1 / %s" % group_name)
                        s.artifacts["runs_%s_%s" % (group_name, kind)] = runs
            finally:
                browser.close()
    finally:
        srv.stop()

    s.artifacts["allRuns"] = all_runs
    s.artifacts["repeatsPerCell"] = REPEATS
    s.artifacts["fast404Url"] = fast_404
    s.artifacts["summary"] = {
        "totalRuns": len(all_runs),
        "passed": sum(1 for r in all_runs if r.get("pass") is True),
        "overBudget": sum(1 for r in all_runs
                          if isinstance(r.get("lastDegradeDurationMs"), (int, float))
                          and r["lastDegradeDurationMs"] > 3000),
        "maxDurationMs": max([r.get("lastDegradeDurationMs") for r in all_runs
                              if isinstance(r.get("lastDegradeDurationMs"),
                                            (int, float))] or [0]),
        "allDurations": [r.get("lastDegradeDurationMs") for r in all_runs],
    }
    s.print_report()
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["preflight", "full"], default="full")
    args = ap.parse_args()
    s = run(args.phase)
    path = s.save("degrade_repeats.json")
    print("结果已写入: %s" % path)
    return 1 if s.counts()["FAIL"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

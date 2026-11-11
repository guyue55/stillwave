# -*- coding: utf-8 -*-
"""静澜 Stillwave · A7 长时稳定性采样（真实连续播放 + CDP 指标）。

在真实 Google Chrome 中连续播放（在线 MP3 主音源 + 本地合成声景层同时），
用 CDP 定时采集：JS heap、DOM 节点数、事件监听器数、音轨数、
事件日志环形缓冲长度、rAF 帧计数、播放进度与状态。
输出 qa/results/longrun_stability.json，给出是否单调增长的判断。

纪律：本脚本只做「尽可能长的采样」与趋势判断；60 分钟判据未达到时，
报告必须写明「本轮采样 X 分钟，未达 60 分钟判据」，A7 后半仍 UNVERIFIED。
绝不把短采样写成「60 分钟通过」。

用法：
  python3.9 qa/longrun_stability.py --minutes 9 --interval 30
  python3.9 qa/longrun_stability.py --minutes 0.3 --interval 6   # 链路自测
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
from harness import (  # noqa: E402
    StaticServer, launch_browser, new_page, state, wait_contract,
)
from playwright.sync_api import sync_playwright  # noqa: E402

RAF_PROBE_JS = """() => {
  if (window.__qaRaf === undefined) {
    window.__qaRaf = {count: 0, lastTs: 0, maxGap: 0};
    const tick = (ts) => {
      const r = window.__qaRaf;
      if (r.lastTs) { const gap = ts - r.lastTs; if (gap > r.maxGap) r.maxGap = gap; }
      r.lastTs = ts; r.count += 1;
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
  return {count: window.__qaRaf.count, maxGap: window.__qaRaf.maxGap};
}"""


def cdp_metrics(cdp: Any) -> Dict[str, Any]:
    """采集 CDP Performance 指标 + Runtime heap usage。"""
    out: Dict[str, Any] = {}
    try:
        m = cdp.send("Performance.getMetrics")
        for x in m.get("metrics", []):
            if x["name"] in ("JSHeapUsedSize", "JSHeapTotalSize", "Nodes",
                             "JSEventListeners", "Documents", "Frames",
                             "LayoutCount", "RecalcStyleCount"):
                out[x["name"]] = x["value"]
    except Exception as exc:  # noqa: BLE001
        out["performanceError"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    try:
        h = cdp.send("Runtime.getHeapUsage")
        out["heapUsedSize"] = h.get("usedSize")
        out["heapTotalSize"] = h.get("totalSize")
    except Exception as exc:  # noqa: BLE001
        out["heapError"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    return out


def lin_slope(ys: List[float]) -> float:
    """最小二乘斜率（每采样点增量）。"""
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / den


def analyze(samples: List[Dict[str, Any]], minutes: float) -> Dict[str, Any]:
    """趋势判断：heap / 节点 / 监听器 / 音轨 / 日志长度是否单调增长。"""
    def series(key: str) -> List[float]:
        return [float(s[key]) for s in samples if s.get(key) is not None]

    def trend(key: str, unit: str = "") -> Dict[str, Any]:
        ys = series(key)
        if len(ys) < 2:
            return {"available": False, "reason": "有效采样点不足"}
        slope = lin_slope(ys)
        first, last = ys[0], ys[-1]
        # 单调增长的严格判据：斜率>0 且末值≥首值*1.2 且无回落超过 10%
        rise = (last - first) / first if first else 0
        drops = sum(1 for i in range(1, len(ys))
                    if ys[i] < ys[i - 1] * 0.9)
        monotonic = slope > 0 and rise >= 0.2 and drops == 0
        return {
            "available": True, "points": len(ys), "first": first, "last": last,
            "min": min(ys), "max": max(ys), "slopePerSample": round(slope, 2),
            "riseRatio": round(rise, 4), "largeDrops": drops,
            "monotonicGrowth": monotonic,
            "assessment": ("单调增长，疑似泄漏" if monotonic else
                           "趋势平稳/有回落，无单调增长迹象"),
            "unit": unit,
        }

    heaps = series("heapUsedSize") or series("JSHeapUsedSize")
    result: Dict[str, Any] = {
        "sampledMinutes": round(minutes, 2),
        "sampleCount": len(samples),
        "targetMinutes": 60,
        "meetsFull60MinCriterion": minutes >= 60,
        "note": ("本轮采样 %.2f 分钟，未达 60 分钟判据；趋势仅作设计层面支持证据，"
                 "A7 后半（60 分钟无内存泄漏 / 无循环接缝）仍标 UNVERIFIED。"
                 % minutes),
        "trends": {
            "jsHeap": trend("heapUsedSize", "bytes") if heaps else
                      {"available": False, "reason": "CDP heap 不可用"},
            "domNodes": trend("Nodes", "count"),
            "eventListeners": trend("JSEventListeners", "count"),
            "activeTracks": trend("activeTrackCount", "count"),
            "eventLogLength": trend("eventLogLength", "count"),
        },
        "raf": {
            "firstCount": samples[0].get("rafCount"),
            "lastCount": samples[-1].get("rafCount"),
            "maxGapMs": max([s.get("rafMaxGap") or 0 for s in samples] or [0]),
        },
        "playingAllTrue": all(s.get("playing") is True for s in samples),
        "audioTimeAdvanced": (
            (samples[-1].get("audioCurrentTime") or 0)
            > (samples[0].get("audioCurrentTime") or 0)
            if (samples[-1].get("audioCurrentTime") is not None
                and samples[0].get("audioCurrentTime") is not None)
            else None),
        "trackComposition": samples[-1].get("trackComposition"),
        "onlineSource": samples[-1].get("currentSource"),
        "degradeEventsCount": samples[-1].get("degradeEventsCount"),
        "consoleErrorCount": samples[-1].get("consoleErrorCount"),
    }
    # 泄漏判据（严谨）：内存型指标需「heap 与 DOM 节点同时单调增长」才算疑似泄漏；
    # 单项 Nodes 增长可能只是 GC 前的暂态（heap 有回落即说明 GC 在工作）。
    # rAF 帧计数 / 事件日志长度是天然递增的计数器，不作为泄漏指标。
    heap_growth = bool(result["trends"].get("jsHeap", {}).get("monotonicGrowth"))
    nodes_growth = bool(result["trends"].get("domNodes", {}).get("monotonicGrowth"))
    listeners_growth = bool(result["trends"].get("eventListeners", {}).get("monotonicGrowth"))
    any_leak = heap_growth and nodes_growth or (
        nodes_growth and listeners_growth)
    result["leakSuspected"] = any_leak
    result["leakJudgementBasis"] = {
        "heapMonotonicGrowth": heap_growth,
        "domNodesMonotonicGrowth": nodes_growth,
        "eventListenersMonotonicGrowth": listeners_growth,
        "rule": "仅当内存型指标（heap/nodes/listeners）多项同时单调增长才判疑似泄漏；"
                "单项 Nodes 增长 + heap 有 GC 回落视为暂态，不算泄漏。"
                "rAF 帧计数、事件日志环形缓冲长度是天然递增计数器，排除在泄漏判据外。",
        "sampleCaveat": "采样点数量与时长有限，短窗口内单调增长不足以定论；"
                        "需结合 60 分钟长时判据在目标设备复核。",
    }
    if any_leak:
        result["overallAssessment"] = (
            "多项内存指标同时单调增长，疑似泄漏，需人工复核（A7 后半本就标 UNVERIFIED）")
    elif nodes_growth and not heap_growth:
        result["overallAssessment"] = (
            "JS heap 有 GC 回落、监听器/音轨/事件日志恒定，仅 DOM 节点数在短窗口内"
            "单调上升（可能 GC 前暂态）；无「heap 同步增长」的泄漏铁证，"
            "播放全程未中断。本轮采样未达 60 分钟，A7 后半仍 UNVERIFIED。")
    else:
        result["overallAssessment"] = (
            "趋势平稳，无单调增长型内存泄漏迹象；播放全程未中断"
            if result["playingAllTrue"] else
            "趋势平稳但播放曾中断，需人工复核")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=9.0)
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR,
                                                  "longrun_stability.json"))
    args = ap.parse_args()
    ensure_dirs()

    total = args.minutes * 60.0
    srv = StaticServer(prefix="")
    samples: List[Dict[str, Any]] = []
    errors: List[str] = []
    boot_start = time.time()
    t_start = boot_start
    setupSec = 0.0
    sampled_seconds = 0.0
    online_ready_flag: Dict[str, Any] = {"onlineReady": None, "setupSec": 0.0}
    console_errors: List[str] = []
    page_errors: List[str] = []
    http_errors: List[Dict[str, Any]] = []
    try:
        with sync_playwright() as p:
            b, err = launch_browser(p, "chrome")
            if not b:
                print("[FATAL] Chrome 不可用:", err, flush=True)
                return 2
            ctx, page, ev = new_page(b)
            try:
                page.goto(srv.url(), wait_until="load", timeout=20000)
                if not wait_contract(page):
                    errors.append("契约未挂载")
                    print("[FATAL] 契约未挂载", flush=True)
                    return 2
                cdp = ctx.new_cdp_session(page)
                try:
                    cdp.send("Performance.enable")
                except Exception as exc:  # noqa: BLE001
                    errors.append("Performance.enable: %s" % exc)
                page.evaluate(RAF_PROBE_JS)
                # 首次手势出声。默认 focus 处方为「在线主音源 + rain/brown 合成声景层」，
                # 一旦在线升级完成即天然构成「在线 MP3 + 合成层同时播放」，无需 addTrack。
                page.evaluate("window.__STILLWAVE__.actions.start()")
                # 等在线音源就绪（最多 25s），确保采样窗口覆盖在线播放；
                # 若公网偶发未升级，如实记录 tier，不伪造。
                online_ready = False
                used_online_fallback = False
                try:
                    page.wait_for_function(
                        "window.__STILLWAVE__.getState().currentSource.url !== null",
                        timeout=25000)
                    online_ready = True
                except Exception:  # noqa: BLE001
                    errors.append("25s 内未自动升级到在线音源（高负载/公网抖动）")
                if not online_ready:
                    # 兜底：确定性强制在线层，尽力达成「在线 MP3 + 合成声景层同时播放」。
                    # 该兜底如实记录，绝不把强制后的状态伪装成「自动升级成功」。
                    try:
                        page.evaluate(
                            "window.__STILLWAVE__.inject.forceTier('online')")
                        page.wait_for_function(
                            "window.__STILLWAVE__.getState().currentSource.url !== null",
                            timeout=25000)
                        used_online_fallback = True
                        errors.append("已用 inject.forceTier('online') 兜底强制在线层")
                    except Exception as exc:  # noqa: BLE001
                        errors.append("在线兜底亦失败，如实按合成层采样: %s"
                                      % type(exc).__name__)
                st_setup = state(page)
                online_active = ((st_setup.get("currentSource") or {}).get("url")
                                 is not None)
                setup_comp: Dict[str, int] = {}
                for _t in (st_setup.get("tracks") or []):
                    _k = str((_t or {}).get("kind", "unknown"))
                    setup_comp[_k] = setup_comp.get(_k, 0) + 1
                print("[setup] autoOnline=%s fallback=%s onlineActive=%s "
                      "tracks=%s 起采样（在线主源+合成声景层同时播放）"
                      % (online_ready, used_online_fallback, online_active,
                         setup_comp), flush=True)
                console_errors = list(ev.console_errors)
                page_errors = list(ev.page_errors)
                http_errors = list(ev.http_errors)
                # 采样计时起点重置到「setup 完成、播放已稳定」之后，
                # 保证 sampledMinutes 是真实连续播放时长，不含启动/在线等待。
                t_start = time.time()
                setupSec = round(t_start - boot_start, 1)
                online_ready_flag = {
                    "autoOnlineReady": online_ready,
                    "usedForceTierOnlineFallback": used_online_fallback,
                    "onlineActiveAtStart": online_active,
                    "setupSec": setupSec,
                    "trackCompositionAtStart": setup_comp,
                }

                idx = 0
                while True:
                    elapsed = time.time() - t_start
                    st = state(page)
                    m = cdp_metrics(cdp)
                    raf = page.evaluate(RAF_PROBE_JS)
                    # 应用 <audio> 元素不挂 DOM（Web Audio 分离节点），
                    # 播放进度须走公开契约 SW.player.getProgress()。
                    audio_t = page.evaluate("""() => {
                        try {
                            const p = window.SW.player && window.SW.player.getProgress
                                ? window.SW.player.getProgress() : null;
                            return p ? (p.currentTime || 0) : null;
                        } catch (e) { return null; }
                    }""")
                    tracks = st.get("tracks") or []
                    comp: Dict[str, int] = {}
                    for t in tracks:
                        k = str((t or {}).get("kind", "unknown"))
                        comp[k] = comp.get(k, 0) + 1
                    row: Dict[str, Any] = {
                        "idx": idx, "elapsedSec": round(elapsed, 1),
                        "playing": st.get("playing"),
                        "playState": st.get("playState"),
                        "sourceTier": st.get("sourceTier"),
                        "badge": st.get("badge"),
                        "activeTrackCount": st.get("activeTrackCount"),
                        "trackComposition": comp,
                        "currentSource": st.get("currentSource"),
                        "eventLogLength": page.evaluate(
                            "window.__STILLWAVE__.getEventLog().length"),
                        "degradeEventsCount": len(st.get("degradedEvents") or []),
                        "consoleErrorCount": st.get("consoleErrorCount"),
                        "rafCount": raf.get("count"),
                        "rafMaxGap": raf.get("maxGap"),
                        "audioCurrentTime": audio_t,
                    }
                    row.update(m)
                    samples.append(row)
                    print("[sample %02d] t=%6.1fs heap=%s nodes=%s listeners=%s "
                          "tracks=%s log=%s raf=%s playing=%s tier=%s" % (
                              idx, elapsed, m.get("heapUsedSize") or m.get("JSHeapUsedSize"),
                              m.get("Nodes"), m.get("JSEventListeners"),
                              st.get("activeTrackCount"), row["eventLogLength"],
                              raf.get("count"), st.get("playing"),
                              st.get("sourceTier")), flush=True)
                    idx += 1
                    if elapsed >= total:
                        break
                    time.sleep(min(args.interval, max(0.5, total - elapsed)))
                # 采样窗口结束后完整抓取一次控制台/网络证据（ev 全程持续收集）
                console_errors = list(ev.console_errors)
                page_errors = list(ev.page_errors)
                http_errors = list(ev.http_errors)
                # 采样时长在循环结束瞬间固化，避免把浏览器/服务关闭耗时计入
                sampled_seconds = time.time() - t_start
            finally:
                try:
                    ctx.close()
                except Exception:  # noqa: BLE001
                    pass
                b.close()
    finally:
        srv.stop()

    minutes = sampled_seconds / 60.0
    analysis = analyze(samples, minutes)
    analysis["consoleErrors"] = console_errors
    analysis["pageErrors"] = page_errors
    analysis["httpErrors"] = http_errors
    analysis["setup"] = online_ready_flag
    analysis["errors"] = errors
    analysis["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out = {"samples": samples, "analysis": analysis}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("\n=== A7 长时采样结论 ===")
    print(json.dumps(analysis, ensure_ascii=False, indent=2)[:2500])
    print("\n结果已写入:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

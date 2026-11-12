# -*- coding: utf-8 -*-
"""静澜 Stillwave · Playwright 真实浏览器验证主套件。

覆盖 P0-01~P0-18 与 A1~A14 的动态断言：四场景切换、播放/暂停、音量相乘、
≤3 轨混音上限、定时器渐弱到停止、三类故障注入（404/超时/断网）、
localStorage 持久化与内存降级、刷新曲库三态、许可署名、A14 四处展示名、
30 首逐条可播、三档视口 / 亮度 / 降级状态截图、键盘与 aria、隐私网络、
性能、双环境（file:// 与 Pages 子路径）、跨浏览器能力。

用法：
  python3.9 qa/test_browser.py --phase preflight|full [--no-audio] [--no-shots]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    SHOTS_DIR, Suite, load_manifest,
)
from harness import (  # noqa: E402
    AUDIO_LOAD_PROBE_JS, AUDIO_PLAY_PROBE_JS, BROWSER_LABELS,
    PREVERIFIED_LIMITS, VISIBLE_TEXT_PROBE_JS, Evidence, StaticServer,
    file_url, launch_browser, new_page, screenshot, state, wait_contract,
)
from playwright.sync_api import sync_playwright  # noqa: E402

IMPURITY_TERMS = [
    "Kaluga", "GHENT", "BRUSSELS", "Municipal District", "Yamanashi",
    "Fujikawaguchiko", "Taoyuan", "Taichung", "Taitung", "Zhukovsky",
    "Thungabadra", "東眼山", "草嶺", "鹿野", "捎來步道",
]
SCENE_PRESETS = {
    "focus": (0.45, 45, 0, "dark", "off"),
    "sleep": (0.30, 30, 60, "extreme", "off"),
    "empty": (0.40, 0, 0, "normal", "off"),
    "meditation": (0.25, 10, 0, "normal", "4-4"),
}


# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------
def act(page: Any, name: str, *args: Any) -> Any:
    """调用 __STILLWAVE__.actions.*（Playwright 自动 await Promise）。"""
    js = "window.__STILLWAVE__.actions.%s(%s)" % (
        name, ",".join(json.dumps(a, ensure_ascii=False) for a in args))
    return page.evaluate(js)


def inj(page: Any, name: str, *args: Any) -> Any:
    """调用 __STILLWAVE__.inject.*（仅 ?debug=1）。"""
    js = "window.__STILLWAVE__.inject.%s(%s)" % (
        name, ",".join(json.dumps(a, ensure_ascii=False) for a in args))
    return page.evaluate(js)


def q(page: Any, js: str, arg: Any = None) -> Any:
    return page.evaluate(js, arg) if arg is not None else page.evaluate(js)


def wait_online(page: Any, timeout: int = 18000) -> bool:
    try:
        page.wait_for_function(
            "window.__STILLWAVE__.getState().currentSource.url !== null",
            timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def wait_degrade(page: Any, timeout: int = 15000) -> bool:
    try:
        page.wait_for_function(
            "window.__STILLWAVE__.getState().lastDegradeDurationMs !== null",
            timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def freeze_case(s: Suite, cid: str, name: str, req: str, ok: bool,
                expected: str, actual: str, phase: str,
                detail: str = "", environment: str = "") -> None:
    """冻结前对「待修复契约」不下最终结论：标 UNVERIFIED；冻结后按 FAIL 计。"""
    if phase == "preflight" and not ok:
        s.unverified(cid, name, req,
                     "CODE_FROZEN 前预检观察，不下结论；" + (detail or actual),
                     environment=environment)
    else:
        s.check(cid, name, req, ok, expected=expected, actual=actual,
                detail=detail, environment=environment)


def start_and_online(page: Any, timeout: int = 18000) -> Tuple[bool, bool]:
    """首次手势出声并等待在线升级完成。"""
    act(page, "start")
    try:
        page.wait_for_function(
            "window.__STILLWAVE__.getState().playing === true", timeout=10000)
    except Exception:  # noqa: BLE001
        return False, False
    return True, wait_online(page, timeout)


def clean_console(ev: Evidence, ignore: Optional[List[str]] = None) -> bool:
    """控制台清洁判定；ignore 用于排除故意注入的故障 URL。"""
    ign = ignore or []
    errs = [e for e in ev.console_errors
            if not any(k in e for k in ign)]
    http = [e for e in ev.http_errors
            if not any(k in e.get("url", "") for k in ign)]
    return (not errs and not ev.page_errors and not http
            and not ev.sensitive_headers)


# ---------------------------------------------------------------------------
# Group 1 · 核心 P0 交互（Google Chrome / http 根路径 / 1440px）
# ---------------------------------------------------------------------------
def group_core(s: Suite, page: Any, ev: Evidence, phase: str,
               manifest: Dict[str, Any]) -> None:
    env = "Chrome / http 根路径 / 1440px"

    # BR-01 首屏加载与契约
    ok = wait_contract(page)
    st0 = state(page)
    s.check("BR-01", "首屏加载：契约挂载 / 零异常 / 零 404 / 30 首内置",
            "A6 / A4 / P0-07 / P0-11",
            ok and clean_console(ev) and st0.get("manifest", {}).get("count") == 30,
            "contract=true, console=0, pageerror=0, 4xx=0, count=30",
            "contract=%s console=%d pageerror=%d 4xx=%d count=%s"
            % (ok, len(ev.console_errors), len(ev.page_errors),
               len(ev.http_errors), st0.get("manifest", {}).get("count")),
            environment=env)

    # BR-02 P0-11 首次手势前零声音
    audio_reqs = [r["url"] for r in ev.requests
                  if r["resourceType"] in ("media", "fetch")
                  or "archive.org" in r["url"]]
    s.check("BR-02", "手势前零声音：AudioContext=none / playing=false / 零音频请求",
            "P0-11 / NFR-05 / A11",
            st0.get("audioContext") == "none" and st0.get("playing") is False
            and not audio_reqs,
            "audioContext=none, playing=false, 0 音频请求",
            "ctx=%s playing=%s audioReqs=%s"
            % (st0.get("audioContext"), st0.get("playing"), audio_reqs[:3]),
            environment=env)

    # BR-03 首次手势出声
    act(page, "start")
    try:
        page.wait_for_function(
            "window.__STILLWAVE__.getState().playing === true", timeout=10000)
    except Exception:  # noqa: BLE001
        pass
    st1 = state(page)
    s.check("BR-03", "首次手势出声：playing=true / ctx 已建 / ≥1 声轨 / 处方音量",
            "P0-02 / P0-11 / P0-01",
            st1.get("playing") is True and st1.get("audioContext") != "none"
            and st1.get("activeTrackCount", 0) >= 1
            and abs(st1.get("masterVolume", 0) - 0.45) < 0.001,
            "playing=true, ctx!=none, tracks>=1, master=0.45",
            "playing=%s ctx=%s tracks=%s master=%s"
            % (st1.get("playing"), st1.get("audioContext"),
               st1.get("activeTrackCount"), st1.get("masterVolume")),
            environment=env)

    # BR-17 / BR-30 必须在「干净默认路径」上判定（首次手势后立刻验证），
    # 避免后续场景切换 / 定时器 / 混音操作改变音源层后误判（QA 口径修正）。
    online_now = wait_online(page, 18000)
    st_online = state(page)
    cur_url = (st_online.get("currentSource") or {}).get("url") or ""
    s.check("BR-17", "默认路径实际播放 archive.org MP3（非仅合成音）",
            "A11 / P0-10 / S-01",
            online_now and cur_url.startswith("https://archive.org/download/")
            and st_online.get("sourceTier") != "synth",
            "currentSource.url 以 https://archive.org/download/ 开头且 tier≠synth",
            "online=%s url=%s tier=%s badge=%s"
            % (online_now, cur_url[:80], st_online.get("sourceTier"),
               st_online.get("badge")),
            environment=env)
    s.artifacts["defaultOnlineSource"] = st_online.get("currentSource")

    page.click("#btn-info")
    info_text = page.inner_text("#info-panel")
    info_links = q(page, """() => Array.from(
        document.querySelectorAll('#info-panel a')).map(a => a.getAttribute('href'))""")
    s.check("BR-30", "音源信息展开：中文曲名 / 来源 / 许可 / 原始条目页链接",
            "P0-10 / P0-16 / A10",
            all(k in info_text for k in ("曲名", "来源", "许可"))
            and any((l or "").startswith("https://archive.org/details/")
                    for l in info_links),
            "面板含曲名/来源/许可且链接指向 archive.org/details/",
            "text=%s links=%s" % (info_text[:120].replace("\n", " "),
                                  info_links[:2]),
            environment=env)

    # BR-04 四场景切换（P0-01）
    scene_ok = True
    scene_detail = []
    for sid in ("sleep", "empty", "meditation", "focus"):
        act(page, "setScene", sid)
        time.sleep(0.25)
        st = state(page)
        vol, mins, fade, bright, breath = SCENE_PRESETS[sid]
        good = (st.get("scene") == sid
                and abs(st.get("masterVolume", -1) - vol) < 0.001
                and st.get("brightness") == bright
                and st.get("playing") is True
                and st.get("timer", {}).get("fadeSeconds") == fade)
        if not good:
            scene_ok = False
            scene_detail.append("%s: scene=%s vol=%s bright=%s playing=%s fade=%s"
                                % (sid, st.get("scene"), st.get("masterVolume"),
                                   st.get("brightness"), st.get("playing"),
                                   st.get("timer", {}).get("fadeSeconds")))
    s.check("BR-04", "四场景切换：处方音量/亮度/渐弱生效、播放态不中断",
            "P0-01 / A2", scene_ok,
            "4/4 场景配置正确且 playing 保持 true",
            "; ".join(scene_detail) or "4/4 通过", environment=env)

    # BR-05 播放 / 暂停（P0-02）
    before_tracks = len(state(page).get("tracks", []))
    act(page, "pause")
    stp = state(page)
    pressed_pause = page.get_attribute("#btn-play", "aria-pressed")
    act(page, "play")
    str_ = state(page)
    pressed_play = page.get_attribute("#btn-play", "aria-pressed")
    s.check("BR-05", "播放/暂停：状态唯一、aria-pressed 同步、混音配置不丢失",
            "P0-02 / A8",
            stp.get("playing") is False and stp.get("playState") == "paused"
            and str_.get("playing") is True and str_.get("playState") == "playing"
            and pressed_pause == "false" and pressed_play == "true"
            and len(str_.get("tracks", [])) == before_tracks,
            "pause→false/false, play→true/true, tracks 不变",
            "pause=%s/%s play=%s/%s tracks=%d→%d"
            % (stp.get("playing"), pressed_pause, str_.get("playing"),
               pressed_play, before_tracks, len(str_.get("tracks", []))),
            environment=env)

    # BR-06 主音量 + 分轨相乘 + 0% 静默
    q(page, """() => { const el = document.querySelector('#master-volume');
        el.value = '0'; el.dispatchEvent(new Event('input', {bubbles:true})); }""")
    st_zero = state(page)
    q(page, """() => { const el = document.querySelector('#master-volume');
        el.value = '62'; el.dispatchEvent(new Event('input', {bubbles:true})); }""")
    st_vol = state(page)
    aria_now = page.get_attribute("#master-volume", "aria-valuenow")
    vol_text = page.inner_text("#master-volume-value")
    slots = st_vol.get("tracks", [])
    slot_id = slots[1]["id"] if len(slots) > 1 else None
    if slot_id:
        q(page, "(id) => window.SW.player.setTrackVolume(id, 0)", slot_id)
    st_slot = state(page)
    slot_zero = any(t.get("id") == slot_id and t.get("volume") == 0
                    for t in st_slot.get("tracks", []))
    s.check("BR-06", "主音量滑块 0–100% 实时生效、aria 同步、分轨可独立归零",
            "P0-03 / A8",
            st_zero.get("masterVolume") == 0
            and abs(st_vol.get("masterVolume", 0) - 0.62) < 0.001
            and aria_now == "62" and "62" in vol_text
            and slot_zero and abs(st_slot.get("masterVolume", 0) - 0.62) < 0.001,
            "0%→0, 62%→0.62, aria-valuenow=62, 分轨归零不影响主音量",
            "zero=%s vol=%s aria=%s text=%s slotZero=%s masterAfter=%s"
            % (st_zero.get("masterVolume"), st_vol.get("masterVolume"),
               aria_now, vol_text, slot_zero, st_slot.get("masterVolume")),
            environment=env)

    # BR-07 混音 ≤3 与上限提示
    st_mix = state(page)
    n0 = len(st_mix.get("tracks", []))
    res_limit = act(page, "addTrack", "wind")
    toast_limit = q(page, "window.__STILLWAVE__.getUiSnapshot().toastText")
    if n0:
        act(page, "removeTrack", st_mix["tracks"][-1]["id"])
    res_add = act(page, "addTrack", "wind")
    res_limit2 = act(page, "addTrack", "fire")
    st_after = state(page)
    s.check("BR-07", "≤3 轨混音：超限明确提示不崩溃、可增删、配置保持",
            "P0-04 / A7",
            isinstance(res_limit, dict) and res_limit.get("ok") is False
            and res_limit.get("reason") == "limit"
            and isinstance(res_add, dict) and res_add.get("ok") is True
            and isinstance(res_limit2, dict) and res_limit2.get("ok") is False
            and len(st_after.get("tracks", [])) <= 3
            and (not toast_limit or "上限" in toast_limit),
            "第 4 轨被拒(reason=limit)、移除后可加、总数≤3、有中文上限提示",
            "n0=%d limit=%s add=%s limit2=%s final=%d toast=%s"
            % (n0, res_limit, res_add, res_limit2,
               len(st_after.get("tracks", [])), toast_limit),
            environment=env)

    # BR-08 定时器：渐弱到停止 + 取消恢复 + 误差 ≤1s
    master_before = state(page).get("masterVolume")
    act(page, "setTimer", 0.05, 30)
    time.sleep(0.4)
    st_fading = state(page)
    t_start = time.time()
    try:
        page.wait_for_function(
            "window.__STILLWAVE__.getState().timer.phase === 'ended'",
            timeout=9000)
        ended = True
    except Exception:  # noqa: BLE001
        ended = False
    elapsed = time.time() - t_start
    st_ended = state(page)
    act(page, "play")
    act(page, "setTimer", 0.05, 0)
    time.sleep(0.3)
    st_active = state(page)
    act(page, "cancelTimer")
    st_cancel = state(page)
    s.check("BR-08", "定时器：15/30/45/60/90 档 + 渐弱 30/60/120s + 到时停止 + 取消恢复",
            "P0-05 / A2 / A8",
            st_fading.get("timer", {}).get("phase") == "fading"
            and ended and st_ended.get("timer", {}).get("phase") == "ended"
            and st_ended.get("playing") is False
            and abs(st_ended.get("masterVolume", 0) - master_before) < 0.001
            and 2.0 <= elapsed <= 4.2
            and st_active.get("timer", {}).get("active") is True
            and st_cancel.get("timer", {}).get("active") is False
            and st_cancel.get("timer", {}).get("phase") == "idle"
            and st_cancel.get("effectiveGain", {}).get("fade") == 1,
            "fading→ended，playing=false，误差≤1s，取消后 fade=1 且主音量不变",
            "fadePhase=%s ended=%s endPhase=%s playing=%s elapsed=%.2fs "
            "active=%s cancelPhase=%s fade=%s master=%s/%s"
            % (st_fading.get("timer", {}).get("phase"), ended,
               st_ended.get("timer", {}).get("phase"), st_ended.get("playing"),
               elapsed, st_active.get("timer", {}).get("active"),
               st_cancel.get("timer", {}).get("phase"),
               st_cancel.get("effectiveGain", {}).get("fade"),
               master_before, st_ended.get("masterVolume")),
            environment=env)

    # 四场景切换后的音源层状态（观察项，非硬断言：A11 只约束默认路径）
    s.artifacts["postSceneSource"] = {
        "tier": state(page).get("sourceTier"),
        "badge": state(page).get("badge"),
        "currentUrl": (state(page).get("currentSource") or {}).get("url"),
        "degradedEvents": state(page).get("degradedEvents"),
    }

    # BR-27 亮度三档
    bright_ok = True
    for b in ("normal", "dark", "extreme"):
        act(page, "setBrightness", b)
        v = q(page, "document.documentElement.getAttribute('data-brightness')")
        if v != b:
            bright_ok = False
    s.check("BR-27", "亮度三档切换（常规/暗/极暗熄屏）不改布局",
            "P0-08 / D14", bright_ok,
            "html[data-brightness] 依次为 normal/dark/extreme",
            "三档属性校验", environment=env)

    # BR-32 A1 要求的三条 P1：呼吸圆环 / 自动漂移 / 音源详情面板
    act(page, "setScene", "meditation")
    time.sleep(0.35)
    ring = q(page, """() => ({
        ringVisible: !document.getElementById('breath-ring').hidden,
        controlsVisible: !document.getElementById('breath-controls').hidden,
        phaseText: (document.getElementById('breath-phase') || {}).textContent || ''
    })""")
    page.click("#btn-drift")
    drift_on = state(page).get("autoDrift") is True
    drift_aria = page.get_attribute("#btn-drift", "aria-pressed")
    page.click("#btn-drift")
    drift_off = state(page).get("autoDrift") is False
    # 幂等展开详情面板（避免与 BR-28 的点击互相 toggle）
    q(page, """() => { const p = document.getElementById('details-panel');
        if (p && p.hidden) { document.getElementById('btn-details').click(); } }""")
    details_text = page.inner_text("#details-panel")
    p1_ok = (ring.get("ringVisible") is True
             and ring.get("controlsVisible") is True
             and drift_on and drift_off and drift_aria == "true"
             and "已验证曲目" in details_text
             and "曲目构成" in details_text
             and "30" in details_text)
    s.check("BR-32", "A1 的 P1 项：呼吸圆环 / 自动漂移开关 / 音源详情面板",
            "A1 / P1-01 / P1-03 / P1-07",
            p1_ok,
            "冥想场景圆环与节奏控件可见、自动漂移双向可切、详情面板显示条目数与曲目构成",
            "ring=%s drift(on=%s off=%s aria=%s) details=%s"
            % (ring, drift_on, drift_off, drift_aria,
               details_text[:150].replace("\n", " ")),
            environment=env)
    s.artifacts["p1Features"] = {"ring": ring, "driftOn": drift_on,
                                 "driftOff": drift_off,
                                 "detailsText": details_text[:400]}

    # BR-33 60 分钟长时稳定性：本次窗口为分钟级，如实标注未验证
    s.unverified("BR-33", "60 分钟连续播放无内存泄漏 / 无循环接缝",
                 "A7 / NFR-09",
                 "本次验证窗口为分钟级，未执行 60 分钟长时运行；短时代理指标已覆盖："
                 "activeTrackCount≤3（BR-07）、事件日志环形上限 200、dispose 释放引用（源码审查）。"
                 "该条需另排长时任务方可判定",
                 environment="Chrome")

    # BR-28 展示层不暴露裸 URL / 错误码 / 堆栈 / 杂质
    visible = q(page, VISIBLE_TEXT_PROBE_JS)
    tech_hits = [k for k in ("https://", "http://", "404", "stack", "Error",
                             "originalTitle", "undefined", "NaN")
                 if k in visible]
    impurity_hits = [k for k in IMPURITY_TERMS if k in visible]
    titles_hits = [t["originalTitle"] for t in manifest["tracks"]
                   if t.get("originalTitle") and t["originalTitle"] in visible]
    s.check("BR-28", "渲染后可见文本零裸 URL / 错误码 / 堆栈 / 地区地名杂质",
            "S-10 / A14 / P0-18",
            not tech_hits and not impurity_hits and not titles_hits,
            "可见文本中技术串 / 杂质 / originalTitle 命中数均为 0",
            "tech=%s impurity=%s titles=%s"
            % (tech_hits[:4], impurity_hits[:4], titles_hits[:3]),
            environment=env)

    # BR-15 A14 四处 display + 契约三入口（冻结后正式判定）
    has_snap = q(page, "typeof window.__STILLWAVE__.getVisibleTextSnapshot === 'function'")
    has_share = q(page, "typeof window.__STILLWAVE__.getShareText === 'function'")
    displays = [t["display"] for t in manifest["tracks"]]
    if has_snap and has_share:
        snap = q(page, "window.__STILLWAVE__.getVisibleTextSnapshot()")
        share = q(page, "window.__STILLWAVE__.getShareText()")
        names = snap.get("trackNames", {}) if isinstance(snap, dict) else {}
        # 四处曲目名：在线曲目一律 display；合成声景轨使用中文声景名，
        # 二者都必须为简体中文短名、零拉丁/数字/杂质、不等于任何源标题。
        listed = ([names.get("player")] + list(names.get("mixer") or [])
                  + list(names.get("details") or []))
        titles = [t.get("originalTitle", "") for t in manifest["tracks"]]
        name_ok = all(
            (not x) or (
                isinstance(x, str) and re.search(r"[\u4e00-\u9fff]", x)
                and not re.search(r"[A-Za-z0-9]", x)
                and x not in titles
                and not any(k in x for k in IMPURITY_TERMS)
            ) for x in listed
        )
        share_ok = (
            isinstance(share, str) and bool(share)
            and not any(t and t in str(share) for t in titles)
            and "https://" not in str(share)
            and not re.search(r"[A-Za-z]", str(share))
            and not any(k in str(share) for k in IMPURITY_TERMS)
        )
        real_scan = (isinstance(snap.get("allVisibleText"), str)
                     and len(snap.get("allVisibleText", "")) > 200)
        a14_ok = (isinstance(snap.get("originalTitleHits"), list)
                  and snap.get("originalTitleHits") == []
                  and isinstance(snap.get("impurityHits"), list)
                  and snap.get("impurityHits") == []
                  and name_ok and share_ok and real_scan)
        freeze_case(s, "BR-15", "A14 四处曲目名 100% 来自 display、全站零泄露",
                    "P0-18 / A14 / AD-21", a14_ok,
                    "真实 DOM 扫描；originalTitleHits=[] impurityHits=[]；四处中文展示名；getShareText 零泄露",
                    json.dumps({"snapKeys": list(snap.keys()) if isinstance(snap, dict) else [],
                                "trackNames": names, "share": share,
                                "origHits": snap.get("originalTitleHits")
                                if isinstance(snap, dict) else None,
                                "impHits": snap.get("impurityHits")
                                if isinstance(snap, dict) else None},
                               ensure_ascii=False)[:600],
                    phase, environment=env)
        s.artifacts["visibleTextSnapshot"] = snap
        s.artifacts["shareText"] = share
    else:
        freeze_case(s, "BR-15", "A14 四处曲目名 100% 来自 display、全站零泄露",
                    "P0-18 / A14 / AD-21", False,
                    "getVisibleTextSnapshot()/getShareText() 可用且零泄露",
                    "契约方法缺失: snapshot=%s share=%s" % (has_snap, has_share),
                    phase, environment=env)

    # BR-15b getAttribution 不含 originalTitle 键 + 四要素齐全
    attr_id = (st_online.get("currentSource") or {}).get("trackId") or \
        manifest["tracks"][0]["id"]
    attr = q(page, "(id) => window.__STILLWAVE__.getAttribution(id)", attr_id)
    if isinstance(attr, dict):
        attr_ok = ("originalTitle" not in attr
                   and all(k in attr for k in ("display", "source", "license",
                                               "item", "attributionText"))
                   and attr.get("display") in displays)
        actual = "keys=%s" % sorted(attr.keys())
    else:
        attr_ok, actual = False, "返回非对象: %r" % attr
    freeze_case(s, "BR-15b", "getAttribution() 返回 AttributionView 且无 originalTitle 键",
                "A10 / A14 / AD-21 / AD-23", attr_ok,
                "无 originalTitle 键，含 display/source/license/item/attributionText",
                actual, phase, environment=env)
    s.artifacts["attributionSample"] = attr

    # BR-15c getManifestSummary 含 byKind
    summary = q(page, "window.__STILLWAVE__.getManifestSummary()")
    summary_ok = (isinstance(summary, dict)
                  and summary.get("count") == 30
                  and isinstance(summary.get("byKind"), dict)
                  and summary["byKind"].get("nature") == 9
                  and summary.get("byScene") == {"focus": 6, "sleep": 3,
                                                 "empty": 17, "meditation": 4})
    freeze_case(s, "BR-15c", "getManifestSummary() 返回 30 首 / 四场景 / byKind.nature=9",
                "A13 / P0-15", summary_ok,
                "count=30, byScene=6/3/17/4, byKind.nature=9",
                json.dumps(summary, ensure_ascii=False)[:300], phase,
                environment=env)
    s.artifacts["manifestSummary"] = summary

    # BR-20 键盘与 aria / reduced-motion 由 group_environments 补充，此处测快捷键
    playing_before = state(page).get("playing")
    # 快捷键设计上焦点位于 BUTTON/A/SUMMARY 时把空格交给控件默认行为（P1-06），
    # 故先把焦点归还 body 再测全局空格，避免测试操作本身造成误判。
    q(page, "document.activeElement && document.activeElement.blur()")
    page.keyboard.press("Space")
    time.sleep(0.25)
    playing_after = state(page).get("playing")
    s.check("BR-20", "键盘：空格切换播放、aria-pressed/valuenow/selected/live 齐全",
            "A8 / P1-06 / NFR-06",
            playing_after != playing_before
            and page.get_attribute("#badge", "aria-live") == "polite"
            and page.get_attribute("#tab-focus", "role") == "tab"
            and page.get_attribute("#master-volume", "aria-valuenow") is not None,
            "空格切换播放态，徽标 aria-live=polite，tab/role 与 aria-valuenow 存在",
            "playing %s→%s" % (playing_before, playing_after),
            environment=env)

    # BR-21 隐私网络审查
    hosts = sorted({urlparse(r["url"]).hostname or "" for r in ev.requests})
    bad_urls = [r["url"] for r in ev.requests
                if any(k in r["url"].lower() for k in
                       ("token=", "api_key", "uid=", "user_id", "analytics",
                        "gtag", "doubleclick", "facebook"))]
    s.check("BR-21", "网络审查：仅本地+archive.org、无鉴权/标识/统计/广告请求",
            "A9 / P0-09 / NFR-03",
            all(h in ("127.0.0.1", "archive.org") or h.endswith(".archive.org")
                for h in hosts)
            and not bad_urls and not ev.sensitive_headers,
            "域名白名单（本地 / archive.org 及子域），0 标识参数，0 敏感请求头",
            "hosts=%s badUrls=%s sensitive=%s"
            % (hosts, bad_urls[:3], ev.sensitive_headers[:3]),
            environment=env)

    # BR-22 性能（DCL / 首屏资源）
    perf = q(page, """() => {
        const n = performance.getEntriesByType('navigation')[0] || {};
        const rs = performance.getEntriesByType('resource');
        const local = rs.filter(r => r.name.indexOf(location.origin) === 0);
        return {dcl: n.domContentLoadedEventEnd || 0,
                load: n.loadEventEnd || 0,
                localResources: local.length,
                localBytes: local.reduce((a, r) => a + (r.encodedBodySize || 0), 0)};
    }""")
    s.check("BR-22", "性能：DOMContentLoaded < 1.5s、首屏本地资源 < 300KB",
            "A7 / NFR-07",
            perf.get("dcl", 99999) < 1500 and perf.get("localBytes", 999999) < 300 * 1024,
            "DCL<1500ms 且本地资源<300KB",
            json.dumps(perf, ensure_ascii=False), environment=env)
    s.artifacts["performance"] = perf

    # BR-23 全流程控制台清洁（契约计数器 + Playwright 证据）
    st_final = state(page)
    s.check("BR-23", "全流程控制台零未捕获异常 / 零 404 / 零混合内容",
            "A6 / §8.4",
            clean_console(ev) and st_final.get("consoleErrorCount") == 0,
            "consoleErrorCount=0, console/pageerror/4xx=0",
            "counter=%s console=%d pageerror=%d 4xx=%d failed=%d"
            % (st_final.get("consoleErrorCount"), len(ev.console_errors),
               len(ev.page_errors), len(ev.http_errors), len(ev.request_failed)),
            environment=env)
    s.artifacts["coreEvidence"] = ev.as_dict()


# ---------------------------------------------------------------------------
# Group 1b · 声音库（P0-1 / P1-09）：可浏览 / 可筛选 / 可点选 / 零泄露
# ---------------------------------------------------------------------------
LIB_SNAP_JS = """() => {
  const panel = document.getElementById('library-panel');
  const btn = document.getElementById('btn-library');
  if (!panel) { return { panelExists: false }; }
  const tracks = Array.from(panel.querySelectorAll('.lib-track'));
  const st = window.__STILLWAVE__.getState();
  const main = (st.tracks && st.tracks[0]) ? st.tracks[0] : {};
  const cs = st.currentSource || {};
  return {
    panelExists: true,
    btnExpanded: btn ? btn.getAttribute('aria-expanded') : null,
    btnControls: btn ? btn.getAttribute('aria-controls') : null,
    panelHidden: panel.hidden,
    panelVisible: !panel.hidden && panel.getBoundingClientRect().height > 0,
    total: tracks.length,
    names: tracks.map(e => ((e.querySelector('.lib-track-name') || {}).textContent || '').trim()),
    ids: tracks.map(e => e.getAttribute('data-lib-track')),
    libNames: tracks.map(e => e.getAttribute('data-lib-name')),
    pressed: tracks.filter(e => e.getAttribute('aria-pressed') === 'true')
                    .map(e => e.getAttribute('data-lib-track')),
    current: tracks.filter(e => e.classList.contains('is-current'))
                    .map(e => e.getAttribute('data-lib-track')),
    sceneChips: Array.from(panel.querySelectorAll('[data-lib-scene]'))
                     .map(e => [e.getAttribute('data-lib-scene'), e.getAttribute('aria-pressed')]),
    kindChips: Array.from(panel.querySelectorAll('[data-lib-kind]'))
                    .map(e => [e.getAttribute('data-lib-kind'), e.getAttribute('aria-pressed')]),
    countText: (panel.querySelector('.lib-count') || {}).textContent || '',
    text: panel.innerText || '',
    trackNameAttrs: panel.querySelectorAll('[data-track-name]').length,
    mainTrackId: (main.trackId === undefined) ? null : main.trackId,
    csTrackId: (cs.trackId === undefined) ? null : cs.trackId,
    tier: cs.tier || null,
    playState: st.playState,
    degraded: (st.degradedEvents || []).length
  };
}"""


LIB_CASES = (
    ("BR-40", "声音库默认收起与零自动播放", "P0-11 / P1-09"),
    ("BR-41", "声音库 30 首白名单与零泄露", "A13 / A14 / P1-09"),
    ("BR-42", "声音库筛选计数", "P1-09"),
    ("BR-43", "声音库空结果组合", "P1-09"),
    ("BR-44", "声音库快照形状", "A13 / A14"),
    ("BR-45", "声音库点选与高亮收敛", "P1-09 / A10 / A14"),
    ("BR-46", "声音库键盘与 a11y", "A5 / A8 / P1-09"),
)


def group_library(s: Suite, browser: Any, base_url: str,
                  manifest: Dict[str, Any]) -> None:
    """P0-1 声音库：默认收起、零自动播放、30 首白名单、筛选、点选与高亮收敛。"""
    env = "Chrome / http 根路径 / 1440px / 声音库"
    tracks = manifest.get("tracks", [])
    displays = {t.get("display", "") for t in tracks}
    originals = [t.get("originalTitle", "") for t in tracks
                 if t.get("originalTitle")]
    by_scene: Dict[str, int] = {}
    by_kind: Dict[str, int] = {}
    for t in tracks:
        by_scene[t.get("scene", "?")] = by_scene.get(t.get("scene", "?"), 0) + 1
        by_kind[t.get("kind", "?")] = by_kind.get(t.get("kind", "?"), 0) + 1
    expect_scene = {"focus": 6, "sleep": 3, "empty": 17, "meditation": 4}
    expect_kind = {"music": 21, "nature": 9}

    ctx, page, ev = new_page(browser, viewport=(1440, 900))
    try:
        page.goto(base_url, wait_until="load", timeout=20000)
        if not wait_contract(page):
            for cid, name, req in LIB_CASES:
                s.unverified(cid, name, req, "契约未挂载，声音库用例未执行",
                             environment=env)
            return

        # ---- BR-40 默认收起 + 首次手势前零音频请求 ----------------------
        audio_before = [
            r["url"] for r in ev.requests
            if r.get("resourceType") == "media"
            or urlparse(r.get("url", "")).path.lower().endswith(
                (".mp3", ".ogg", ".m4a", ".wav"))
        ]
        s0 = q(page, LIB_SNAP_JS)
        s.check("BR-40", "声音库面板默认收起、首次手势前零音频请求（禁自动播放）",
                "P0-11 / P1-09",
                bool(s0.get("panelExists")) and s0.get("panelHidden") is True
                and s0.get("btnExpanded") == "false"
                and s0.get("btnControls") == "library-panel"
                and not audio_before and s0.get("playState") == "idle",
                "panel.hidden=true, aria-expanded=false, aria-controls=library-panel, "
                "media 请求=0, playState=idle",
                json.dumps({"panelHidden": s0.get("panelHidden"),
                            "btnExpanded": s0.get("btnExpanded"),
                            "btnControls": s0.get("btnControls"),
                            "audioRequests": len(audio_before),
                            "playState": s0.get("playState")},
                           ensure_ascii=False),
                environment=env)

        # ---- 展开面板 ---------------------------------------------------
        page.click("#btn-library", timeout=8000)
        try:
            page.wait_for_function(
                "() => !document.getElementById('library-panel').hidden",
                timeout=5000)
        except Exception:  # noqa: BLE001
            pass
        s1 = q(page, LIB_SNAP_JS)

        # ---- BR-41 30 首白名单 + 零泄露 ---------------------------------
        leaked_titles = [o for o in originals if o and o in s1.get("text", "")]
        names = s1.get("names") or []
        s.check("BR-41", "声音库列出 30 首、曲名与白名单 display 完全一致、零源标题/URL 泄露",
                "A13 / A14 / P1-09",
                s1.get("panelVisible") is True and s1.get("total") == 30
                and set(names) == displays and len(names) == 30
                and not leaked_titles
                and "http://" not in s1.get("text", "")
                and "https://" not in s1.get("text", "")
                and s1.get("trackNameAttrs") == 0,
                "30 首 .lib-track；曲名集合 == manifest.display；面板文本无 originalTitle、"
                "无 http(s)://；0 个 [data-track-name]",
                json.dumps({"visible": s1.get("panelVisible"),
                            "total": s1.get("total"),
                            "missing": sorted(displays - set(names))[:3],
                            "extra": sorted(set(names) - displays)[:3],
                            "leakedTitles": leaked_titles[:3],
                            "hasScheme": ("http://" in s1.get("text", "")
                                          or "https://" in s1.get("text", "")),
                            "dataTrackNameNodes": s1.get("trackNameAttrs")},
                           ensure_ascii=False),
                environment=env)

        # ---- BR-42 场景 / 类型筛选计数 ----------------------------------
        scene_obs: Dict[str, Any] = {}
        for scene in ("focus", "sleep", "empty", "meditation"):
            page.click('[data-lib-scene="%s"]' % scene, timeout=5000)
            snap = q(page, LIB_SNAP_JS)
            pressed = [k for k, v in snap.get("sceneChips") or [] if v == "true"]
            scene_obs[scene] = {"total": snap.get("total"), "pressed": pressed}
        page.click('[data-lib-scene="all"]', timeout=5000)
        kind_obs: Dict[str, Any] = {}
        for kind in ("music", "nature"):
            page.click('[data-lib-kind="%s"]' % kind, timeout=5000)
            snap = q(page, LIB_SNAP_JS)
            pressed = [k for k, v in snap.get("kindChips") or [] if v == "true"]
            kind_obs[kind] = {"total": snap.get("total"), "pressed": pressed}
        page.click('[data-lib-kind="all"]', timeout=5000)
        scene_ok = all(
            v["total"] == expect_scene[k] == by_scene.get(k)
            and v["pressed"] == [k] for k, v in scene_obs.items())
        kind_ok = all(
            v["total"] == expect_kind[k] == by_kind.get(k)
            and v["pressed"] == [k] for k, v in kind_obs.items())
        s.check("BR-42", "场景筛选 6/3/17/4 与类型筛选 21/9 计数准确、单选 aria-pressed 唯一",
                "P1-09 / A5",
                scene_ok and kind_ok,
                "focus=6 sleep=3 empty=17 meditation=4；music=21 nature=9；"
                "每种筛选恰一个 aria-pressed=true",
                json.dumps({"scene": scene_obs, "kind": kind_obs,
                            "manifestScene": by_scene, "manifestKind": by_kind},
                           ensure_ascii=False),
                environment=env)

        # ---- BR-43 空结果组合 -------------------------------------------
        err_before = len(ev.console_errors)
        page.click('[data-lib-scene="sleep"]', timeout=5000)
        page.click('[data-lib-kind="nature"]', timeout=5000)
        empty = q(page, LIB_SNAP_JS)
        # 面板仍可用：筛选按钮依然存在且能点回非空组合
        chips_left = len(empty.get("sceneChips") or []) + len(empty.get("kindChips") or [])
        page.click('[data-lib-scene="all"]', timeout=5000)
        after_reset = q(page, LIB_SNAP_JS)
        page.click('[data-lib-kind="all"]', timeout=5000)
        s.check("BR-43", "空结果组合（助眠+自然录音=0）零曲目、保留可用筛选与提示、零异常",
                "P1-09 / A6",
                empty.get("total") == 0
                and "0" in (empty.get("countText") or "")
                and "换个筛选条件" in (empty.get("text") or "")
                and chips_left >= 8
                and (after_reset.get("total") or 0) > 0
                and len(ev.console_errors) == err_before,
                "sleep+nature 渲染 0 首、计数显示 0、出现空态提示、筛选条仍可切回非空、"
                "控制台零新增错误",
                json.dumps({"total": empty.get("total"),
                            "countText": (empty.get("countText") or "").strip(),
                            "hasEmptyHint": "换个筛选条件" in (empty.get("text") or ""),
                            "chipsLeft": chips_left,
                            "afterResetTotal": after_reset.get("total"),
                            "consoleErrors": len(ev.console_errors)},
                           ensure_ascii=False),
                environment=env)

        # ---- BR-44 契约快照形状 -----------------------------------------
        snapc = q(page, "() => window.__STILLWAVE__.getLibrarySnapshot()")
        snap_keys = sorted(snapc.keys()) if isinstance(snapc, dict) else []
        filter_keys = sorted((snapc.get("filter") or {}).keys())
        item_keys = sorted({k for t in (snapc.get("tracks") or []) for k in t.keys()})
        s.check("BR-44", "getLibrarySnapshot() 键形状正确：total=30、tracks 等于可见列表",
                "A13 / A14 / AD-21",
                snap_keys == ["filter", "total", "tracks", "visibleCount"]
                and filter_keys == ["kind", "scene"]
                and item_keys == ["display", "id", "kind", "scene"]
                and snapc.get("total") == 30
                and len(snapc.get("tracks") or []) == snapc.get("visibleCount"),
                "顶层 {filter,visibleCount,total,tracks}；filter {scene,kind}；"
                "曲目 {id,display,scene,kind}；total=30；tracks.length=visibleCount",
                json.dumps({"keys": snap_keys, "filterKeys": filter_keys,
                            "itemKeys": item_keys, "total": snapc.get("total"),
                            "visibleCount": snapc.get("visibleCount"),
                            "tracksLen": len(snapc.get("tracks") or [])},
                           ensure_ascii=False),
                environment=env)

        # ---- BR-45 点选：即时高亮 + 收敛自洽 ----------------------------
        pre = q(page, LIB_SNAP_JS)
        prev_cs = pre.get("csTrackId")
        prev_main = pre.get("mainTrackId")
        base_degraded = pre.get("degraded") or 0
        scene_of = {t.get("id"): t.get("scene") for t in tracks}
        pick = None
        for tid in pre.get("ids") or []:
            if tid not in (prev_cs, prev_main):
                pick = tid
                break
        if pick is None:
            s.check("BR-45", "点选曲目后高亮/主槽位/署名一致并收敛自洽", "P1-09",
                    False, "存在可点选的非当前曲目", "声音库中没有可选曲目",
                    environment=env)
        else:
            page.click('.lib-track[data-lib-track="%s"]' % pick, timeout=8000)
            try:
                page.wait_for_function(
                    "(id) => { var st = window.__STILLWAVE__.getState();"
                    " return st.tracks && st.tracks[0] && st.tracks[0].trackId === id; }",
                    arg=pick, timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            mid = q(page, LIB_SNAP_JS)
            # 收敛：archive.org 单曲首包 1.5~9.6s，3s 预算下有以下三种「自洽」终态：
            #   (a) bundled-primary  —— 所选曲目在线接入成功
            #   (b) bundled-backup   —— 主源超时后按 AD-16 切到同场景真实备选（badge=备用音源）
            #   (c) synth-degraded   —— 全部候选失败，自愈回落 L0 合成层
            # 判据是「高亮 / 主槽位 / currentSource 三者互指且绝不指向旧曲目」，不硬要 bundled。
            t0 = time.time()
            term_kind = None
            end = mid
            while time.time() - t0 < 20:
                end = q(page, LIB_SNAP_JS)
                tier = end.get("tier")
                cs = end.get("csTrackId")
                cur = end.get("current") or []
                consistent = (
                    end.get("mainTrackId") == cs and cur == [cs]
                    and cs is not None and cs != prev_cs)
                if tier == "bundled" and consistent:
                    if cs == pick:
                        term_kind = "bundled-primary"
                        break
                    if scene_of.get(cs) and scene_of.get(cs) == scene_of.get(pick):
                        term_kind = "bundled-backup"
                        break
                if (tier == "synth" and cs is None
                        and end.get("mainTrackId") is None and cur == []
                        and (end.get("degraded") or 0) > base_degraded):
                    term_kind = "synth-degraded"
                    break
                time.sleep(0.5)
            immediate_ok = (
                mid.get("pressed") == [pick] and mid.get("current") == [pick]
                and mid.get("mainTrackId") == pick
                and mid.get("csTrackId") in (None, pick)
                and (prev_cs is None or mid.get("csTrackId") != prev_cs))
            s.check("BR-45", "点选后即时高亮唯一、主槽位切到目标曲目、旧署名不残留，"
                     "20s 内收敛为自洽终态（在线 / 同场景备选 / 合成层）",
                    "P1-09 / A10 / A14",
                    bool(immediate_ok) and term_kind is not None,
                    "点击瞬间：仅该按钮 aria-pressed=true 且 .is-current；"
                    "tracks[0].trackId=picked；currentSource.trackId∈{null,picked} 且≠旧值；"
                    "20s 内收敛为 (a) bundled & trackId=picked，或 (b) bundled & trackId="
                    "同场景备选，或 (c) synth & trackId=null & 无高亮；三者均要求高亮/"
                    "主槽位/currentSource 互指",
                    json.dumps({"pick": pick, "prevCs": prev_cs, "prevMain": prev_main,
                                "immediate": {"pressed": mid.get("pressed"),
                                              "current": mid.get("current"),
                                              "mainTrackId": mid.get("mainTrackId"),
                                              "csTrackId": mid.get("csTrackId")},
                                "immediateOk": bool(immediate_ok),
                                "terminal": term_kind,
                                "end": {"tier": end.get("tier"),
                                        "csTrackId": end.get("csTrackId"),
                                        "mainTrackId": end.get("mainTrackId"),
                                        "current": end.get("current"),
                                        "degraded": end.get("degraded")}},
                               ensure_ascii=False)[:900],
                    environment=env)
            s.artifacts["libraryPick"] = {"pick": pick, "terminal": term_kind,
                                          "tier": end.get("tier"),
                                          "csTrackId": end.get("csTrackId")}

        # ---- BR-46 键盘 / a11y / 收起 / 全程控制台清洁 ------------------
        focus_target = (q(page, LIB_SNAP_JS).get("ids") or [None])[0]
        focus_ok = False
        if focus_target:
            focus_ok = bool(q(page, """(id) => {
              const btn = document.querySelector('.lib-track[data-lib-track="' + id + '"]');
              if (!btn) { return false; }
              btn.focus();
              return document.activeElement === btn
                && document.activeElement.classList.contains('lib-track');
            }""", focus_target))
        names_ok = q(page, """() => {
          const list = Array.from(document.querySelectorAll('#library-panel .lib-track'));
          return list.length > 0 && list.every(e =>
            (e.getAttribute('data-lib-name') || '') ===
            (((e.querySelector('.lib-track-name') || {}).textContent || '').trim()));
        }""")
        page.click("#btn-library", timeout=5000)
        try:
            page.wait_for_function(
                "() => document.getElementById('library-panel').hidden",
                timeout=5000)
        except Exception:  # noqa: BLE001
            pass
        closed = q(page, LIB_SNAP_JS)
        errs, perrs, herrs = (len(ev.console_errors), len(ev.page_errors),
                              len(ev.http_errors))
        s.check("BR-46", "曲目按钮可聚焦、data-lib-name 与可见名一致、"
                 "再次点击收起面板、全程零 console/page/HTTP 错误",
                "A5 / A8 / A6 / P1-09",
                focus_ok and bool(names_ok)
                and closed.get("panelHidden") is True
                and closed.get("btnExpanded") == "false"
                and errs == 0 and perrs == 0 and herrs == 0,
                "focus 进入 .lib-track；data-lib-name == .lib-track-name；"
                "收起后 hidden=true & aria-expanded=false；console/pageerror/4xx=0",
                json.dumps({"focus": focus_ok, "namesMatch": bool(names_ok),
                            "closedHidden": closed.get("panelHidden"),
                            "closedExpanded": closed.get("btnExpanded"),
                            "console": errs, "pageErrors": perrs,
                            "httpErrors": herrs,
                            "httpSample": ev.http_errors[:2]},
                           ensure_ascii=False),
                environment=env)
        s.artifacts["libraryEvidence"] = {
            "consoleErrors": errs, "pageErrors": perrs, "httpErrors": herrs,
            "count": 30, "displays": len(displays),
        }
    except Exception as exc:  # noqa: BLE001
        # 异常兜底也要保住用例数：未登记过的编号一律记 FAIL，绝不让总数静默缩水
        done = {c.id for c in s.cases}
        for cid, name, req in LIB_CASES:
            if cid in done:
                continue
            s.check(cid, name, req, False, "声音库用例无异常执行",
                    "%s: %s" % (type(exc).__name__, str(exc)[:240]),
                    environment=env)
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Group 2 · 三类故障注入（每个用例独立页面，避免相互污染）
# ---------------------------------------------------------------------------
def group_faults(s: Suite, browser: Any, base_url: str, phase: str) -> None:
    # 用本地静态服务的快速 404 路径注入，确保触发 <audio> error（reason=404）
    # 而非 archive.org 不存在路径的 3s 挂起（那条路径属于「超时」，由 BR-10 覆盖）。
    parsed = urlparse(base_url)
    fast_404 = "%s://%s/__qa_404__.mp3" % (parsed.scheme, parsed.netloc)
    s.artifacts["fault404InjectedUrl"] = fast_404
    cases = [
        ("BR-09", "404 主源故障注入", "404", "A3 / P0-06 / P0-17"),
        ("BR-10", "模拟超时故障注入", "timeout", "A3 / P0-06 / P0-17"),
        ("BR-11", "断网故障注入", "network", "A3 / P0-06 / P0-14 / P0-17"),
    ]
    for cid, name, kind, req in cases:
        ctx, page, ev = new_page(browser)
        results: Dict[str, Any] = {}
        try:
            page.goto(base_url, wait_until="load", timeout=20000)
            if not wait_contract(page):
                s.unverified(cid, name, req, "契约未挂载", environment="Chrome")
                continue
            # 三类注入都在「启动前/启动时」注入，避免依赖在线升级这一网络前置条件；
            # 断网按架构 §4.5 示例直接 inject.setOffline(true)，验证播放连续 + 徽标切 synth。
            if kind == "404":
                inj(page, "setManifestOverride", [
                    {"id": "jamendo-122281", "url": fast_404}])
            elif kind == "timeout":
                inj(page, "setLoadTimeout", 400)
                inj(page, "forceTimeoutNext", 1)
            else:
                inj(page, "setOffline", True)
            act(page, "start")
            try:
                page.wait_for_function(
                    "window.__STILLWAVE__.getState().playing === true",
                    timeout=10000)
            except Exception:  # noqa: BLE001
                pass
            started = state(page).get("playing") is True
            gain_before = state(page).get("effectiveGain", {}).get("master")
            degraded = wait_degrade(page, 15000)
            if kind == "network":
                try:
                    page.wait_for_function(
                        "window.__STILLWAVE__.getState().badge === 'synth'",
                        timeout=12000)
                except Exception:  # noqa: BLE001
                    pass
            results["gainBefore"] = gain_before
            st = state(page)
            ui = q(page, "window.__STILLWAVE__.getUiSnapshot()")
            results.update({
                "started": started, "degraded": degraded,
                "playing": st.get("playing"),
                "playState": st.get("playState"),
                "lastDegradeDurationMs": st.get("lastDegradeDurationMs"),
                "degradedEvents": st.get("degradedEvents"),
                "badge": st.get("badge"), "sourceTier": st.get("sourceTier"),
                "consoleErrorCount": st.get("consoleErrorCount"),
                "effectiveGain": st.get("effectiveGain"),
                "ui": ui,
            })
            toast = (ui or {}).get("toastText") or ""
            duration = st.get("lastDegradeDurationMs")
            ok = (started and degraded and st.get("playing") is True
                  and isinstance(duration, (int, float)) and duration <= 3000
                  and len(st.get("degradedEvents") or []) >= 1
                  and st.get("consoleErrorCount") == 0
                  and (ui or {}).get("hasDialog") is False
                  and (ui or {}).get("hasModal") is False
                  and (ui or {}).get("flashingElements") == 0
                  and (ui or {}).get("ariaLive") == "polite"
                  and "错误" not in toast)
            if kind == "timeout":
                ok = ok and any(e.get("reason") == "timeout"
                                for e in (st.get("degradedEvents") or []))
            if kind == "network":
                ok = ok and st.get("badge") == "synth" \
                    and results.get("gainBefore") == \
                    (st.get("effectiveGain") or {}).get("master")
            s.check(cid, "%s：≤3s 自动回退、playing 不变、零异常、不弹窗不闪烁" % name,
                    req, bool(ok),
                    "lastDegradeDurationMs<=3000, playing=true, badge 正确, "
                    "consoleErrorCount=0, hasDialog/hasModal=false, ariaLive=polite",
                    json.dumps(results, ensure_ascii=False)[:700],
                    environment="Chrome / ?debug=1")
            s.artifacts["fault_" + kind] = results

            # BR-12 回退后仍可继续操作（仅在断网用例后测，覆盖 P0-17）
            if kind == "network" and ok:
                act(page, "setScene", "empty")
                act(page, "setMasterVolume", 0.55)
                act(page, "setTimer", 1, 30)
                st2 = state(page)
                s.check("BR-12", "回退后仍可切场景 / 调音量 / 设定时器且 playing 不变",
                        "P0-17 / A3",
                        st2.get("scene") == "empty"
                        and abs(st2.get("masterVolume", 0) - 0.55) < 0.001
                        and st2.get("timer", {}).get("active") is True
                        and st2.get("playing") is True,
                        "scene=empty, master=0.55, timer.active=true, playing=true",
                        json.dumps({k: st2.get(k) for k in
                                    ("scene", "masterVolume", "timer", "playing")},
                                   ensure_ascii=False)[:300],
                        environment="Chrome / 降级态")
        except Exception as exc:  # noqa: BLE001
            s.check(cid, name, req, False, "注入用例完整执行",
                    "%s: %s" % (type(exc).__name__, str(exc)[:260]),
                    environment="Chrome")
        finally:
            ctx.close()


# ---------------------------------------------------------------------------
# Group 3 · 持久化 / 内存降级 / 刷新曲库三态
# ---------------------------------------------------------------------------
def group_persistence(s: Suite, browser: Any, base_url: str) -> None:
    ctx, page, ev = new_page(browser)
    try:
        page.goto(base_url, wait_until="load", timeout=20000)
        wait_contract(page)
        act(page, "start")
        act(page, "setScene", "sleep")
        act(page, "setMasterVolume", 0.77)
        act(page, "setBrightness", "extreme")
        before = state(page)
        page.reload(wait_until="load")
        wait_contract(page)
        after = state(page)
        s.check("BR-13", "P0-12 偏好持久化：重开还原场景/音量/亮度",
                "P0-12 / A4",
                after.get("scene") == "sleep"
                and abs(after.get("masterVolume", 0) - 0.77) < 0.001
                and after.get("brightness") == "extreme",
                "reload 后 scene=sleep, master=0.77, brightness=extreme",
                "before=%s after=%s"
                % (json.dumps({k: before.get(k) for k in
                               ("scene", "masterVolume", "brightness")},
                              ensure_ascii=False),
                   json.dumps({k: after.get(k) for k in
                               ("scene", "masterVolume", "brightness")},
                              ensure_ascii=False)),
                environment="Chrome / reload")

        # 清除本地设置
        act(page, "clearStorage")
        cleared = state(page)
        s.check("BR-13b", "「清除本地设置」恢复出厂默认",
                "P0-09 / P0-12",
                cleared.get("scene") == "focus"
                and abs(cleared.get("masterVolume", 0) - 0.45) < 0.001
                and cleared.get("brightness") == "dark",
                "scene=focus, master=0.45, brightness=dark",
                json.dumps({k: cleared.get(k) for k in
                            ("scene", "masterVolume", "brightness")},
                           ensure_ascii=False),
                environment="Chrome")

        # localStorage 不可用 → 内存降级
        inj(page, "setStorageUnavailable", True)
        degraded = state(page)
        s.check("BR-13c", "localStorage 不可用时静默降级为内存态、不报错",
                "P0-12 / A6",
                degraded.get("storageMode") == "memory"
                and degraded.get("consoleErrorCount") == 0
                and not ev.page_errors,
                "storageMode=memory, consoleErrorCount=0",
                "mode=%s counter=%s pageErrors=%d"
                % (degraded.get("storageMode"),
                   degraded.get("consoleErrorCount"), len(ev.page_errors)),
                environment="Chrome / 注入")
        inj(page, "setStorageUnavailable", False)

        # 刷新曲库：正常态 + 失败态都保留清单
        r1 = act(page, "refreshLibrary")
        st1 = state(page)
        inj(page, "setOffline", True)
        r2 = act(page, "refreshLibrary")
        inj(page, "setOffline", False)
        st2 = state(page)
        legal = {"updated", "unchanged", "skipped", "failed"}
        s.check("BR-14", "刷新曲库三态：status 合法、失败不清空清单、播放不中断",
                "P0-13 / P0-14 / A12",
                isinstance(r1, dict) and r1.get("status") in legal
                and isinstance(r2, dict) and r2.get("status") in legal
                and st1.get("manifest", {}).get("count") == 30
                and st2.get("manifest", {}).get("count") == 30
                and st2.get("consoleErrorCount") == 0,
                "两次 refresh 返回合法 status，manifest.count 恒为 30",
                "r1=%s r2=%s count1=%s count2=%s libStatus=%s"
                % (r1, r2, st1.get("manifest", {}).get("count"),
                   st2.get("manifest", {}).get("count"),
                   st2.get("libraryStatus")),
                environment="Chrome")
        s.artifacts["refreshResults"] = [r1, r2]
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Group 4 · 30 首逐条可播 + 四场景真实出声
# ---------------------------------------------------------------------------
def group_audio(s: Suite, browser: Any, base_url: str,
                manifest: Dict[str, Any]) -> None:
    ctx, page, ev = new_page(browser)
    try:
        page.goto(base_url, wait_until="load", timeout=20000)
        wait_contract(page)
        urls = [t["url"] for t in manifest["tracks"]]
        results: List[Dict[str, Any]] = []
        # 分 5 批 × 6 首并发，避免单次 evaluate 协议超时
        for i in range(0, len(urls), 6):
            batch = urls[i:i + 6]
            try:
                part = page.evaluate(AUDIO_LOAD_PROBE_JS, batch)
                results.extend(part)
            except Exception as exc:  # noqa: BLE001
                results.extend({"url": u, "ok": False,
                                "reason": "evaluate-error:" + type(exc).__name__}
                               for u in batch)
            time.sleep(1)  # 批次间留白，规避 archive.org 突发限流
        def playable(r: Dict[str, Any]) -> bool:
            return bool(r.get("ok") and r.get("readyState", 0) >= 1
                        and r.get("duration", 0) > 0)

        first_pass = sum(1 for r in results if playable(r))
        # archive.org 偶发限流（非死链）：失败项单条退避重试最多 3 次，
        # 重试结果如实记录，不把「重试通过」伪装成「首轮通过」。
        time.sleep(1)  # 重试前留白，先让限流窗口释放
        retries: List[Dict[str, Any]] = []
        final: List[Dict[str, Any]] = []
        for r in results:
            if playable(r):
                final.append(r)
                continue
            fixed = None
            attempts = 0
            for attempt in range(3):
                attempts = attempt + 1
                try:
                    one = page.evaluate(AUDIO_LOAD_PROBE_JS, [r["url"]])[0]
                except Exception as exc:  # noqa: BLE001
                    one = {"url": r["url"], "ok": False,
                           "reason": "evaluate-error:" + type(exc).__name__}
                if playable(one):
                    fixed = one
                    break
                time.sleep(2.0)
            retries.append({
                "url": r["url"], "firstReason": r.get("reason"),
                "fixedAfterRetry": bool(fixed), "attempts": attempts,
                "lastReason": (fixed or one).get("reason"),
            })
            final.append(fixed or r)
        good = [r for r in final if playable(r)]
        failed = [r for r in final if not playable(r)]
        s.check("BR-16", "A13/P0-15：30 首在线曲目逐条真实加载可播（元数据+时长）",
                "A13 / P0-15 / A11",
                len(good) == 30,
                "30/30 首 canplay/loadedmetadata 且 duration>0（偶发限流允许单条重试）",
                "首轮 %d/30，重试修复 %d 条，最终 %d/30；失败样例=%s；重试明细=%s"
                % (first_pass, sum(1 for x in retries if x["fixedAfterRetry"]),
                   len(good), json.dumps(failed[:2], ensure_ascii=False)[:300],
                   json.dumps(retries[:3], ensure_ascii=False)[:400]),
                environment="Google Chrome / 真实网络")
        s.artifacts["audioLoadProbe"] = final
        s.artifacts["audioLoadFirstPass"] = first_pass
        s.artifacts["audioLoadRetries"] = retries

        # 四场景各 1 首 + 默认主源：真实 play() 且 currentTime 前进
        picks = []
        for scene in ("focus", "sleep", "empty", "meditation"):
            t = next((x for x in manifest["tracks"] if x["scene"] == scene), None)
            if t:
                picks.append((scene, t["url"]))
        default = next((x for x in manifest["tracks"]
                        if x["id"] == "jamendo-122281"), None)
        if default:
            picks.append(("default", default["url"]))
        def play_ok_one(r: Dict[str, Any]) -> bool:
            return (r.get("ok") is True and r.get("readyState", 0) >= 3
                    and r.get("advanced", 0) > 0.05)

        plays: List[Dict[str, Any]] = []
        play_retries: List[Dict[str, Any]] = []
        for label, url in picks:
            r: Dict[str, Any] = {}
            for attempt in range(1, 4):
                try:
                    r = page.evaluate(AUDIO_PLAY_PROBE_JS, url)
                except Exception as exc:  # noqa: BLE001
                    r = {"ok": False, "reason": type(exc).__name__}
                if play_ok_one(r):
                    break
                # archive.org 偶发限流/并发 NotSupportedError：如实记录并退避重试
                if attempt < 3:
                    time.sleep(1.0)
            r["label"] = label
            r["attempts"] = attempt
            plays.append(r)
            if attempt > 1:
                play_retries.append({
                    "label": label, "url": url, "attempts": attempt,
                    "firstReason": "play-rejected/限流", "finalOk": play_ok_one(r),
                })
        play_ok = len(picks) == 5 and all(play_ok_one(p) for p in plays)
        s.check("BR-16b", "四场景 + 默认主源共 5 首真实 play() 出声（currentTime 前进）",
                "A13 / A11 / P0-15",
                play_ok, "5/5 play() 成功、readyState>=3、进度前进（偶发限流允许单条重试）",
                "通过=%d/5；重试明细=%s；结果=%s"
                % (sum(1 for p in plays if play_ok_one(p)),
                   json.dumps(play_retries, ensure_ascii=False)[:300],
                   json.dumps(plays, ensure_ascii=False)[:600]),
                environment="Google Chrome / 真实网络")
        s.artifacts["audioPlayProbe"] = plays
        s.artifacts["audioPlayRetries"] = play_retries
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Group 5 · 三档视口 / 四场景 / 极暗 / 降级状态截图
# ---------------------------------------------------------------------------
def group_visual(s: Suite, browser: Any, base_url: str, shots: bool) -> None:
    # BR-18 320px 视口
    ctx, page, ev = new_page(browser, viewport=(320, 720))
    try:
        page.goto(base_url, wait_until="load", timeout=20000)
        wait_contract(page)
        act(page, "start")
        time.sleep(0.4)
        geo = q(page, """() => {
            const de = document.documentElement;
            const ids = ['#btn-play','#master-volume','#btn-refresh',
                         '#tab-focus','#btn-add','#btn-brightness'];
            const boxes = {};
            ids.forEach(s => { const e = document.querySelector(s);
                if (e) { const r = e.getBoundingClientRect();
                         boxes[s] = {w: Math.round(r.width), h: Math.round(r.height)}; } });
            return {scrollWidth: de.scrollWidth, clientWidth: de.clientWidth,
                    boxes: boxes};
        }""")
        small = [k for k, v in geo["boxes"].items()
                 if min(v["w"], v["h"]) < 44]
        s.check("BR-18", "A5：320px 真机视口无横向溢出、主控件触控区 ≥44px",
                "A5 / P0-08",
                geo["scrollWidth"] <= geo["clientWidth"] + 1 and not small,
                "scrollWidth<=320 且 6 个主控件最小边≥44px",
                json.dumps(geo, ensure_ascii=False)[:500],
                environment="Chrome / 320×720")
        s.artifacts["viewport320"] = geo
        if shots:
            screenshot(page, "viewport_320.png")
    finally:
        ctx.close()

    if not shots:
        return
    ctx, page, ev = new_page(browser, viewport=(1440, 900))
    paths = []
    try:
        page.goto(base_url, wait_until="load", timeout=20000)
        wait_contract(page)
        act(page, "start")
        time.sleep(6.0)  # 等在线升级完成，截图反映真实播放态
        paths.append(screenshot(page, "viewport_1440.png"))
        for sid in ("focus", "sleep", "empty", "meditation"):
            act(page, "setScene", sid)
            time.sleep(0.6)
            paths.append(screenshot(page, "scene_%s.png" % sid))
        act(page, "setBrightness", "extreme")
        time.sleep(0.4)
        extreme_state = state(page).get("brightness")
        paths.append(screenshot(page, "brightness_extreme.png"))
        # 极暗档只用于「夜间最低亮度」截图；随后恢复默认亮度，
        # 避免污染「降级状态」截图的可读性（QA 自修：此前未恢复）。
        act(page, "setBrightness", "dark")
        # 用 forceTier('synth') 确定性触发降级，并显式等待徽标切换，
        # 确保截图内容与文件名一致（此前仅 setOffline+sleep 不可靠）。
        inj(page, "forceTier", "synth")
        try:
            page.wait_for_function(
                "window.__STILLWAVE__.getState().badge === 'synth'",
                timeout=8000)
            degraded_confirmed = True
        except Exception:  # noqa: BLE001
            degraded_confirmed = False
        time.sleep(0.5)
        degraded_state = state(page)
        degraded_ui = q(page, "window.__STILLWAVE__.getUiSnapshot()")
        paths.append(screenshot(page, "degraded_synth.png"))
        s.artifacts["screenshotStates"] = {
            "brightnessExtreme": extreme_state,
            "degradedBadge": degraded_state.get("badge"),
            "degradedTier": degraded_state.get("sourceTier"),
            "degradedBadgeText": (degraded_ui or {}).get("badgeText"),
            "degradedToast": (degraded_ui or {}).get("toastText"),
            "degradedConfirmed": degraded_confirmed,
        }
        s.check("BR-19", "截图产出：三档视口 + 四场景 + 夜间极暗 + 降级状态",
                "A2 / A5 / 交付物",
                len(paths) >= 6 and extreme_state == "extreme"
                and degraded_confirmed
                and degraded_state.get("badge") == "synth"
                and degraded_state.get("sourceTier") == "synth",
                "本组 ≥6 张 PNG 落盘且极暗档=extreme、降级截图徽标=synth",
                "已生成 %d 张；极暗=%s；降级徽标=%s/%s toast=%s"
                % (len(paths), extreme_state, degraded_state.get("badge"),
                   degraded_state.get("sourceTier"),
                   (degraded_ui or {}).get("toastText")),
                environment="Chrome")
        s.artifacts["screenshots"] = sorted(
            os.path.join(SHOTS_DIR, f) for f in os.listdir(SHOTS_DIR)
            if f.endswith(".png"))
    finally:
        ctx.close()

    # 768px 单独一档
    ctx, page, ev = new_page(browser, viewport=(768, 1024))
    try:
        page.goto(base_url, wait_until="load", timeout=20000)
        wait_contract(page)
        act(page, "start")
        time.sleep(0.5)
        screenshot(page, "viewport_768.png")
        s.check("BR-19b", "768px 视口无横向溢出", "A5 / P0-08",
                q(page, "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"),
                "无横向溢出", "校验通过", environment="Chrome / 768×1024")
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Group 6 · 双环境 / 跨浏览器 / reduced-motion / favicon 原始观察
# ---------------------------------------------------------------------------
def group_environments(s: Suite, pw: Any, servers: Dict[str, StaticServer],
                       browsers: Dict[str, Any], phase: str) -> None:
    chrome = browsers.get("chrome")
    if not chrome:
        s.unverified("BR-25", "双环境验证", "A4", "Chrome 不可用")
        return

    # BR-25 file:// 双击打开
    for label, url, cid in (
        ("file://", file_url(), "BR-25"),
        ("Pages 子路径", servers["sub"].url(), "BR-26"),
    ):
        ctx, page, ev = new_page(chrome)
        try:
            page.goto(url, wait_until="load", timeout=20000)
            ok = wait_contract(page)
            st = state(page)
            act(page, "start")
            time.sleep(0.5)
            st2 = state(page)
            s.check(cid, "%s 环境：契约挂载、零异常、首次手势可出声、30 首内置" % label,
                    "A4 / NFR-02 / P0-11",
                    ok and clean_console(ev)
                    and st.get("manifest", {}).get("count") == 30
                    and st.get("resolvedRemotes") == []
                    and st2.get("playing") is True
                    and st2.get("activeTrackCount", 0) >= 1,
                    "contract=true, remotes=[], count=30, playing=true, 0 异常",
                    "ok=%s remotes=%s count=%s playing=%s console=%d pageErrors=%d"
                    % (ok, st.get("resolvedRemotes"),
                       st.get("manifest", {}).get("count"),
                       st2.get("playing"), len(ev.console_errors),
                       len(ev.page_errors)),
                    environment=label)
        except Exception as exc:  # noqa: BLE001
            s.unverified(cid, "%s 环境验证" % label, "A4",
                         "%s: %s" % (type(exc).__name__, str(exc)[:200]))
        finally:
            ctx.close()

    # BR-20b reduced-motion
    ctx, page, ev = new_page(chrome, reduced_motion=True)
    try:
        page.goto(servers["root"].url(), wait_until="load", timeout=20000)
        wait_contract(page)
        dur = q(page, "getComputedStyle(document.documentElement).getPropertyValue('--dur').trim()")
        st = state(page)
        s.check("BR-20b", "prefers-reduced-motion: reduce 时动效归零且状态可感知",
                "A8 / NFR-06",
                dur == "0ms" and st.get("reducedMotion") is True,
                "--dur=0ms 且 state.reducedMotion=true",
                "dur=%s reducedMotion=%s" % (dur, st.get("reducedMotion")),
                environment="Chrome / reduced-motion")
    finally:
        ctx.close()

    # BR-29 A6 严格口径（Round 2）：favicon 已用 <link rel="icon" href="data:,">
    # 修复。在**关闭 favicon_204 中性化**的原始静态服务上直接断言
    # 零 404 / 零 console error / 零 pageerror / 零 favicon 请求，不掩盖不豁免。
    raw = StaticServer(prefix="", favicon_204=False)
    try:
        ctx, page, ev = new_page(chrome)
        try:
            page.goto(raw.url(), wait_until="load", timeout=20000)
            ok = wait_contract(page)
            act(page, "start")           # 全流程（含首次手势出声）审查
            time.sleep(0.8)
            favicon_reqs = [r["url"] for r in ev.requests
                            if "favicon" in r["url"]]
            has_favicon_404 = any("404" in e for e in ev.console_errors) or any(
                x["status"] == 404 for x in ev.http_errors)
            strict_a6 = (
                ok is True
                and not ev.console_errors
                and not ev.page_errors
                and not ev.http_errors
                and not favicon_reqs
                and not ev.sensitive_headers)
            s.artifacts["faviconObservation"] = {
                "consoleErrors": ev.console_errors,
                "pageErrors": ev.page_errors,
                "httpErrors": ev.http_errors,
                "faviconRequests": favicon_reqs,
                "favicon404Present": has_favicon_404,
                "phase": "Round 2 / CODE_FROZEN 后 / 关闭中性化（favicon_204=False）",
                "note": ("修复前：站点未提供 favicon，浏览器自动请求 /favicon.ico "
                         "返回 404 + console error（见 supplementary_findings.json SF-05 "
                         "与 preflight 归档 BR-29）。修复后：index.html 增加 "
                         "<link rel=\"icon\" href=\"data:,\">，浏览器不再发起该请求；"
                         "本用例在原始服务上严格断言零 404 / 零 console error，"
                         "不再依赖任何中性化豁免。"),
            }
            s.check("BR-29", "A6 严格口径（关闭中性化）：favicon 修复后全流程零 404 / 零 console error",
                    "A6 / NFR-01 / P0-07",
                    strict_a6,
                    "favicon_204=False 原始服务上 console=0, pageerror=0, 4xx=0, "
                    "favicon 请求=0, 敏感头=0",
                    "strict=%s console=%d pageerror=%d 4xx=%s faviconReqs=%s"
                    % (strict_a6, len(ev.console_errors), len(ev.page_errors),
                       json.dumps(ev.http_errors, ensure_ascii=False)[:200],
                       favicon_reqs[:2]),
                    environment="Chrome / 原始静态服务（无中性化）")
            s.artifacts["favicon404Present"] = has_favicon_404
        finally:
            ctx.close()
    finally:
        raw.stop()

    # BR-24 A10 许可与署名：原始条目页链接真实 HTTP 可访问（抽样 3 条，覆盖 music/nature/场景）
    manifest = load_manifest()
    picks = [
        manifest["tracks"][0],
        next((t for t in manifest["tracks"] if t.get("kind") == "nature"),
             manifest["tracks"][1]),
        next((t for t in manifest["tracks"] if t.get("scene") == "meditation"),
             manifest["tracks"][2]),
    ]
    link_results: List[Dict[str, Any]] = []
    for t in picks:
        url = t.get("item", "")
        try:
            req = urllib.request.Request(
                url, method="HEAD",
                headers={"User-Agent": "Mozilla/5.0 (Stillwave-QA)"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                link_results.append({"id": t["id"], "url": url,
                                     "status": resp.status})
        except urllib.error.HTTPError as exc:
            link_results.append({"id": t["id"], "url": url, "status": exc.code})
        except Exception as exc:  # noqa: BLE001
            link_results.append({"id": t["id"], "url": url,
                                 "error": "%s: %s" % (type(exc).__name__,
                                                      str(exc)[:120])})
    if all("error" in r for r in link_results):
        s.unverified("BR-24", "许可原始条目页链接可访问（抽样 3 条真实 HTTP）",
                     "A10 / P0-16",
                     "网络受限，3 条 HEAD 均失败：%s"
                     % json.dumps(link_results, ensure_ascii=False)[:400])
    else:
        ok = all(r.get("status") in (200, 301, 302, 303, 307, 308, 405)
                 for r in link_results)
        s.check("BR-24", "许可原始条目页链接可访问（抽样 3 条真实 HTTP）",
                "A10 / P0-16", ok,
                "3/3 条 item 链接返回 2xx / 3xx / 405（405 视为端点存在）",
                json.dumps(link_results, ensure_ascii=False)[:500],
                environment="真实 HTTP HEAD")
    s.artifacts["licenseLinkProbe"] = link_results

    # BR-31 跨浏览器：Round 2 主理人已实测定稿「仅 channel=chrome 可用」，
    # 明确要求「请勿再重试 Firefox/WebKit」。故本轮只启动 Chrome，其余逐项
    # UNVERIFIED 并写明定稿事实；Chrome 内的四场景 / 夜间最低亮度 /
    # 定时器渐弱到停止由 group_core 的 BR-04 / BR-27 / BR-08 真实实测通过，
    # 但绝不外推为 Firefox / Safari 通过。
    for name in ("chromium", "firefox", "webkit"):
        b = browsers.get(name)
        if not b:
            s.unverified(
                "BR-31.%s" % name,
                "跨浏览器完整核心路径：%s" % BROWSER_LABELS[name],
                "A2 / NFR-08",
                "环境限制（主理人 Round 2 实测定稿，本轮不重复启动）：%s；"
                "需在目标设备补测，Chrome 结果不得外推（详见 env_probe.json）"
                % PREVERIFIED_LIMITS[name],
                environment=BROWSER_LABELS[name])
            continue
        ctx, page, ev = new_page(b)
        detail: Dict[str, Any] = {}
        try:
            page.goto(servers["root"].url(), wait_until="load", timeout=20000)
            ok = wait_contract(page)
            st0 = state(page)
            detail["contract"] = ok
            detail["manifestCount"] = st0.get("manifest", {}).get("count")

            act(page, "start")
            time.sleep(0.5)
            st1 = state(page)
            detail["playing"] = st1.get("playing")
            detail["audioContext"] = st1.get("audioContext")

            # 四场景切换
            scene_ok = True
            for sid in ("sleep", "empty", "meditation", "focus"):
                act(page, "setScene", sid)
                time.sleep(0.15)
                if state(page).get("scene") != sid:
                    scene_ok = False
            detail["scenes"] = scene_ok

            # 定时器设定
            act(page, "setTimer", 1, 30)
            detail["timerActive"] = state(page).get("timer", {}).get("active")

            # 降级徽标（确定性触发）
            inj(page, "forceTier", "synth")
            try:
                page.wait_for_function(
                    "window.__STILLWAVE__.getState().badge === 'synth'",
                    timeout=8000)
                detail["degradeBadge"] = state(page).get("badge")
            except Exception:  # noqa: BLE001
                detail["degradeBadge"] = None

            # A14 零泄露：四处曲目名 + 两个命中数组
            snap = q(page, "window.__STILLWAVE__.getVisibleTextSnapshot()") or {}
            detail["originalTitleHits"] = snap.get("originalTitleHits")
            detail["impurityHits"] = snap.get("impurityHits")
            a14_ok = (snap.get("originalTitleHits") == []
                      and snap.get("impurityHits") == [])

            detail["consoleErrors"] = len(ev.console_errors)
            detail["pageErrors"] = len(ev.page_errors)
            passed = (
                ok is True
                and st0.get("manifest", {}).get("count") == 30
                and st1.get("playing") is True
                and scene_ok
                and detail.get("timerActive") is True
                and detail.get("degradeBadge") == "synth"
                and a14_ok
                and clean_console(ev))
            s.check("BR-31.%s" % name,
                    "跨浏览器完整核心路径：%s" % BROWSER_LABELS[name],
                    "A2 / A14 / NFR-08",
                    passed,
                    "契约挂载+30首 / 首次手势出声 / 四场景切换 / 定时器 / "
                    "降级徽标=synth / A14 零泄露 / 零异常",
                    json.dumps(detail, ensure_ascii=False)[:500],
                    environment=BROWSER_LABELS[name])
            s.artifacts["crossBrowser_" + name] = detail
        except Exception as exc:  # noqa: BLE001
            s.unverified("BR-31.%s" % name,
                         "跨浏览器完整核心路径：%s" % BROWSER_LABELS[name],
                         "A2",
                         "执行异常: %s: %s（已采明细=%s）"
                         % (type(exc).__name__, str(exc)[:160],
                            json.dumps(detail, ensure_ascii=False)[:200]))
        finally:
            ctx.close()

    # Safari 通道结论：引用 env_probe 事实（本轮重新探测后仍不可动则保留）
    s.unverified("BR-31.safari", "Safari 完整使用路径", "A2 / NFR-08",
                 "系统 Safari 需在「设置→开发者→允许远程自动化」手动开启，"
                 "当前会话无该权限，safaridriver 返回 500；未执行，详见 env_probe.json",
                 environment="Safari")


# ---------------------------------------------------------------------------
# 总入口
# ---------------------------------------------------------------------------
def run(phase: str = "full", with_audio: bool = True,
        with_shots: bool = True) -> Suite:
    s = Suite("browser", phase=phase)
    manifest = load_manifest()
    # Round 2 / A6 严格口径：关闭 favicon_204 中性化。
    # 站点已用 <link rel="icon" href="data:,"> 修复，浏览器不再请求 /favicon.ico，
    # 因此在原始静态服务上直接断言零 404 / 零 console error（不掩盖、不豁免）。
    servers = {
        "root": StaticServer(prefix="", favicon_204=False),
        "sub": StaticServer(prefix="stillwave_meditation", favicon_204=False),
    }
    browsers: Dict[str, Any] = {}
    try:
        with sync_playwright() as pw:
            # Round 2 定稿：仅 channel=chrome 可启动；chromium/firefox/webkit
            # 按主理人指示不再重复启动（逐项 UNVERIFIED，见 group_environments）。
            for name in ("chrome",):
                b, err = launch_browser(pw, name)
                if b:
                    browsers[name] = b
            if "chrome" not in browsers:
                s.unverified("BR-00", "Chrome 主套件", "A2",
                             "Google Chrome 不可用，浏览器用例全部未执行")
                s.print_report()
                return s

            # Group 1 核心
            ctx, page, ev = new_page(browsers["chrome"], viewport=(1440, 900))
            try:
                page.goto(servers["root"].url(), wait_until="load", timeout=20000)
                group_core(s, page, ev, phase, manifest)
            finally:
                ctx.close()

            group_library(s, browsers["chrome"], servers["root"].url(), manifest)
            group_faults(s, browsers["chrome"], servers["root"].url(), phase)
            group_persistence(s, browsers["chrome"], servers["root"].url())
            if with_audio:
                group_audio(s, browsers["chrome"], servers["root"].url(), manifest)
            else:
                s.skip("BR-16", "30 首逐条真实加载", "A13 / P0-15",
                       "--no-audio 模式跳过（正式 full 阶段执行）")
                s.skip("BR-16b", "四场景真实 play() 出声", "A13 / A11",
                       "--no-audio 模式跳过（正式 full 阶段执行）")
            group_visual(s, browsers["chrome"], servers["root"].url(), with_shots)
            group_environments(s, pw, servers, browsers, phase)

            for b in browsers.values():
                try:
                    b.close()
                except Exception:  # noqa: BLE001
                    pass
    finally:
        for srv in servers.values():
            srv.stop()

    s.print_report()
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["preflight", "full"], default="full")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--no-shots", action="store_true")
    args = ap.parse_args()
    s = run(args.phase, not args.no_audio, not args.no_shots)
    path = s.save("browser.json")
    print("结果已写入: %s" % path)
    return 1 if s.counts()["FAIL"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

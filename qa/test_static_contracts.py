# -*- coding: utf-8 -*-
"""静澜 Stillwave · 静态契约检查（无需浏览器，纯 Python 标准库）。

覆盖：文件树 / 零依赖 / 相对路径 / 首屏体积 / 曲库 Schema 与实测基线一致性 /
中文展示名 / .json-.js 同源 / 字段隔离（A14）/ 冻结常量 / 场景处方 /
定时器与亮度 / 隐私与许可 / 错误语义。

用法：
  python3.9 qa/test_static_contracts.py [--phase preflight|full]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    DOCS, SITE, Suite, load_manifest, load_verified_pool, read_text,
)

FIRST_SCREEN = [
    "index.html", "styles/tokens.css", "styles/app.css",
    "js/config.js", "js/store.js", "js/sources.js", "js/synth.js",
    "js/player.js", "js/timer.js", "js/ui.js", "js/main.js",
    "data/audio-sources.js",
]
EXPECTED_FILES = [
    "index.html", "styles/tokens.css", "styles/app.css",
    "js/config.js", "js/store.js", "js/sources.js", "js/synth.js",
    "js/player.js", "js/timer.js", "js/ui.js", "js/main.js",
    "data/audio-sources.json", "data/audio-sources.js",
    "tools/refresh-sources.py", ".github/workflows/refresh-sources.yml",
]
REQUIRED_FIELDS = [
    "id", "url", "candidates", "bytes", "scene", "kind", "display",
    "originalTitle", "license", "item", "source", "enabled",
    "needsReview", "health", "cors",
]
# 展示层源文件：按 AD-21 不得出现 originalTitle（数据文件与 sources.js 除外）
PRESENTATION_FILES = [
    "index.html", "js/config.js", "js/store.js", "js/synth.js",
    "js/player.js", "js/timer.js", "js/ui.js", "js/main.js",
]
# 仅收录「繁体独有字」，避免把「森林/溪流/林间」等简体常用字误判为杂质
TRADITIONAL_CHARS = set("東臺遊樂區導線雙嶺縣龍禱來崑")
IMPURITY_WORDS = [
    "Kaluga", "GHENT", "BRUSSELS", "Municipal District", "Yamanashi",
    "Fujikawaguchiko", "Taoyuan", "Taichung", "Taitung", "L 50",
    "Zhukovsky", "Thungabadra", "東眼山", "草嶺", "鹿野",
]


def strip_js_comments(src: str) -> str:
    """去掉 JS 注释（块注释 + 行注释），避免「注释里写了关键字」骗过静态断言。

    站点源码内没有 http:// 以外的 `//` 字面量，这里再做一次保护：
    行注释只在 `//` 不紧跟 `:` 时剔除，避免误伤 URL。
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)(^|[^:])\s*//[^\n]*", r"\1", src)
    return src


def js_function_body(src: str, name: str) -> str:
    """按大括号配对截取某个函数的函数体（含花括号），取不到返回空串。

    用于「只在某个渲染/生成函数内」做静态断言：ui.js 既有代码本来就有
    innerHTML（列表渲染），不能用全文件计数去判断分享面板是否安全。
    """
    m = re.search(r"function\s+%s\s*\(" % re.escape(name), src)
    if not m:
        return ""
    i = src.find("{", m.end())
    if i < 0:
        return ""
    depth = 0
    for j in range(i, len(src)):
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    return ""


def all_site_files() -> List[str]:
    # 仓库布局下根目录还包含 .git/、qa/、docs/ 等非站点运行时文件，
    # 遍历时跳过，保证 ST-01 的「源文件树」口径与原工作区一致。
    skip_dirs = {".git", "qa", "docs", "__pycache__"}
    out = []
    for base, dirs, files in os.walk(SITE):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            out.append(os.path.relpath(os.path.join(base, f), SITE))
    return sorted(out)


def js_bundle_object(text: str) -> Dict[str, Any]:
    """从 data/audio-sources.js 中解析 BUNDLED_MANIFEST 对象字面量。"""
    marker = "window.SW.BUNDLED_MANIFEST"
    idx = text.find(marker)
    if idx < 0:
        raise ValueError("未找到 BUNDLED_MANIFEST")
    brace = text.find("{", idx)
    obj, _end = json.JSONDecoder().raw_decode(text[brace:])
    return obj


def run(phase: str = "full") -> Suite:
    s = Suite("static_contracts", phase=phase)
    prov = (phase == "preflight")  # 冻结前：待修复契约只作预检观察

    files = all_site_files()
    manifest = load_manifest()
    pool = load_verified_pool()
    html = read_text("index.html")
    css = read_text("styles/tokens.css") + "\n" + read_text("styles/app.css")
    config_js = read_text("js/config.js")
    sources_js = read_text("js/sources.js")
    main_js = read_text("js/main.js")
    ui_js = read_text("js/ui.js")
    all_js = "\n".join(read_text(p) for p in files if p.endswith(".js"))

    # ---- ST-01 文件树与零依赖 ------------------------------------------
    missing = [f for f in EXPECTED_FILES if f not in files]
    forbidden = [f for f in files if (
        "node_modules" in f or f.startswith("dist/") or f.startswith("build/")
        or f.endswith(("package.json", "package-lock.json", "vite.config.js",
                       "webpack.config.js", "tsconfig.json", ".babelrc"))
        or f.endswith((".php", ".pyc", ".node"))
    )]
    s.check("ST-01", "15 个源文件齐全且仓库零构建/零依赖产物", "P0-07 / A12",
            not missing and not forbidden,
            "15 个文件齐全，无 node_modules/构建配置/服务端代码",
            "缺失=%s 违规=%s 实际文件数=%d" % (missing, forbidden, len(files)),
            environment="静态文件树")

    # ---- ST-02 全部本地资源相对路径 ------------------------------------
    refs = re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', html)
    local = [r for r in refs if not r.startswith(("http://", "https://",
                                                  "mailto:", "#", "data:"))]
    bad = [r for r in local if not r.startswith("./") or r.startswith("/")]
    s.check("ST-02", "index.html 全部本地资源使用 ./ 相对路径", "P0-07 / NFR-01 / A4",
            not bad and len(local) >= 11,
            "全部以 ./ 开头且无 / 绝对开头（CSS2 + JS9 + data1）",
            "引用=%d 违规=%s" % (len(local), bad))

    # ---- ST-03 无 import/export、无框架、无凭据 -------------------------
    modules = re.findall(r'^\s*(?:import|export)\s', all_js, re.M)
    frameworks = re.findall(r'\b(?:React|Vue|Angular|jQuery|require\()', all_js)
    secrets = re.findall(
        r'(?:api[_-]?key|secret[_-]?key|bearer\s|authorization\s*:|GITHUB_TOKEN)',
        "\n".join(read_text(p) for p in files if p.startswith("js/"))
        + html + css, re.I)
    s.check("ST-03", "无 ESM import/export、无框架运行时、前端无凭据常量",
            "P0-07 / NFR-03 / A9 / AD-01",
            not modules and not frameworks and not secrets,
            "modules=0 frameworks=0 credentials=0",
            "modules=%s frameworks=%s credentials=%s"
            % (modules[:3], frameworks[:3], secrets[:3]))

    # ---- ST-04 首屏体积 ------------------------------------------------
    total = sum(os.path.getsize(os.path.join(SITE, p)) for p in FIRST_SCREEN)
    s.check("ST-04", "首屏本地资源总量 < 300KB", "A7 / NFR-07",
            total < 300 * 1024, "< 300KB",
            "%d B (%.1f KB)" % (total, total / 1024.0))
    s.artifacts["firstScreenBytes"] = total

    # ---- ST-05/06/07 曲库规模与构成 ------------------------------------
    tracks = manifest.get("tracks", [])
    by_scene: Dict[str, int] = {}
    by_kind: Dict[str, int] = {}
    for t in tracks:
        by_scene[t.get("scene", "?")] = by_scene.get(t.get("scene", "?"), 0) + 1
        by_kind[t.get("kind", "?")] = by_kind.get(t.get("kind", "?"), 0) + 1
    expect_scene = {"focus": 6, "sleep": 3, "empty": 17, "meditation": 4}
    s.check("ST-05", "权威清单 30 首、count 与 tracks 长度自洽", "P0-15 / A13",
            manifest.get("count") == 30 and len(tracks) == 30,
            "count=30 且 tracks.length=30",
            "count=%s tracks=%d" % (manifest.get("count"), len(tracks)))
    s.check("ST-06", "四场景分布 6 / 3 / 17 / 4", "P0-15 / A13",
            by_scene == expect_scene, json.dumps(expect_scene, ensure_ascii=False),
            json.dumps(by_scene, ensure_ascii=False))
    s.check("ST-07", "21 首 CC 氛围音乐 + 9 首真实自然录音", "A13 / S-11",
            by_kind.get("music") == 21 and by_kind.get("nature") == 9,
            "music=21 nature=9",
            json.dumps(by_kind, ensure_ascii=False))

    # ---- ST-08 每条字段齐全 + candidates[0] === url ---------------------
    field_errors = []
    for t in tracks:
        miss = [k for k in REQUIRED_FIELDS if k not in t]
        if miss:
            field_errors.append("%s 缺 %s" % (t.get("id"), miss))
        if not t.get("candidates") or t["candidates"][0] != t.get("url"):
            field_errors.append("%s candidates[0]!=url" % t.get("id"))
        if t.get("url", "").startswith("http://"):
            field_errors.append("%s 非 HTTPS" % t.get("id"))
    s.check("ST-08", "30 条曲目字段齐全、候选首项等于主 URL、全 HTTPS",
            "S-11 / P0-10 / S-08", not field_errors, "0 条字段缺陷",
            "; ".join(field_errors[:6]) or "0 条缺陷")

    # ---- ST-09 与实测基线逐条一致 --------------------------------------
    pool_urls = {t["url"]: t for t in pool["tracks"]}
    mismatch = []
    for t in tracks:
        p = pool_urls.get(t["url"])
        if not p:
            mismatch.append("未收录于实测曲库: %s" % t.get("id"))
            continue
        # license 允许按 AD-23 本地化为简体中文（"CC，详见来源页"），
        # 但必须仍是 CC 语义或与原实测 URL 完全一致，不可凭空改写许可。
        for k in ("display", "originalTitle", "scene", "kind", "source",
                  "item", "bytes"):
            if t.get(k) != p.get(k):
                mismatch.append("%s.%s: %r != %r" % (t["id"], k, t.get(k), p.get(k)))
        lic = t.get("license", "")
        if lic != p.get("license") and not (
            lic.startswith("http") or "CC" in lic or "知识共享" in lic
        ):
            mismatch.append("%s.license 本地化后丢失 CC 语义: %r" % (t["id"], lic))
    s.check("ST-09", "30 首 URL 与实测曲库逐条一致（零臆造链接）",
            "S-11 / A11 / P0-15", not mismatch, "30/30 与 00-verified-tracks.json 一致",
            "; ".join(mismatch[:6]) or "30/30 一致")

    # ---- ST-10 display 简体中文且无杂质 ---------------------------------
    bad_display = []
    for t in tracks:
        d = t.get("display", "")
        if not d or not re.search(r"[\u4e00-\u9fff]", d):
            bad_display.append("%s 非中文" % t.get("id"))
        if re.search(r"[A-Za-z0-9,./()\-]", d):
            bad_display.append("%s 含拉丁/数字/标点: %s" % (t.get("id"), d))
        if any(ch in TRADITIONAL_CHARS for ch in d):
            bad_display.append("%s 含繁体: %s" % (t.get("id"), d))
    s.check("ST-10", "全部展示名为简体中文、无地名/编号/繁体杂质",
            "P0-18 / A14 / S-12", not bad_display,
            "30/30 简体中文展示名", "; ".join(bad_display[:6]) or "30/30 合规")

    # ---- ST-11 .json / .js 同源 ----------------------------------------
    try:
        js_obj = js_bundle_object(read_text("data/audio-sources.js"))
        same = js_obj == manifest
        detail = "两文件对象完全一致" if same else "存在差异"
    except Exception as exc:  # noqa: BLE001
        same, detail = False, "解析失败: %s" % exc
    s.check("ST-11", "data/audio-sources.js 与 .json 同源一致", "AD-02 / A12",
            same, "对象完全一致", detail)

    # ---- ST-12 展示层零 originalTitle ----------------------------------
    leaks = []
    for p in PRESENTATION_FILES:
        txt = read_text(p)
        # 注释里提及不计入渲染，只统计代码标识符出现（含字符串拼接）
        code_lines = [ln for ln in txt.splitlines()
                      if not ln.lstrip().startswith(("*", "/*", "//", "<!--"))]
        if "originalTitle" in "\n".join(code_lines):
            leaks.append(p)
    s.check("ST-12", "展示层源文件（UI/HTML/契约/播放器）零 originalTitle",
            "A14 / P0-18 / AD-21", not leaks,
            "展示层 0 处 originalTitle 引用", "命中文件: %s" % leaks,
            provisional=prov)

    # ---- ST-13 getAttribution 返回值不含 originalTitle 键 ---------------
    m = re.search(r"function getAttribution\s*\([\s\S]*?\n  \}",
                  sources_js)
    body = m.group(0) if m else ""
    attr_clean = bool(body) and "originalTitle" not in body
    s.check("ST-13", "getAttribution() 返回视图不含 originalTitle 键",
            "A10 / A14 / AD-21", attr_clean,
            "AttributionView 无 originalTitle 键",
            "函数体仍含 originalTitle" if body else "未找到函数体",
            provisional=prov)

    # ---- ST-14 sanitizeForUI 白名单投影 ---------------------------------
    has_sanitize = ("function sanitizeForUI" in sources_js
                    and "sanitizeForUI:" in sources_js)
    s.check("ST-14", "SW.sources.sanitizeForUI() 白名单投影存在并导出",
            "P0-18 / A14 / AD-21", has_sanitize,
            "定义并导出，投影不含 url/originalTitle/bytes/health/candidates",
            "未找到定义/导出" if not has_sanitize else "已导出",
            provisional=prov)

    # ---- ST-15 __STILLWAVE__ 新增契约方法 -------------------------------
    need = ["getVisibleTextSnapshot", "getShareText", "getManifestSummary",
            "getUiSnapshot", "getAttribution", "getState", "getEventLog"]
    missing_api = [k for k in need if k not in main_js]
    s.check("ST-15", "__STILLWAVE__ 契约方法齐全（含 A14 三入口）",
            "A14 / A13 / §4.5", not missing_api,
            "全部方法已挂载: %s" % ",".join(need),
            "缺失: %s" % missing_api, provisional=prov)

    # ---- ST-16 getManifestSummary 含 byKind -----------------------------
    s.check("ST-16", "getManifestSummary() 返回 byKind 构成", "A13 / P0-15",
            "byKind" in sources_js, "含 byKind:{music,nature}",
            "未找到 byKind 字段" if "byKind" not in sources_js else "已包含",
            provisional=prov)

    # ---- ST-17 冻结常量 -------------------------------------------------
    const_ok = all([
        "MAX_TRACKS: 3" in config_js,
        "LOAD_TIMEOUT_MS: 3000" in config_js,
        "CROSSFADE_MS: 600" in config_js,
        "ENABLE_RADIO: false" in config_js,
        "REMOTE_MANIFEST = null" in config_js,
        len(re.findall(r"'white'|'pink'|'brown'", config_js)) >= 3,
    ])
    s.check("ST-17", "关键常量符合设计（≤3 轨 / 3s 回退 / 600ms 过渡 / 电台默认关）",
            "P0-04 / P0-06 / P0-01 / D20", const_ok,
            "MAX_TRACKS=3, LOAD_TIMEOUT=3000, CROSSFADE=600, RADIO=false",
            "常量文本校验未全通过")

    # ---- ST-18 场景处方与 PRD §3.4 一致 ---------------------------------
    presets = [
        ("focus", "masterVolume: 0.45", "timerMinutes: 45", "fadeSeconds: 0"),
        ("sleep", "masterVolume: 0.30", "timerMinutes: 30", "fadeSeconds: 60"),
        ("empty", "masterVolume: 0.40", "timerMinutes: 0", "fadeSeconds: 0"),
        ("meditation", "masterVolume: 0.25", "timerMinutes: 10", "mainTrackId: null"),
    ]
    bad_presets = []
    scene_block = config_js[config_js.find("var SCENES"):config_js.find("var EVENTS")]
    for sid, *checks in presets:
        seg = scene_block[scene_block.find(sid + ": {"):]
        for c in checks:
            if c not in seg[:900]:
                bad_presets.append("%s 缺 %s" % (sid, c))
    s.check("ST-18", "四场景默认配置与 PRD §3.4 处方逐项一致", "P0-01",
            not bad_presets, "音量/定时器/渐弱/亮度/呼吸处方一致",
            "; ".join(bad_presets[:6]) or "四场景一致")

    # ---- ST-19 定时器与渐弱档位 -----------------------------------------
    minutes = set(re.findall(r'data-minutes="(\d+)"', html))
    fades = set(re.findall(r'data-fade="(\d+)"', html))
    timer_js = read_text("js/timer.js")
    s.check("ST-19", "定时器 15/30/45/60/90 + 自定义，渐弱 关/30/60/120s",
            "P0-05", minutes == {"15", "30", "45", "60", "90"}
            and fades == {"0", "30", "60", "120"}
            and "[0, 30, 60, 120]" in timer_js
            and "setFade(0" in timer_js and "cancel" in timer_js,
            "档位齐全且渐弱只操作 fadeGain、取消可恢复",
            "minutes=%s fades=%s" % (sorted(minutes), sorted(fades)))

    # ---- ST-20 响应式 / 亮度 / 无障碍 -----------------------------------
    css_ok = all([
        "@media (max-width: 359px)" in css,
        "@media (min-width: 768px)" in css,
        "@media (min-width: 1440px)" in css,
        "@media (prefers-reduced-motion: reduce)" in css,
        "--touch: 44px" in css,
        'data-brightness="normal"' in css,
        'data-brightness="dark"' in css,
        'data-brightness="extreme"' in css,
        'role="tablist"' in html and 'aria-pressed' in html
        and 'aria-valuenow' in html and 'aria-live="polite"' in html,
    ])
    s.check("ST-20", "320/768/1440 三档响应式 + 亮度三档 + 44px 触控 + aria",
            "P0-08 / A5 / A8", css_ok,
            "三档媒体查询、三档亮度、--touch:44px、tablist/aria-pressed/valuenow/live 齐全",
            "CSS/HTML 校验未全通过")

    # ---- ST-21 隐私：无追踪 / 登录 / cookie / 字体 CDN ------------------
    privacy_bad = re.findall(
        r'(?:google-analytics|gtag|googletagmanager|facebook\.net|doubleclick|'
        r'analytics|document\.cookie|<form|type="password"|@import|fonts\.googleapis)',
        html + css + all_js, re.I)
    s.check("ST-21", "无登录表单 / cookie / 第三方统计 / 广告 / 字体 CDN",
            "P0-09 / A9 / NFR-10", not privacy_bad,
            "0 处追踪/登录/cookie/外部字体引用",
            "命中: %s" % privacy_bad[:6])

    # ---- ST-22 许可署名 -------------------------------------------------
    license_ok = (
        ("音源许可与署名" in html)
        and (("查看原始条目" in (ui_js + html)) or ("在来源站点查看" in ui_js))
        and all(t.get("item", "").startswith("https://archive.org/details/")
                for t in tracks)
        and all(t.get("license") and t.get("source") for t in tracks)
    )
    s.check("ST-22", "页脚署名区块 + 30 条许可/来源/原始条目页字段齐全",
            "P0-16 / A10 / S-06", bool(license_ok),
            "页脚区块 + 30 条 item/license/source 可查证",
            "许可署名要素不全")

    # ---- ST-23 错误语义（控制台清洁的静态保证） -------------------------
    # 注意：ui.getUiSnapshot() 里的 '[role="alertdialog"]' 是「检测弹窗」的查询选择器，
    # 属于 A6 的保障代码而非弹窗本身，故不纳入违规匹配。
    err_bad = re.findall(r'(?<![.\w])console\.error\s*\(|\balert\s*\(|'
                         r'\bconfirm\s*\(|<dialog\b', all_js + html)
    s.check("ST-23", "源码无裸 console.error / alert / dialog（异常内部吞掉）",
            "A6 / §8.4", not err_bad,
            "0 处裸错误输出/弹窗",
            "命中: %s" % err_bad[:6])

    # ---- ST-24 无明文 http:// 资源（混合内容） --------------------------
    http_refs = re.findall(r'(?:src|href)\s*=\s*"http://[^"]+"', html)
    s.check("ST-24", "页面无 http:// 明文资源引用（零混合内容）", "A6 / S-08",
            not http_refs, "0 处 http:// 资源引用", "命中: %s" % http_refs[:4])

    # ---- ST-25 声音库面板的 HTML 契约（P0-1 / P1-09） -------------------
    lib_btn = re.search(r'<button[^>]*id="btn-library"[^>]*>', html)
    lib_panel = re.search(r'<div[^>]*id="library-panel"[^>]*>', html)
    btn_tag = lib_btn.group(0) if lib_btn else ""
    panel_tag = lib_panel.group(0) if lib_panel else ""
    html_lib_ok = (
        bool(btn_tag)
        and 'aria-expanded="false"' in btn_tag
        and 'aria-controls="library-panel"' in btn_tag
        and bool(panel_tag)
        and re.search(r'\shidden(?=[\s>/])', panel_tag) is not None
    )
    s.check("ST-25", "声音库入口按钮 aria 关联面板且面板默认 hidden 收起",
            "P1-09 / A5 / P0-11", html_lib_ok,
            '#btn-library 带 aria-expanded="false" + aria-controls="library-panel"；'
            '#library-panel 默认 hidden',
            "btn=%r panel=%r" % (btn_tag[:120], panel_tag[:120]))

    # ---- ST-26 声音库样式契约 + 库内零 data-track-name -------------------
    # 「库内」= app.css 的声音库区块 + ui.js 的 renderLibraryPanel..renderMixCards 区间；
    # 许可清单里的 data-track-name 属 A14 的 30 条扫描锚点，不在库内，不能误判。
    app_css = read_text("styles/app.css")
    css_start = app_css.find("声音库面板")
    css_end = app_css.find("/* ---------- 轻提示", css_start)
    css_lib_block = app_css[css_start:css_end] if css_start >= 0 and css_end > css_start else ""
    js_start = ui_js.find("function renderLibraryPanel")
    js_end = ui_js.find("function renderMixCards", js_start)
    js_lib_block = ui_js[js_start:js_end] if js_start >= 0 and js_end > js_start else ""
    track_rule = re.search(r"\.lib-track\s*\{[^}]*\}", css_lib_block)
    track_rule_text = track_rule.group(0) if track_rule else ""
    css_lib_ok = (
        ".library-panel" in css_lib_block
        and ".lib-chip" in css_lib_block
        and ".lib-track" in css_lib_block
        and ".is-current" in css_lib_block
        and "min-height: var(--touch)" in track_rule_text
        and "--touch: 44px" in css
        and "data-track-name" not in css_lib_block
        and "data-track-name" not in js_lib_block
    )
    s.check("ST-26", "库面板样式齐全、曲目按钮命中 44px 触控令牌、库内零 data-track-name",
            "P1-09 / A5 / A14", css_lib_ok,
            ".library-panel/.lib-track/.lib-chip/.is-current 齐备；.lib-track "
            "min-height: var(--touch)（--touch: 44px）；库区块 0 处 data-track-name",
            "样式命中={%s} min-height=%r 库CSS含data-track-name=%s "
            "库JS含data-track-name=%s"
            % (",".join(k for k in (".library-panel", ".lib-chip", ".lib-track",
                                    ".is-current") if k in css_lib_block),
               "var(--touch)" if "min-height: var(--touch)" in track_rule_text else "缺失",
               "data-track-name" in css_lib_block,
               "data-track-name" in js_lib_block))

    # ---- ST-27 声音库只消费白名单投影 + 契约三入口 -----------------------
    main_need = ("getLibrarySnapshot", "selectTrack", "setLibraryFilter")
    main_missing = [k for k in main_need if k not in main_js]
    ui_lib_missing = [k for k in ("data-lib-name", "data-lib-track", "getUiTrackList")
                      if k not in ui_js]
    lib_ok = (not main_missing and not ui_lib_missing
              and "originalTitle" not in ui_js)
    s.check("ST-27", "声音库仅渲染 UiTrack 白名单投影且契约三入口齐全",
            "A14 / AD-21 / A13", lib_ok,
            "ui.js 含 data-lib-name/data-lib-track/getUiTrackList 且 0 处 originalTitle；"
            "main.js 导出 getLibrarySnapshot/selectTrack/setLibraryFilter",
            "ui.js 缺失=%s originalTitle=%d；main.js 缺失=%s"
            % (ui_lib_missing, ui_js.count("originalTitle"), main_missing))

    # ---- ST-28 设计令牌对比度（WCAG AA 实算，P0-4a） --------------------
    # 背景：--c-text-3 原值 #6d807c 在 --c-surface 上仅 3.91:1、--c-bg 上 4.44:1，
    # 低于正文 4.5:1。此处用与浏览器无关的 WCAG 相对亮度公式实算，避免靠观感判断。
    tokens_css = read_text("styles/tokens.css")

    def _tok(name, block=None):
        src = tokens_css if block is None else block
        m = re.search(r'--' + re.escape(name) + r'\s*:\s*(#[0-9a-fA-F]{6})', src)
        return m.group(1) if m else None

    def _lum(hx):
        h = hx.lstrip('#')
        ch = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        ch = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
              for c in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]

    def _ratio(fg, bg):
        a, b = _lum(fg), _lum(bg)
        hi, lo = max(a, b), min(a, b)
        return (hi + 0.05) / (lo + 0.05)

    ex_block = ""
    m_ex = re.search(r'html\[data-brightness="extreme"\]\s*\{(.*?)\}', tokens_css, re.S)
    if m_ex:
        ex_block = m_ex.group(1)
    bg = _tok("c-bg")
    surf = _tok("c-surface")
    surf2 = _tok("c-surface-2") or surf
    ex_bg = _tok("c-bg", ex_block) or bg
    contrast_rows = []
    for name, minimum in (("c-text", 4.5), ("c-text-2", 4.5),
                          ("c-text-3", 4.5), ("c-primary-soft", 4.5)):
        fg = _tok(name)
        for label, back in (("bg", bg), ("surface", surf), ("surface-2", surf2)):
            if fg and back:
                contrast_rows.append((name, label, _ratio(fg, back), minimum))
    for name in ("c-primary", "c-primary-soft"):
        fg = _tok(name)
        for label, back in (("bg", bg), ("surface", surf)):
            if fg and back:
                contrast_rows.append((name + "/控件焦点", label,
                                      _ratio(fg, back), 3.0))
    for name in ("c-text-2", "c-text-3"):
        fg = _tok(name)
        if fg and ex_bg:
            contrast_rows.append((name + "/极暗档", "extreme-bg",
                                  _ratio(fg, ex_bg), 4.5))
    contrast_bad = [r for r in contrast_rows if r[2] < r[3]]
    contrast_ok = bool(contrast_rows) and not contrast_bad
    s.check("ST-28", "设计令牌对比度实算达标（正文 4.5:1 / 控件焦点 3:1）",
            "P0-4a / A5 / NFR-06 / WCAG 1.4.3+1.4.11", contrast_ok,
            "全部令牌配对满足阈值；--c-text-3 在 surface/surface-2/bg/极暗档均 ≥4.5",
            "不达标=%s | 样例=%s"
            % (["%s@%s=%.2f<%.1f" % (n, l, r, t) for n, l, r, t in contrast_bad][:6],
               " ".join("%s@%s=%.2f" % (n, l, r)
                        for n, l, r, t in contrast_rows[:5])))

    # ---- ST-29 收藏与预设（P0-2）静态契约 -------------------------------
    store_js = read_text("js/store.js")
    app_css_full = read_text("styles/app.css")
    # 关键：一律在「去注释后的代码」上判断，否则注释里出现同名调用会骗过断言
    #（注入验证时曾实测到这一点：把 removeStorage(K.favorites) 注释掉后必须变红）
    store_code = strip_js_comments(store_js)
    ui_code = strip_js_comments(ui_js)

    # 1) STORAGE_KEYS：两个新键存在且块内恰好 5 个键
    sk_m = re.search(r"var\s+STORAGE_KEYS\s*=\s*\{(.*?)\}", config_js, re.S)
    sk_body = sk_m.group(1) if sk_m else ""
    sk_pairs = dict(re.findall(r"(\w+)\s*:\s*['\"]([^'\"]+)['\"]", sk_body))
    sk_ok = (sk_pairs.get("favorites") == "sw.favorites.v1"
             and sk_pairs.get("presets") == "sw.presets.v1"
             and len(sk_pairs) == 5)

    # 2) clearAll 函数体必须显式清除两个新键（否则「清除本地设置」会留下收藏）
    ca_m = re.search(r"function\s+clearAll\s*\([^)]*\)\s*\{(.*?)\n  \}",
                     store_code, re.S)
    ca_body = ca_m.group(1) if ca_m else ""
    clear_ok = ("removeStorage(K.favorites)" in ca_body
                and "removeStorage(K.presets)" in ca_body)

    # 3) SW.store 导出六个 P0-2 方法
    ex_m = re.search(r"SW\.store\s*=\s*\{(.*?)\n\s*\};", store_code, re.S)
    ex_body = ex_m.group(1) if ex_m else ""
    store_exports = ("getFavorites", "isFavorite", "toggleFavorite",
                     "getPresets", "savePreset", "deletePreset")
    store_export_missing = [n for n in store_exports
                            if not re.search(r"\b%s\s*:" % n, ex_body)]

    # 4) main.js 快照契约 + actions 四个入口
    main_code = strip_js_comments(main_js)
    act_m = re.search(r"function\s+buildActions\s*\([^)]*\)\s*\{(.*?)"
                      r"function\s+buildInject", main_code, re.S)
    act_body = act_m.group(1) if act_m else ""
    mains_missing = [n for n in ("getFavoritesSnapshot", "getPresetsSnapshot",
                                 "getMixSpec") if n not in main_code]
    act_missing = [n for n in ("toggleFavorite", "savePreset", "deletePreset",
                               "applyMix")
                   if not re.search(r"\b%s\s*:" % n, act_body)]

    # 5) 预设命名走内联 input：ui.js 代码零原生弹窗（注释提及不计）
    dialog_hits = re.findall(
        r"(?:window\s*\.\s*)?\b(?:prompt|alert|confirm)\s*\(", ui_code)

    # 6) 预设面板 HTML 契约：按钮 aria 关联 + 面板默认 hidden
    pre_btn_m = re.search(r'<button[^>]*id="btn-presets"[^>]*>', html)
    pre_panel_m = re.search(r'<div[^>]*id="preset-panel"[^>]*>', html)
    pre_btn = pre_btn_m.group(0) if pre_btn_m else ""
    pre_panel = pre_panel_m.group(0) if pre_panel_m else ""
    preset_html_ok = (
        bool(pre_btn) and 'aria-expanded="false"' in pre_btn
        and 'aria-controls="preset-panel"' in pre_btn
        and bool(pre_panel) and re.search(r"\shidden(?=[\s>/])", pre_panel) is not None)

    # 7) #btn-fav-only 必须在 .lib-filters 之外（否则会污染 BR-42 的 chip 计数）
    #    判断方式：先剥掉行内注释（注释里会提到 .lib-filters，位置判断会被带偏），
    #    再要求 renderLibraryPanel 区间内 btn-fav-only 出现在第一个
    #    「<div class="lib-filters"」标记之前 —— 它独占 <p class="lib-flag-row">，
    #    在两组 chip 之前渲染，故必然不在 chip 组内。
    #    另要求 index.html 内任何静态 .lib-filters 块都不含该按钮。
    rl_start = ui_js.find("function renderLibraryPanel")
    rl_end = ui_js.find("function getLibrarySnapshot", rl_start)
    rl_raw = ui_js[rl_start:rl_end] if rl_start >= 0 and rl_end > rl_start else ""
    rl_body = "\n".join(ln for ln in rl_raw.splitlines()
                        if not ln.lstrip().startswith(("*", "/*", "//")))
    i_fav_btn = rl_body.find("btn-fav-only")
    i_filters = rl_body.find('<div class="lib-filters"')
    fav_outside_js = (i_fav_btn >= 0 and i_filters >= 0 and i_fav_btn < i_filters)
    html_filter_blocks = re.findall(r'<div class="lib-filters".*?</div>', html, re.S)
    fav_outside_html = all("btn-fav-only" not in b for b in html_filter_blocks)
    fav_outside = fav_outside_js and fav_outside_html

    # 8) 三个新控件的 44px 触控令牌：按选择器逐条取规则体（含分组选择器）
    rule_blocks = re.findall(r"([^{}]+)\{([^{}]*)\}", app_css_full)
    touch_missing = []
    for cls in (".lib-fav", ".preset-apply", ".preset-delete"):
        hit = False
        for sel, body in rule_blocks:
            if cls in [s.strip() for s in sel.split(",")] and \
                    "min-height: var(--touch)" in body:
                hit = True
                break
        if not hit:
            touch_missing.append(cls)

    # 9) A14：收藏/预设层代码零 originalTitle（注释提及不计）
    a14_hits = ui_code.count("originalTitle") + store_code.count("originalTitle")

    st29_ok = (sk_ok and clear_ok and not store_export_missing
               and not mains_missing and not act_missing and not dialog_hits
               and preset_html_ok and fav_outside and not touch_missing
               and a14_hits == 0)
    s.check("ST-29", "收藏与预设：存储键/清空覆盖/契约入口/零 prompt/44px/零 originalTitle",
            "P0-2 / A14 / A5 / AD-21", st29_ok,
            "STORAGE_KEYS 5 键含 sw.favorites.v1 + sw.presets.v1；clearAll 清两键；"
            "store 导出 6 个方法；main.js 三快照 + actions 四入口；ui.js 零 prompt/"
            "alert/confirm；#btn-presets aria 关联且面板 hidden；#btn-fav-only 在 "
            ".lib-filters 外；.lib-fav/.preset-apply/.preset-delete 均 min-height:"
            "var(--touch)；ui.js+store.js 零 originalTitle",
            "storageKeys=%s 含新键=%s 键数=%d | clearAll=%s | store导出缺=%s | "
            "main快照缺=%s actions缺=%s | 弹窗=%s | presetHTML=%s(fav=%r) | "
            "favOnlyOutside=%s(js=%s html=%s, idx %d<%d) | 缺44px=%s | "
            "originalTitle=%d"
            % ({k: sk_pairs.get(k) for k in ("favorites", "presets")},
               sk_ok, len(sk_pairs), clear_ok, store_export_missing,
               mains_missing, act_missing, dialog_hits[:3], preset_html_ok,
               pre_btn[:80], fav_outside, fav_outside_js, fav_outside_html,
               i_fav_btn, i_filters, touch_missing, a14_hits))

    # ---- ST-30 URL 分享状态（P0-3）静态契约 ------------------------------
    # 1) HTML：#btn-share 可访问（有 aria-label 或可见文案）+ aria-expanded 收起
    #    + aria-controls 指向真实存在的面板且面板默认 hidden
    share_btn_m = re.search(r"<button[^>]*\bid=\"btn-share\"[^>]*>(.*?)</button>",
                            html, re.S)
    share_btn = share_btn_m.group(0) if share_btn_m else ""
    share_btn_text = (share_btn_m.group(1) or "") if share_btn_m else ""
    ctrl_m = re.search(r'aria-controls="([^"]+)"', share_btn)
    share_ctrl = ctrl_m.group(1) if ctrl_m else ""
    share_panel = ""
    if share_ctrl:
        pm = re.search(r"<[^>]*\bid=\"%s\"[^>]*>" % re.escape(share_ctrl), html)
        share_panel = pm.group(0) if pm else ""
    share_named = ("aria-label=" in share_btn
                   or bool(re.sub(r"<[^>]+>", "", share_btn_text).strip()))
    share_html_ok = (
        bool(share_btn) and share_named
        and 'aria-expanded="false"' in share_btn
        and bool(share_panel)
        and re.search(r"\shidden(?=[\s>/])", share_panel) is not None)

    # 2) CSS：至少一条含 share 的选择器命中 44px 触控令牌
    share_touch_ok = False
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", app_css_full):
        sels = [x.strip().lower() for x in sel.split(",")]
        if any("share" in x for x in sels) and "min-height: var(--touch)" in body:
            share_touch_ok = True
            break

    # 3) ui.js：分享相关的渲染/文本生成函数必须存在，且函数体内零 innerHTML、
    #    零 originalTitle（全文件既有 innerHTML 不计，只看分享函数体）
    share_fn_names = sorted(set(re.findall(r"function\s+(\w*[Ss]hare\w*)\s*\(",
                                          ui_code)))
    share_bodies = [js_function_body(ui_code, n) for n in share_fn_names]
    share_body = "\n".join(share_bodies)
    share_ui_ok = (bool(share_fn_names)
                   and share_body.count("innerHTML") == 0
                   and share_body.count("originalTitle") == 0)

    # 4) main.js：契约三入口 + hashchange 监听 + 节流
    #    节流证据按「语义」判：时间戳比较 / 哨兵变量 / setTimeout+clearTimeout 去抖
    #    任一成立即可——这里要求的是「连粘两次只还原一次」，不是某个变量名。
    main_share_missing = [n for n in ("parseShareHash", "getShareHash",
                                      "restoreFromHash")
                          if n not in main_code]
    hc_idx = main_code.find("hashchange")
    hashchange_ok = hc_idx >= 0
    throttle_ok = bool(re.search(
        r"(lastHash\w*|hashThrottle|SHARE_THROTTLE_MS|hashTimer|pending"
        r"|Date\.now\(\)|performance\.now\(\)|clearTimeout\()",
        main_code[hc_idx:hc_idx + 1600])) if hashchange_ok else False

    # 5) actions 暴露 copyShareLink（与点击 #btn-share 等价）
    share_action_ok = re.search(r"\bcopyShareLink\s*:", act_body) is not None

    # 6) 站点发布文件集合仍为 15（新增文件必须显式更新清单）
    #    口径修正是必须的：仓库根布局下还有 README / LICENSE / .nojekyll / .gitignore /
    #    CHANGELOG 等**仓库元文件**，它们不是站点运行时文件。用「全目录文件数 == 15」
    #    会让同一份源码在 meditation/ 布局下 PASS、在仓库根布局下假红（实测 22）。
    #    这里只统计会跟着 Pages 一起发布的子树（index.html + js/styles/data/tools/.github），
    #    既保留「新增站点文件必须更新 EXPECTED_FILES」的原意，又与布局无关。
    PUBLISHED_DIRS = ("js/", "styles/", "data/", "tools/", ".github/")
    published = [f for f in files
                 if f == "index.html" or f.startswith(PUBLISHED_DIRS)]
    unexpected = [f for f in published if f not in EXPECTED_FILES]
    files_ok = (not unexpected
                and all(f in published for f in EXPECTED_FILES)
                and len(EXPECTED_FILES) == 15)

    st30_ok = (share_html_ok and share_touch_ok and share_ui_ok
               and not main_share_missing and hashchange_ok and throttle_ok
               and share_action_ok and files_ok)
    s.check("ST-30", "URL 分享：按钮可访问/面板收起/44px/零 innerHTML/契约入口/hashchange 节流",
            "P0-3 / A5 / A6 / A14 / AD-21", st30_ok,
            "#btn-share 有可访问名与 aria-expanded=false，aria-controls 指向默认 "
            "hidden 的面板；含 share 的选择器命中 min-height:var(--touch)；"
            "ui.js 分享函数的函数体零 innerHTML、零 originalTitle；main.js 含 "
            "parseShareHash/getShareHash/restoreFromHash + hashchange + 节流；"
            "actions 有 copyShareLink；站点文件数=15",
            "btn=%r named=%s ctrl=%r panelHidden=%s | 44px=%s | shareFns=%s "
            "innerHTML=%d originalTitle=%d | main缺=%s hashchange=%s 节流=%s | "
            "copyShareLink=%s | published=%d unexpected=%s"
            % (share_btn[:70], share_named, share_ctrl,
               bool(share_panel) and re.search(r"\shidden(?=[\s>/])", share_panel) is not None,
               share_touch_ok, share_fn_names, share_body.count("innerHTML"),
               share_body.count("originalTitle"), main_share_missing,
               hashchange_ok, throttle_ok, share_action_ok,
               len(published), unexpected[:5]))

    # ---- ST-31 分享链接不得改写访问者本地偏好（P0-3 收口） ----------------
    # 缺陷背景（审计实证）：applyMix → applyScene / applySceneConfigOnly /
    # setMasterVolume / syncSlots 都会 store.savePrefs()，所以「点开别人的分享链接」
    # 会把访问者自己的偏好永久改成对方的配置。修复方式是还原期间挂起偏好回写。
    save_body = js_function_body(store_code, "savePrefs")
    hold_export_ok = (re.search(r"\bholdPrefs\s*:", store_code) is not None
                      and re.search(r"\breleasePrefs\s*:", store_code) is not None)
    hold_decl_ok = (re.search(r"function\s+holdPrefs\s*\(", store_code) is not None
                    and re.search(r"function\s+releasePrefs\s*\(", store_code) is not None)
    i_guard = save_body.find("prefsHoldDepth")
    i_write = save_body.find("writeStorage")
    save_guard_ok = (i_guard >= 0 and i_write > i_guard
                     and re.search(r"return\s*;", save_body[i_guard:i_write]) is not None)
    restore_body = js_function_body(main_code, "restoreFromHash")
    i_hold = restore_body.find("holdPrefs")
    i_apply = restore_body.find("applyMix")
    i_release = restore_body.find("releasePrefs")
    restore_hold_ok = (i_hold >= 0 and i_apply > i_hold and i_release > i_apply
                       and "finally" in restore_body)
    # 反向证据：还原路径上不得出现「先 applyMix 之后再补一次 savePrefs」这类绕过写法
    post_apply = restore_body[i_apply:] if i_apply >= 0 else ""
    no_bypass = "savePrefs" not in post_apply

    st31_ok = (hold_decl_ok and save_guard_ok and hold_export_ok
               and restore_hold_ok and no_bypass)
    s.check("ST-31", "分享还原挂起偏好回写：访问者本地设置不被他人链接覆写",
            "P0-3 / P0-11 / A5", st31_ok,
            "store.js 有 holdPrefs/releasePrefs 并在 savePrefs 内于 writeStorage 之前"
            "提前 return；store 导出两方法；main.js restoreFromHash 在 applyMix 之前"
            "holdPrefs、之后 releasePrefs（finally），applyMix 之后不再补写偏好",
            "holdDecl=%s saveGuard=%s(guard@%d write@%d) export=%s restoreHold=%s"
            "(hold@%d apply@%d release@%d finally=%s) noBypass=%s"
            % (hold_decl_ok, save_guard_ok, i_guard, i_write, hold_export_ok,
               restore_hold_ok, i_hold, i_apply, i_release,
               "finally" in restore_body, no_bypass))

    # ---- 记录元数据 -----------------------------------------------------
    s.artifacts["manifest"] = {
        "schema": manifest.get("schema"), "version": manifest.get("version"),
        "updatedAt": manifest.get("updatedAt"), "count": len(tracks),
        "byScene": by_scene, "byKind": by_kind,
        "candidates": len(manifest.get("candidates", [])),
        "quarantine": len(manifest.get("quarantine", [])),
    }
    s.artifacts["siteFiles"] = files
    s.print_report()
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["preflight", "full"], default="full")
    args = ap.parse_args()
    s = run(args.phase)
    path = s.save("static_contracts.json")
    print("结果已写入: %s" % path)
    # 正式阶段任一 FAIL 返回 1；预检阶段 PROVISIONAL 不影响退出码
    return 1 if s.counts()["FAIL"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

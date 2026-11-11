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

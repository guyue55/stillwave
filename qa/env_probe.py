# -*- coding: utf-8 -*-
"""静澜 Stillwave · 验证环境能力探测（可复现的环境事实，不伪造结果）。

输出 qa/results/env_probe.json：Python / Playwright 版本、四款浏览器启动能力、
Safari WebDriver 可用性、三环境（http 根 / Pages 子路径 / file://）加载事实、
真实在线 MP3 的单曲加载事实。供最终报告「跨浏览器结果表」与环境限制章节引用。
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Suite, ensure_dirs  # noqa: E402
from harness import (  # noqa: E402
    AUDIO_PLAY_PROBE_JS, BROWSER_LABELS, PREVERIFIED_LIMITS, StaticServer,
    file_url, launch_browser, new_page, wait_contract,
)
from playwright.sync_api import sync_playwright  # noqa: E402

SAMPLE_URL = ("https://archive.org/download/jamendo-122281/"
              "01-1038385-Ambient%20Sounddesign-Morning%20Fog.mp3")


def probe_safari_webdriver() -> Dict[str, Any]:
    """尝试用系统 safaridriver 建立真实 Safari 会话（失败如实返回原因）。"""
    port = 48777
    proc = subprocess.Popen(["/usr/bin/safaridriver", "-p", str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result: Dict[str, Any] = {"available": False, "reason": ""}
    try:
        time.sleep(1.0)
        body = json.dumps({
            "capabilities": {"alwaysMatch": {"browserName": "safari"}}
        }).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:%d/session" % port, data=body, method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode())
            sid = payload.get("value", {}).get("sessionId")
            result = {"available": bool(sid), "sessionId": sid,
                      "reason": "" if sid else "未返回 sessionId"}
            if sid:
                try:
                    urllib.request.urlopen(urllib.request.Request(
                        "http://127.0.0.1:%d/session/%s" % (port, sid),
                        method="DELETE"), timeout=5).read()
                except Exception:  # noqa: BLE001
                    pass
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:500]
        result = {"available": False, "reason": "HTTP %s: %s" % (exc.code, detail)}
    except Exception as exc:  # noqa: BLE001
        result = {"available": False,
                  "reason": "%s: %s" % (type(exc).__name__, str(exc)[:300])}
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
    return result


def run() -> Suite:
    s = Suite("env_probe", phase="environment")
    ensure_dirs()
    facts: Dict[str, Any] = {
        "python": sys.version.split()[0],
        "pythonExecutable": sys.executable,
        "platform": platform.platform(),
    }
    s.check("EP-01", "QA Python 3.9 + Playwright 可用", "A2 / 工具链路",
            sys.version_info[:2] == (3, 9),
            "Python 3.9 + playwright.sync_api 可导入",
            "Python %s" % sys.version.split()[0])

    root = StaticServer(prefix="")
    sub = StaticServer(prefix="stillwave_meditation")
    servers = [root, sub]
    browser_errors: Dict[str, str] = {}
    launch_results: Dict[str, bool] = {}

    try:
        with sync_playwright() as pw:
            for name in ("chrome", "chromium", "firefox", "webkit"):
                # Round 2：主理人已实测定稿「仅 channel=chrome 可用」，明确要求
                # 「请勿再重试」。对已定稿不可用的浏览器不再重复启动（避免无意义的
                # 30s 超时等待），直接引用定稿事实如实标 UNVERIFIED。
                if name in PREVERIFIED_LIMITS:
                    launch_results[name] = False
                    browser_errors[name] = PREVERIFIED_LIMITS[name]
                    s.unverified(
                        "EP-02.%s" % name,
                        "浏览器启动能力：%s" % BROWSER_LABELS[name],
                        "A2 / 跨浏览器",
                        "环境限制（主理人 Round 2 实测定稿，本轮不重复启动）：%s"
                        % PREVERIFIED_LIMITS[name],
                        environment=BROWSER_LABELS[name])
                    continue
                t0 = time.time()
                browser, err = launch_browser(pw, name)
                launch_results[name] = bool(browser)
                if err:
                    browser_errors[name] = err
                # 环境能力缺失属于「环境限制」，如实标注 UNVERIFIED，
                # 既不计为源码缺陷，也不伪装成通过。
                if browser:
                    s.check("EP-02.%s" % name,
                            "浏览器启动能力：%s" % BROWSER_LABELS[name],
                            "A2 / 跨浏览器", True,
                            "可启动真实浏览器实例",
                            "OK（%.1fs）" % (time.time() - t0),
                            environment=BROWSER_LABELS[name])
                else:
                    s.unverified("EP-02.%s" % name,
                                 "浏览器启动能力：%s" % BROWSER_LABELS[name],
                                 "A2 / 跨浏览器",
                                 "环境限制，二进制不可用：%s" % err,
                                 environment=BROWSER_LABELS[name])
                if browser:
                    try:
                        browser.close()
                    except Exception:  # noqa: BLE001
                        pass

            # 三环境加载事实（Chrome）
            browser, err = launch_browser(pw, "chrome")
            if browser:
                for label, url in (
                    ("http-root", root.url()),
                    ("pages-subpath", sub.url()),
                    ("file-protocol", file_url()),
                ):
                    ctx, page, ev = new_page(browser)
                    try:
                        page.goto(url, wait_until="load", timeout=20000)
                        ok = wait_contract(page)
                        st = page.evaluate("window.__STILLWAVE__.getState()") if ok else {}
                        facts[label] = {
                            "url": url, "contract": ok,
                            "audioContext": st.get("audioContext"),
                            "playing": st.get("playing"),
                            "manifestCount": st.get("manifest", {}).get("count"),
                            "storageMode": st.get("storageMode"),
                            "resolvedRemotes": st.get("resolvedRemotes"),
                            "consoleErrors": len(ev.console_errors),
                            "pageErrors": len(ev.page_errors),
                            "httpErrors": len(ev.http_errors),
                            "requests": len(ev.requests),
                        }
                        s.check("EP-03.%s" % label,
                                "%s 环境加载：契约挂载 / 零异常 / 30 首内置" % label,
                                "A4 / A6 / P0-11",
                                ok and st.get("manifest", {}).get("count") == 30
                                and st.get("audioContext") == "none"
                                and st.get("playing") is False
                                and not ev.page_errors and not ev.http_errors,
                                "contract=true, count=30, audioContext=none, playing=false, 0 异常",
                                json.dumps(facts[label], ensure_ascii=False)[:300],
                                environment=label)
                    except Exception as exc:  # noqa: BLE001
                        s.unverified("EP-03.%s" % label,
                                     "%s 环境加载" % label, "A4",
                                     "%s: %s" % (type(exc).__name__, str(exc)[:200]))
                    finally:
                        ctx.close()

                # 单曲真实播放事实
                ctx, page, ev = new_page(browser)
                try:
                    page.goto(root.url(), wait_until="load")
                    wait_contract(page)
                    probe = page.evaluate(AUDIO_PLAY_PROBE_JS, SAMPLE_URL)
                    facts["sampleAudio"] = probe
                    s.check("EP-04", "真实 Chrome 可播放 archive.org MP3（出声证据）",
                            "A11 / A13",
                            probe.get("ok") is True and probe.get("readyState", 0) >= 3,
                            "play() 成功、readyState>=3、currentTime 前进",
                            json.dumps(probe, ensure_ascii=False),
                            environment="Google Chrome")
                except Exception as exc:  # noqa: BLE001
                    s.unverified("EP-04", "真实 Chrome 播放 archive.org MP3",
                                 "A11", "异常: %s" % exc)
                finally:
                    ctx.close()
                browser.close()
            else:
                s.unverified("EP-03", "三环境加载探测", "A4",
                             "Chrome 不可用: %s" % err)
    finally:
        for srv in servers:
            srv.stop()

    # Safari WebDriver 能力（独立于 Playwright 的真实 Safari 通道）
    safari = probe_safari_webdriver()
    facts["safariWebDriver"] = safari
    if safari.get("available"):
        s.check("EP-05", "系统 Safari 经 safaridriver 可驱动", "A2 / 跨浏览器",
                True, "可建立 WebDriver 会话", "OK", environment="Safari")
    else:
        s.unverified("EP-05", "系统 Safari 经 safaridriver 可驱动",
                     "A2 / 跨浏览器",
                     "环境限制（需在 Safari 设置开启「允许远程自动化」，需用户交互/管理员权限）：%s"
                     % safari.get("reason"), environment="Safari")
    s.unverified(
        "EP-06", "Safari / Firefox 完整使用路径（若环境不可用）",
        "A2",
        "环境限制（主理人 Round 2 实测定稿，本轮不重复启动 Firefox/WebKit；"
        "Chrome 结果不得外推）：%s" % json.dumps(
            {"browserErrors": browser_errors, "safari": safari},
            ensure_ascii=False)[:600]
        if (browser_errors.get("firefox") or browser_errors.get("webkit")
            or not safari.get("available")) else "环境齐备，无需说明")

    s.artifacts["facts"] = facts
    s.artifacts["browserLaunchResults"] = launch_results
    s.artifacts["browserErrors"] = browser_errors
    s.print_report()
    return s


def main() -> int:
    s = run()
    path = s.save("env_probe.json")
    print("结果已写入: %s" % path)
    return 0  # 环境探测不因能力缺失而失败，只如实记录


if __name__ == "__main__":
    sys.exit(main())

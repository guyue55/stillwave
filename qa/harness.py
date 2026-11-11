# -*- coding: utf-8 -*-
"""静澜 Stillwave · 真实验证环境装置（静态服务 / 浏览器 / 证据采集）。

- 起两个本地静态服务：根路径部署 + GitHub Pages 风格子路径部署。
- 启动真实浏览器（系统 Chrome / Playwright Chromium / Firefox / WebKit，按能力探测）。
- 采集控制台错误、未捕获异常、失败请求、HTTP 4xx/5xx、全部请求 URL，供 A6 / A9 断言。
- 提供 30 首曲目逐条加载探测与真实播放探测的浏览器端 JS。
"""
from __future__ import annotations

import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

from common import SHOTS_DIR, SITE

CHROME_ARGS = ["--autoplay-policy=no-user-gesture-required"]


# ---------------------------------------------------------------------------
# 本地静态服务
# ---------------------------------------------------------------------------
class _QuietHandler(SimpleHTTPRequestHandler):
    """静态文件 handler；支持把 /<repo>/ 前缀剥离后映射到站点根目录。

    favicon_204=True 时，对浏览器自动发起的 /favicon.ico 返回 204，
    用于中性化「站点未提供 favicon」这一环境噪声；该噪声另由独立用例
    在 favicon_204=False 的服务上如实观测并上报，绝不掩盖。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._prefix = kwargs.pop("url_prefix", "")
        self._favicon_204 = kwargs.pop("favicon_204", True)
        super().__init__(*args, **kwargs)

    def translate_path(self, path: str) -> str:
        if self._prefix and path.startswith(self._prefix):
            path = path[len(self._prefix):] or "/"
        return super().translate_path(path)

    def do_GET(self) -> None:
        if self._favicon_204 and self.path.split("?")[0].endswith("/favicon.ico"):
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, fmt: str, *args: Any) -> None:
        return  # 静默，避免污染 QA 输出

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class StaticServer:
    """在后台线程运行一个静态 HTTP 服务。

    prefix 传仓库名（不带斜杠），如 "stillwave_meditation"，
    用于模拟 GitHub Pages 子路径部署。
    """

    def __init__(self, root: str = SITE, prefix: str = "",
                 favicon_204: bool = True) -> None:
        self.prefix = prefix.strip("/")
        url_prefix = ("/" + self.prefix + "/") if self.prefix else ""
        handler = partial(_QuietHandler, directory=root, url_prefix=url_prefix,
                          favicon_204=favicon_204)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path: str = "index.html?debug=1") -> str:
        base = ("/" + self.prefix) if self.prefix else ""
        return "http://127.0.0.1:%d%s/%s" % (self.port, base, path.lstrip("/"))

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def file_url(debug: bool = True) -> str:
    """file:// 双击打开环境。"""
    return "file://" + os.path.join(SITE, "index.html") + ("?debug=1" if debug else "")


# ---------------------------------------------------------------------------
# 证据采集
# ---------------------------------------------------------------------------
class Evidence:
    """控制台 / 网络请求 / 页面异常证据。"""

    def __init__(self) -> None:
        self.console_errors: List[str] = []
        self.console_warnings: List[str] = []
        self.page_errors: List[str] = []
        self.request_failed: List[Dict[str, str]] = []
        self.http_errors: List[Dict[str, Any]] = []
        self.requests: List[Dict[str, str]] = []
        self.sensitive_headers: List[Dict[str, str]] = []

    def attach(self, page: Any) -> "Evidence":
        def on_console(msg: Any) -> None:
            if msg.type == "error":
                self.console_errors.append(msg.text)
            elif msg.type == "warning":
                self.console_warnings.append(msg.text)

        def on_page_error(exc: Any) -> None:
            self.page_errors.append(str(exc))

        def on_request_failed(req: Any) -> None:
            failure = req.failure
            self.request_failed.append({
                "url": req.url,
                "failure": (failure or "unknown") if isinstance(failure, str)
                else str(failure),
            })

        def on_response(resp: Any) -> None:
            if resp.status >= 400:
                self.http_errors.append({"url": resp.url, "status": resp.status})

        def on_request(req: Any) -> None:
            self.requests.append({
                "url": req.url,
                "method": req.method,
                "resourceType": req.resource_type,
            })
            try:
                lowered = {k.lower() for k in req.headers}
                hit = lowered & {"authorization", "cookie", "x-api-key",
                                 "x-auth-token", "proxy-authorization"}
                if hit:
                    self.sensitive_headers.append({
                        "url": req.url, "headers": ",".join(sorted(hit))
                    })
            except Exception:  # noqa: BLE001
                pass

        page.on("console", on_console)
        page.on("pageerror", on_page_error)
        page.on("requestfailed", on_request_failed)
        page.on("response", on_response)
        page.on("request", on_request)
        return self

    def as_dict(self) -> Dict[str, Any]:
        return {
            "consoleErrors": self.console_errors,
            "consoleWarnings": self.console_warnings,
            "pageErrors": self.page_errors,
            "requestFailed": self.request_failed,
            "httpErrors": self.http_errors,
            "requests": self.requests,
            "requestCount": len(self.requests),
            "sensitiveHeaders": self.sensitive_headers,
        }


# ---------------------------------------------------------------------------
# 浏览器
# ---------------------------------------------------------------------------
BROWSER_LABELS = {
    "chrome": "Google Chrome (channel=chrome)",
    "chromium": "Playwright Chromium headless shell",
    "firefox": "Mozilla Firefox",
    "webkit": "WebKit (Safari 语义)",
}

# Round 2 环境定稿（主理人实测，Playwright 1.60.0 / macOS arm64）：
#   p.chromium.launch(channel="chrome") 可用；
#   p.firefox.launch(headless=True, timeout=15000) 与
#   p.webkit.launch(headless=True, timeout=15000) 均 Timeout 15000ms exceeded
#   （Firefox 卡 Nightly.app，WebKit 卡 pw_run.sh），二进制已下载但本环境启动超时；
#   Playwright chromium headless shell 本机修订 1208 与 1.60 期望修订不匹配。
# 按主理人指示「请勿再重试」：本轮不再重复启动这些浏览器，逐项 UNVERIFIED，
# 且绝不把 Chrome 的实测结果外推到 Firefox / Safari。
PREVERIFIED_LIMITS = {
    "chromium": ("Playwright chromium headless shell 本机修订 1208 与 "
                 "Playwright 1.60 期望修订不匹配，本环境不可用"),
    "firefox": ("二进制 firefox-1522 已下载（275MB），但本环境启动超时："
                "主理人实测 p.firefox.launch(headless=True, timeout=15000) "
                "→ Timeout 15000ms exceeded（卡在 Nightly.app）"),
    "webkit": ("二进制 webkit-2287 已下载（304MB），但本环境启动超时："
               "主理人实测 p.webkit.launch(headless=True, timeout=15000) "
               "→ Timeout 15000ms exceeded（卡在 pw_run.sh）"),
}


def launch_browser(pw: Any, name: str) -> Tuple[Any, Optional[str]]:
    """启动指定浏览器；不可用时返回 (None, 原因)，绝不伪造。"""
    try:
        if name == "chrome":
            b = pw.chromium.launch(channel="chrome", headless=True, args=CHROME_ARGS)
        elif name == "chromium":
            b = pw.chromium.launch(headless=True, args=CHROME_ARGS)
        elif name == "firefox":
            b = pw.firefox.launch(headless=True)
        elif name == "webkit":
            b = pw.webkit.launch(headless=True)
        else:
            return None, "未知浏览器名称: %s" % name
        return b, None
    except Exception as exc:  # noqa: BLE001
        return None, "%s: %s" % (type(exc).__name__, str(exc)[:260])


def new_page(browser: Any, viewport: Tuple[int, int] = (1440, 900),
             reduced_motion: bool = False) -> Tuple[Any, Any, Evidence]:
    """新建上下文与页面，并挂上证据采集。"""
    ctx = browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]},
        reduced_motion="reduce" if reduced_motion else "no-preference",
        ignore_https_errors=True,
    )
    page = ctx.new_page()
    ev = Evidence().attach(page)
    return ctx, page, ev


def wait_contract(page: Any, timeout: int = 12000) -> bool:
    """等待引导装配完成（SW.main + __STILLWAVE__ 均挂载）。"""
    try:
        page.wait_for_function(
            "window.__STILLWAVE__ && window.SW && window.SW.main "
            "&& typeof window.__STILLWAVE__.getState === 'function'",
            timeout=timeout,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def state(page: Any) -> Dict[str, Any]:
    """读取只读状态快照。"""
    return page.evaluate("window.__STILLWAVE__.getState()")


def screenshot(page: Any, name: str) -> str:
    """全页截图到 qa/screenshots/。"""
    os.makedirs(SHOTS_DIR, exist_ok=True)
    path = os.path.join(SHOTS_DIR, name)
    page.screenshot(path=path, full_page=True)
    return path


# ---------------------------------------------------------------------------
# 浏览器端音频探测 JS
# ---------------------------------------------------------------------------
AUDIO_LOAD_PROBE_JS = """
async (urls) => {
  const CONCURRENCY = 3;
  const one = (u) => new Promise((resolve) => {
    const a = document.createElement('audio');
    a.crossOrigin = 'anonymous';
    a.preload = 'auto';
    a.setAttribute('aria-hidden', 'true');
    let done = false;
    const timer = setTimeout(() => finish(false, 'timeout'), 20000);
    function finish(ok, reason) {
      if (done) return;
      done = true;
      clearTimeout(timer);
      const out = {
        url: u, ok: ok, reason: reason,
        readyState: a.readyState,
        duration: (isFinite(a.duration) ? a.duration : 0),
        networkState: a.networkState
      };
      try { a.pause(); a.removeAttribute('src'); } catch (e) {}
      resolve(out);
    }
    a.addEventListener('loadedmetadata', () => {
      if (a.readyState >= 1) finish(true, 'loadedmetadata');
    });
    a.addEventListener('canplay', () => finish(true, 'canplay'));
    a.addEventListener('error', () => finish(false, 'error'));
    a.src = u;
    try { a.load(); } catch (e) { finish(false, 'load-exception'); }
  });
  const results = new Array(urls.length);
  let cursor = 0;
  async function worker() {
    while (cursor < urls.length) {
      const i = cursor++;
      await new Promise(r => setTimeout(r, 250));
      results[i] = await one(urls[i]);
    }
  }
  await Promise.all(Array.from(
    {length: Math.min(CONCURRENCY, urls.length)}, worker
  ));
  return results;
}
"""

AUDIO_PLAY_PROBE_JS = """
async (url) => {
  const a = new Audio();
  a.crossOrigin = 'anonymous';
  a.preload = 'auto';
  a.loop = true;
  a.src = url;
  try { await a.play(); }
  catch (e) { return {ok:false, reason:'play-rejected:' + (e && e.name || 'unknown')}; }
  const t0 = a.currentTime;
  await new Promise(r => setTimeout(r, 1500));
  const t1 = a.currentTime;
  const out = {
    ok: (!a.paused && (t1 - t0) > 0.05),
    advanced: Math.round((t1 - t0) * 1000) / 1000,
    paused: a.paused, readyState: a.readyState,
    duration: (isFinite(a.duration) ? a.duration : 0)
  };
  try { a.pause(); a.removeAttribute('src'); } catch (e) {}
  return out;
}
"""

VISIBLE_TEXT_PROBE_JS = """
() => {
  const SKIP = new Set(['SCRIPT','STYLE','NOSCRIPT','TEMPLATE','SVG','HEAD']);
  const parts = [];
  const walk = (node) => {
    if (node.nodeType === 3) {
      const p = node.parentElement;
      if (p && !SKIP.has(p.tagName) && !p.closest('[aria-hidden="true"]') &&
          !p.closest('[hidden]')) {
        const s = node.nodeValue.trim();
        if (s) parts.push(s);
      }
      return;
    }
    if (node.nodeType !== 1) return;
    if (SKIP.has(node.tagName)) return;
    if (node.hasAttribute('hidden') || node.getAttribute('aria-hidden') === 'true') return;
    const st = window.getComputedStyle(node);
    if (st.display === 'none' || st.visibility === 'hidden') return;
    for (let i = 0; i < node.childNodes.length; i++) walk(node.childNodes[i]);
  };
  walk(document.body);
  return parts.join('\\n');
}
"""

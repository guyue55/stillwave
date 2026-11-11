#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静澜 Stillwave · 曲库刷新与健康检查工具（仅 Python 3.9+ 标准库）。

职责（架构 §2.4 / T02）：
  1. 从 docs/00-verified-tracks.json 程序化生成权威清单（--init-from）；
  2. HEAD / Range / Content-Type / CORS / 体积探测，隔离失效项；
  3. 从 archive.org 动态发现候选并做规则过滤（结果只进 candidates[]）；
  4. 原子双写 data/audio-sources.json 与 data/audio-sources.js（同源）；
  5. 输出机器可读 JSON 报告，供 QA 直接断言。

设计红线：
  - 不臆造任何未实测 URL：播放 URL 逐字来自 00-verified-tracks.json；
  - 动态发现的候选恒为 verified=false / needsReview=true，0 条进入 tracks；
  - 更新失败绝不清空现有可用清单；退出码 0/2/3/4。

用法示例：
  python3 tools/refresh-sources.py --init-from ../docs/00-verified-tracks.json --apply
  python3 tools/refresh-sources.py --offline --dry-run --json-report /tmp/report.json
  python3 tools/refresh-sources.py --check-only --json-report /tmp/health.json
  python3 tools/refresh-sources.py --discover --max-new 10 --dry-run
  python3 tools/refresh-sources.py --fail-inject "<url>=404" --check-only
  python3 tools/refresh-sources.py --apply
"""

import argparse
import concurrent.futures
import datetime
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
JSON_PATH = os.path.join(DATA_DIR, "audio-sources.json")
JS_PATH = os.path.join(DATA_DIR, "audio-sources.js")
# 兼容两种布局：GitHub 仓库内 docs/（站点即仓库根），以及原始工作区中与
# 站点平级的 docs/。仅在缺少清单且未指定 --init-from 时用于引导。
_CANDIDATE_SOURCES = (
    os.path.join(ROOT, "docs", "00-verified-tracks.json"),
    os.path.normpath(os.path.join(ROOT, "..", "docs", "00-verified-tracks.json")),
)
DEFAULT_SOURCE = next(
    (p for p in _CANDIDATE_SOURCES if os.path.isfile(p)), _CANDIDATE_SOURCES[0]
)

SCHEMA = "stillwave-audio-manifest/v1"
PLACEHOLDER_LICENSE = "CC，详见来源页"
LICENSE_PLACEHOLDERS = {"", "cc (see item page)", None}
ALLOWED_CONTENT_TYPES = (
    "audio/mpeg", "audio/ogg", "audio/mp4", "application/ogg",
    "audio/x-m4a", "audio/aac", "audio/mp3",
)
EXPECTED_COUNTS = {"focus": 6, "sleep": 3, "empty": 17, "meditation": 4}
REQUIRED_TRACK_FIELDS = (
    "id", "url", "candidates", "bytes", "scene", "kind", "display",
    "originalTitle", "license", "attribution", "item", "source",
    "enabled", "needsReview", "health", "cors",
)
CHECK_TIMEOUT = 8
DISCOVER_TIMEOUT = 8
MAX_WORKERS = 6

ARCHIVE_SEARCH = "https://archive.org/advancedsearch.php"
ARCHIVE_METADATA = "https://archive.org/metadata/{identifier}"
ARCHIVE_DOWNLOAD = "https://archive.org/download/{identifier}/{filename}"

BLACKLIST_PATTERNS = [
    re.compile(r"\btalk\b", re.I), re.compile(r"lecture", re.I),
    re.compile(r"dhamma", re.I), re.compile(r"sermon", re.I),
    re.compile(r"podcast", re.I), re.compile(r"speech", re.I),
    re.compile(r"guided", re.I), re.compile(r"interview", re.I),
    re.compile(r"radio", re.I), re.compile(r"news", re.I),
    re.compile(r"口播|讲座|播客|导词|开示|说法"),
    re.compile(r"\d{3,}[\s\-]?\d{3,}"),
]
IDENTIFIER_PREFIXES = ("jamendo-", "aporee_")
ALLOWED_EXTENSIONS = (".mp3", ".ogg", ".m4a")
MIN_BYTES = 500000
MAX_BYTES = 20000000


def utc_now_iso():
    """返回 ISO 8601 UTC 时间戳。"""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# 清单生成 / 校验
# ---------------------------------------------------------------------------
def normalize_license(raw):
    """许可字段规范化：缺失或占位符回填「CC，详见来源页」，完整 URL 逐字保留。"""
    if raw is None:
        return PLACEHOLDER_LICENSE
    text = str(raw).strip()
    if not text or text.lower() in LICENSE_PLACEHOLDERS:
        return PLACEHOLDER_LICENSE
    return text


def build_attribution(source, license_text):
    """组装署名文案（绝不包含 originalTitle，避免地名/电话等杂质，AD-06）。"""
    return "%s · %s · 经 Internet Archive 分发" % (source, license_text)


def track_id_from_item(item):
    """稳定标识 = item 末段（架构 §4.1）。"""
    tail = str(item).rstrip("/").split("/")[-1]
    return tail or "track"


def build_manifest(source_path):
    """从 00-verified-tracks.json 程序化生成权威清单（URL 逐字一致）。"""
    with open(source_path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    src_tracks = raw.get("tracks", [])
    tracks = []
    for item in src_tracks:
        url = item["url"]  # 逐字保留，绝不改写
        license_text = normalize_license(item.get("license"))
        record = {
            "id": track_id_from_item(item["item"]),
            "url": url,
            "candidates": [url],  # candidates[0] === url
            "bytes": int(item.get("bytes", 0)),
            "scene": item["scene"],
            "kind": item["kind"],
            "display": item["display"],
            "originalTitle": item.get("originalTitle", ""),
            "license": license_text,
            "attribution": build_attribution(item["source"], license_text),
            "item": item["item"],
            "source": item["source"],
            "enabled": True,
            "needsReview": False,
            "health": "alive",
            "cors": True,
            "verified": True,
        }
        tracks.append(record)

    scenes = {}
    for scene in EXPECTED_COUNTS:
        scenes[scene] = sum(1 for t in tracks if t["scene"] == scene)

    manifest = {
        "schema": SCHEMA,
        "version": 1,
        "updatedAt": utc_now_iso(),
        "verifiedAt": raw.get("verifiedAt", "2026-11-09"),
        "count": len(tracks),
        "scenes": scenes,
        "tracks": tracks,
        "candidates": [],
        "quarantine": [],
    }
    return manifest


def validate_manifest(manifest):
    """Schema 校验；返回 (是否通过, 错误列表)。"""
    errors = []
    if not isinstance(manifest, dict):
        return False, ["清单根节点必须为对象"]
    if manifest.get("schema") != SCHEMA:
        errors.append("schema 不匹配：%r" % manifest.get("schema"))
    tracks = manifest.get("tracks")
    if not isinstance(tracks, list):
        errors.append("tracks 必须为数组")
        return False, errors
    if len(tracks) != 30:
        errors.append("tracks 长度应为 30，实际 %d" % len(tracks))
    if manifest.get("count") != len(tracks):
        errors.append("count 与 tracks 长度不一致")

    scenes = {}
    for scene in EXPECTED_COUNTS:
        scenes[scene] = 0
    for index, track in enumerate(tracks):
        for field in REQUIRED_TRACK_FIELDS:
            if field not in track:
                errors.append("tracks[%d] 缺少字段 %s" % (index, field))
        if not track.get("candidates") or track["candidates"][0] != track.get("url"):
            errors.append("tracks[%d].candidates[0] 必须等于 url" % index)
        if track.get("scene") in scenes:
            scenes[track["scene"]] += 1
        if track.get("needsReview") is True:
            errors.append("tracks[%d] 含未审定条目（needsReview=true）" % index)
        if track.get("verified") is False:
            errors.append("tracks[%d] 含未校验条目（verified=false）" % index)
    for scene, expected in EXPECTED_COUNTS.items():
        if scenes.get(scene) != expected:
            errors.append("场景 %s 应为 %d 首，实际 %d 首" % (scene, expected, scenes.get(scene, 0)))
    if manifest.get("scenes") != scenes:
        errors.append("scenes 统计与实际分布不一致")
    if not isinstance(manifest.get("candidates"), list):
        errors.append("candidates 必须为数组")
    if not isinstance(manifest.get("quarantine"), list):
        errors.append("quarantine 必须为数组")
    for index, cand in enumerate(manifest.get("candidates", [])):
        if cand.get("needsReview") is not True or cand.get("verified") is not False:
            errors.append("candidates[%d] 必须 needsReview=true 且 verified=false" % index)
    return (len(errors) == 0), errors


# ---------------------------------------------------------------------------
# 原子双写
# ---------------------------------------------------------------------------
def render_js(manifest):
    """生成与 .json 完全同源的 script-loadable 快照。"""
    payload = json.dumps(manifest, ensure_ascii=False, indent=2)
    return "window.SW = window.SW || {};\nwindow.SW.BUNDLED_MANIFEST = %s;\n" % payload


def atomic_write(path, text):
    """临时文件 + os.replace 原子写，中途异常不破坏上一版。"""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".sw-tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_both(manifest):
    """原子双写 .json 与 .js（两者由同一对象生成，保证同源）。"""
    json_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    js_text = render_js(manifest)
    atomic_write(JSON_PATH, json_text)
    atomic_write(JS_PATH, js_text)
    return {"json": JSON_PATH, "js": JS_PATH, "inSync": True}


def read_manifest():
    """读取现有权威清单；不存在或解析失败返回 None（不抛错）。"""
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def js_in_sync(manifest):
    """校验现有 .js 快照与给定清单是否同源（读取 BUNDLED_MANIFEST 字面量比对）。"""
    try:
        with open(JS_PATH, "r", encoding="utf-8") as handle:
            text = handle.read()
        prefix = "window.SW.BUNDLED_MANIFEST ="
        start = text.find(prefix)
        if start < 0:
            return False
        body = text[start + len(prefix):].strip()
        if body.endswith(";"):
            body = body[:-1]
        return json.loads(body) == manifest
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# 健康探测（HEAD → Range 复核 → Content-Type → CORS → 体积）
# ---------------------------------------------------------------------------
def _http_probe(url, method, headers=None, timeout=CHECK_TIMEOUT):
    """单次 HTTP 探测，返回 (status, headers_dict, body_prefix)；异常返回 (None, {}, b'')。"""
    req = urllib.request.Request(url, method=method, headers=headers or {})
    req.add_header("User-Agent", "StillwaveManifestRefresh/1 (public anonymous GET)")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = b""
            if method == "GET":
                body = resp.read(2048)
            return resp.status, dict(resp.headers.items()), body
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers.items() or {}), b""
    except Exception:
        return None, {}, b""


def _cors_ok(headers):
    """CORS 头存在且允许跨源（S-08：无 ACAO 不得进 Web Audio 增益链路）。"""
    for key in headers:
        if key.lower() == "access-control-allow-origin":
            value = str(headers[key]).strip()
            return value == "*" or bool(value)
    return False


def _content_type_ok(headers):
    ctype = ""
    for key in headers:
        if key.lower() == "content-type":
            ctype = str(headers[key]).lower().split(";")[0].strip()
            break
    return ctype in ALLOWED_CONTENT_TYPES


def check_one(track, offline=False):
    """按架构 §2.4 判定表探测单条；返回 {id, alive, health, cors, reason, sizeMismatch}。"""
    url = track.get("url", "")
    result = {
        "id": track.get("id"), "alive": True, "health": "alive",
        "cors": True, "reason": "", "sizeMismatch": False,
    }
    if offline:
        result["reason"] = "offline-skip"
        return result

    status, headers, _ = _http_probe(url, "HEAD")
    if status not in (200, 206):
        # 改用 GET + Range 复核
        status, headers, _ = _http_probe(url, "GET", {"Range": "bytes=0-1023"})
    if status not in (200, 206):
        result.update({"alive": False, "health": "dead", "reason": "http-%s" % status})
        return result
    if not _content_type_ok(headers):
        result.update({"alive": False, "health": "dead", "reason": "content-type"})
        return result
    if not _cors_ok(headers):
        result["cors"] = False
        result["reason"] = "cors-missing"
    # 体积容差 ±5%（仅记录偏差，不删除）
    length = None
    for key in headers:
        if key.lower() == "content-range":
            try:
                length = int(str(headers[key]).split("/")[-1])
            except ValueError:
                length = None
            break
    if length is None:
        for key in headers:
            if key.lower() == "content-length":
                try:
                    length = int(str(headers[key]))
                except ValueError:
                    length = None
                break
    expected = track.get("bytes", 0)
    if length and expected and abs(length - expected) > expected * 0.05:
        result["sizeMismatch"] = True
    return result


def check_all(manifest, offline=False):
    """并发 6 探测全部曲目；返回 (结果映射, 报告计数)。"""
    results = {}
    tracks = manifest.get("tracks", [])
    if offline:
        for track in tracks:
            results[track["id"]] = check_one(track, offline=True)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(check_one, t, False): t for t in tracks}
            for future in concurrent.futures.as_completed(futures):
                track = futures[future]
                try:
                    results[track["id"]] = future.result()
                except Exception:
                    results[track["id"]] = {
                        "id": track["id"], "alive": False, "health": "dead",
                        "cors": False, "reason": "probe-exception", "sizeMismatch": False,
                    }
        # 偶发限流 / 单点抖动复核：失败项错峰低并发重试，
        # 避免一次超时就被判成死链并写进 quarantine（曲库单调缩水的根因）。
        for retry_round in range(2):
            failed = [t for t in tracks if not results.get(t["id"], {}).get("alive")]
            if not failed:
                break
            time.sleep(0.6 * (retry_round + 1))
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = {pool.submit(check_one, t, False): t for t in failed}
                for future in concurrent.futures.as_completed(futures):
                    track = futures[future]
                    try:
                        retried = future.result()
                    except Exception:
                        continue
                    if retried.get("alive"):
                        results[track["id"]] = retried
    alive = sum(1 for r in results.values() if r.get("alive"))
    dead = len(results) - alive
    return results, {"alive": alive, "dead": dead}


# ---------------------------------------------------------------------------
# 失效隔离（不清空 tracks，仅 enabled=false + quarantine）
# ---------------------------------------------------------------------------
def apply_fail_inject(manifest, spec):
    """注入单个失效：<url>=<code>。返回被隔离的条目数。"""
    if "=" not in spec:
        return 0
    url, code = spec.rsplit("=", 1)
    count = 0
    for track in manifest.get("tracks", []):
        if track.get("url") == url:
            track["enabled"] = False
            track["health"] = "dead"
            track["cors"] = False
            quarantine = manifest.setdefault("quarantine", [])
            exists = any(q.get("url") == url for q in quarantine)
            if not exists:
                quarantine.append({
                    "id": track.get("id"), "url": url, "display": track.get("display"),
                    "reason": "injected-%s" % code, "at": utc_now_iso(),
                    "failCount": 1, "recoverable": True,
                })
            count += 1
    return count


def apply_check_results(manifest, results):
    """把探测结果写回 health/cors/enabled/quarantine（失败项保留在 tracks 中）。

    返回 (quarantined, recovered)。恢复可用时显式复位 enabled=true 并移出
    quarantine，否则一次网络抖动会让曲目永久停用、曲库随时间单调缩水。
    """
    quarantined = 0
    recovered = 0
    recovered_urls = set()
    for track in manifest.get("tracks", []):
        res = results.get(track["id"])
        if not res or res.get("reason") == "offline-skip":
            continue
        track["cors"] = bool(res.get("cors", True))
        if not res.get("alive", True):
            track["health"] = "dead"
            track["enabled"] = False
            quarantine = manifest.setdefault("quarantine", [])
            if not any(q.get("url") == track["url"] for q in quarantine):
                quarantine.append({
                    "id": track["id"], "url": track["url"], "display": track.get("display"),
                    "reason": res.get("reason", "unknown"), "at": utc_now_iso(),
                    "failCount": 1, "recoverable": True,
                })
                quarantined += 1
        else:
            track["health"] = "alive"
            if track.get("enabled") is False:
                track["enabled"] = True
                recovered += 1
                recovered_urls.add(track.get("url"))
    if recovered_urls:
        manifest["quarantine"] = [
            q for q in manifest.get("quarantine", [])
            if q.get("url") not in recovered_urls
        ]
    return quarantined, recovered


# ---------------------------------------------------------------------------
# 动态发现（仅候选，禁止直播，S-05 / D6 / AD-10）
# ---------------------------------------------------------------------------
def _title_blacklisted(title):
    text = str(title or "")
    for pattern in BLACKLIST_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _fetch_json(url, timeout=DISCOVER_TIMEOUT):
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "StillwaveManifestRefresh/1 (public anonymous GET)")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def discover(offline=False, max_new=10):
    """动态发现候选，恒为 verified=false / needsReview=true，0 条进入 tracks。

    离线模式不发起任何网络请求、不臆造 URL，返回空候选列表。
    """
    found = []
    if offline or not max_new:
        return found
    query = (
        "title:(ambient OR drone OR soundscape) AND mediatype:audio "
        "AND -collection:podcasts AND -collection:audio_bookspoetry"
    )
    search_url = (
        ARCHIVE_SEARCH + "?q=" + urllib.parse.quote(query)
        + "&fl%5B%5D=identifier&rows=50&output=json"
    )
    try:
        payload = _fetch_json(search_url)
        docs = payload.get("response", {}).get("docs", [])
    except Exception:
        return found

    for doc in docs:
        if len(found) >= max_new:
            break
        identifier = str(doc.get("identifier", ""))
        if not identifier.startswith(IDENTIFIER_PREFIXES):
            continue
        if _title_blacklisted(identifier):
            continue
        try:
            meta = _fetch_json(ARCHIVE_METADATA.format(identifier=urllib.parse.quote(identifier)))
        except Exception:
            continue
        for entry in meta.get("files", []):
            if len(found) >= max_new:
                break
            name = str(entry.get("name", ""))
            lower = name.lower()
            if not lower.endswith(ALLOWED_EXTENSIONS):
                continue
            try:
                size = int(entry.get("size", 0))
            except (TypeError, ValueError):
                size = 0
            if size and not (MIN_BYTES <= size <= MAX_BYTES):
                continue
            title = str(entry.get("title") or name)
            if _title_blacklisted(title):
                continue
            url = ARCHIVE_DOWNLOAD.format(
                identifier=urllib.parse.quote(identifier),
                filename=urllib.parse.quote(name),
            )
            found.append({
                "id": identifier, "url": url, "display": "待审定",
                "originalTitle": title, "bytes": size,
                "scene": "empty", "kind": "music",
                "license": PLACEHOLDER_LICENSE,
                "attribution": build_attribution("Internet Archive (待审定)", PLACEHOLDER_LICENSE),
                "item": "https://archive.org/details/" + urllib.parse.quote(identifier),
                "source": "Internet Archive (动态发现)",
                "verified": False, "needsReview": True,
                "enabled": False, "health": "unknown", "cors": False,
                "discoveredAt": utc_now_iso(),
            })
    return found


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        description="静澜 Stillwave 曲库刷新与健康检查（仅 Python 标准库）"
    )
    parser.add_argument("--init-from", dest="init_from", default=None,
                        help="从 00-verified-tracks.json 程序化生成权威清单")
    parser.add_argument("--offline", action="store_true", help="零联网：仅 schema 校验与 .js 同源校验")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="不写 data/ 下任何文件（报告仍输出）")
    parser.add_argument("--json-report", dest="json_report", default=None,
                        help="输出机器可读 JSON 报告到指定路径")
    parser.add_argument("--check-only", dest="check_only", action="store_true",
                        help="真实探测全部曲目并输出健康报告")
    parser.add_argument("--discover", action="store_true", help="动态发现候选（带规则过滤）")
    parser.add_argument("--max-new", dest="max_new", type=int, default=10,
                        help="动态发现候选上限（默认 10）")
    parser.add_argument("--fail-inject", dest="fail_inject", default=None,
                        help='注入单个失效，格式 "<url>=404"')
    parser.add_argument("--apply", action="store_true", help="原子回写 .json 与 .js，version 递增")
    parser.add_argument("--prune", action="store_true", help="显式移除连续失效项（默认仅隔离）")
    parser.add_argument("--promote", default=None, help="人工确认后把候选 id 升入 tracks（AD-10）")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.max_new < 0:
        sys.stderr.write("参数错误：--max-new 不能为负数\n")
        return 4

    bootstrapped = False
    manifest = None
    if args.init_from:
        source_path = args.init_from
        if not os.path.isabs(source_path):
            source_path = os.path.normpath(os.path.join(os.getcwd(), source_path))
        if not os.path.isfile(source_path):
            # 相对站点根目录再试一次，便于从任意 cwd 调用
            alt = os.path.normpath(os.path.join(ROOT, args.init_from))
            if os.path.isfile(alt):
                source_path = alt
        try:
            manifest = build_manifest(source_path)
            bootstrapped = True
        except (OSError, ValueError, KeyError) as err:
            sys.stderr.write("初始化失败：%s\n" % err)
            return 2
    else:
        manifest = read_manifest()
        if manifest is None and os.path.isfile(DEFAULT_SOURCE):
            try:
                manifest = build_manifest(DEFAULT_SOURCE)
                bootstrapped = True
            except (OSError, ValueError, KeyError):
                manifest = None

    if manifest is None:
        sys.stderr.write("找不到可用清单，请先运行 --init-from <00-verified-tracks.json> --apply\n")
        return 2

    version_before = manifest.get("version", 0)
    ok, errors = validate_manifest(manifest)
    if not ok:
        sys.stderr.write("schema 校验失败：\n  " + "\n  ".join(errors) + "\n")
        report = {
            "tool": "stillwave-refresh/1", "status": "schema-invalid",
            "errors": errors, "generatedAt": utc_now_iso(),
        }
        _emit_report(args.json_report, report)
        return 2

    report = {
        "tool": "stillwave-refresh/1",
        "status": "ok",
        "offline": bool(args.offline),
        "dryRun": bool(args.dry_run),
        "checkOnly": bool(args.check_only),
        "discover": bool(args.discover),
        "initFrom": bool(bootstrapped),
        "versionBefore": version_before,
        "versionAfter": version_before,
        "count": manifest.get("count", 0),
        "scenes": manifest.get("scenes", {}),
        "alive": manifest.get("count", 0),
        "dead": 0,
        "quarantined": 0,
        "recovered": 0,
        "probeSuspect": False,
        "promoted": 0,
        "candidates": len(manifest.get("candidates", [])),
        "candidatesAllNeedsReview": True,
        "candidatesVerifiedFalse": True,
        "candidatesInTracks": 0,
        "candidatesPromoted": 0,
        "tracksPreserved": True,
        "jsonJsInSync": js_in_sync(manifest),
        "schemaValid": True,
        "notes": [],
        "checkedAt": utc_now_iso(),
        "generatedAt": utc_now_iso(),
    }

    network_total_failure = False
    probe_suspect = False  # 源站/网络整体异常：本次绝不改写曲目状态、绝不回写 data/

    # —— 失效注入 ——
    if args.fail_inject:
        injected = apply_fail_inject(manifest, args.fail_inject)
        report["quarantined"] = injected
        report["dead"] = injected
        report["notes"].append("已注入 %d 条失效并隔离，tracks 未被清空" % injected)

    # —— 健康探测 ——
    if args.check_only or (args.apply and not args.offline and not args.fail_inject):
        results, counts = check_all(manifest, offline=args.offline)
        total = max(1, len(results))
        dead_ratio = counts["dead"] / total
        # 整批异常保护：archive.org 全站限流 / 本机断网时，30 首会被同时判死。
        # 此时若照常 --apply，等于把整份曲库写废。阈值取「全部失败或 >40% 失败」。
        if not args.offline and (counts["alive"] == 0 or dead_ratio > 0.4):
            probe_suspect = True
            network_total_failure = True
            report["probeSuspect"] = True
            report["status"] = "probe-suspect"
            report["alive"] = counts["alive"]
            report["dead"] = counts["dead"]
            report["notes"].append(
                "疑似源站/网络整体异常：%d/%d 首探测失败（阈值 40%%），"
                "本次不改写曲目状态、不回写 data/，保留现有清单"
                % (counts["dead"], total)
            )
        else:
            quarantined, recovered = apply_check_results(manifest, results)
            report["alive"] = counts["alive"] if not args.offline else manifest.get("count", 0)
            report["dead"] = counts["dead"] if not args.offline else 0
            report["quarantined"] += quarantined
            report["recovered"] = recovered
            if recovered:
                report["notes"].append("已自动恢复 %d 首可用曲目（enabled 复位、移出隔离区）" % recovered)

    # —— 动态发现（结果只进 candidates[]，永不进 tracks） ——
    if args.discover:
        found = discover(offline=args.offline, max_new=args.max_new)
        existing = {c.get("url") for c in manifest.get("candidates", [])}
        added = 0
        for candidate in found:
            if candidate["url"] in existing:
                continue
            manifest.setdefault("candidates", []).append(candidate)
            existing.add(candidate["url"])
            added += 1
        report["candidates"] = len(manifest.get("candidates", []))
        report["candidatesAdded"] = added
        report["candidatesAllNeedsReview"] = all(
            c.get("needsReview") is True for c in manifest.get("candidates", [])
        )
        report["candidatesVerifiedFalse"] = all(
            c.get("verified") is False for c in manifest.get("candidates", [])
        )
        report["candidatesInTracks"] = sum(
            1 for t in manifest.get("tracks", []) if t.get("needsReview") is True
        )
        report["candidatesPromoted"] = 0
        if args.offline:
            report["notes"].append("离线发现不联网、不臆造 URL，候选为空且不进入 tracks")

    # —— 人工升格（唯一能让 candidate 进入 tracks 的入口） ——
    if args.promote:
        promote_id = args.promote
        remaining = []
        promoted = 0
        for candidate in manifest.get("candidates", []):
            if candidate.get("id") == promote_id and args.apply:
                promoted_track = dict(candidate)
                promoted_track["needsReview"] = False
                promoted_track["verified"] = True
                promoted_track["enabled"] = True
                promoted_track["health"] = "alive"
                promoted_track["cors"] = True
                promoted_track["candidates"] = [candidate["url"]]
                manifest["tracks"].append(promoted_track)
                promoted += 1
            else:
                remaining.append(candidate)
        manifest["candidates"] = remaining
        report["promoted"] = promoted
        report["candidatesPromoted"] = promoted
        manifest["count"] = len(manifest["tracks"])

    # —— 显式清理（默认关闭，保证「更新失败不清空」） ——
    if args.prune and args.apply:
        before = len(manifest["tracks"])
        manifest["tracks"] = [
            t for t in manifest["tracks"] if not (t.get("health") == "dead" and not t.get("enabled"))
        ]
        manifest["count"] = len(manifest["tracks"])
        report["pruned"] = before - len(manifest["tracks"])

    # 重新校验（候选字段变化后仍必须满足 tracks 契约）
    ok2, errors2 = validate_manifest(manifest)
    report["schemaValid"] = ok2
    if not ok2:
        report["status"] = "schema-invalid"
        report["errors"] = errors2
        _emit_report(args.json_report, report)
        return 2

    # —— 写回 ——
    if args.apply and probe_suspect:
        # 探测异常保护优先于一切写操作：磁盘上的 .json/.js 保持原样与同源。
        report["notes"].append("探测异常保护生效：--apply 已跳过，data/ 未被写入")
        report["versionAfter"] = version_before
        report["count"] = manifest.get("count", 0)
        _emit_report(args.json_report, report)
        return 3
    if args.apply:
        if not bootstrapped:
            manifest["version"] = version_before + 1
        manifest["updatedAt"] = utc_now_iso()
        manifest["count"] = len(manifest["tracks"])
        scenes = {}
        for scene in EXPECTED_COUNTS:
            scenes[scene] = sum(1 for t in manifest["tracks"] if t.get("scene") == scene)
        manifest["scenes"] = scenes
        try:
            write_result = write_both(manifest)
            report["written"] = write_result
            report["jsonJsInSync"] = True
            report["notes"].append("已原子双写 .json 与 .js（同源）")
        except OSError as err:
            report["status"] = "write-failed"
            report["notes"].append("写入失败：%s（保留上一版）" % err)
    elif bootstrapped and not args.dry_run:
        # --init-from 不带 --apply 时仍允许生成初始文件，保证工具可用
        try:
            write_result = write_both(manifest)
            report["written"] = write_result
            report["jsonJsInSync"] = True
        except OSError as err:
            report["notes"].append("写入失败：%s" % err)
    else:
        report["notes"].append("dry-run：未写任何 data/ 文件")
        report["jsonJsInSync"] = js_in_sync(manifest)

    report["versionAfter"] = manifest.get("version", version_before)
    report["count"] = manifest.get("count", 0)
    report["tracksPreserved"] = len(manifest.get("tracks", [])) == 30

    _emit_report(args.json_report, report)

    if network_total_failure:
        return 3
    return 0


def _emit_report(path, report):
    """输出报告到 stdout 与可选文件；写报告失败不影响退出码。"""
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if path:
        try:
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)
            atomic_write(os.path.abspath(path), text + "\n")
        except OSError:
            pass
    sys.stdout.write(text + "\n")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # 任何异常都不外抛为堆栈，转为可读错误（A6 语义）
        sys.stderr.write("工具异常（已保留原文件）：%s\n" % exc)
        sys.exit(3)

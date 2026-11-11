# -*- coding: utf-8 -*-
"""静澜 Stillwave · QA 测试公共模块。

提供统一的结果收集器（用例编号 / 断言 / 通过失败输出 / JSON 落盘），
供 test_static_contracts.py / test_refresh_script.py / test_browser.py 共用。
仅依赖 Python 标准库。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# 路径常量（全部基于本文件位置推导，不依赖调用方 cwd）
# ---------------------------------------------------------------------------
QA_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(QA_DIR)
# 兼容两种布局：
#   1) 原始工作区：站点位于与 qa/ 平级的 meditation/ 子目录；
#   2) GitHub 仓库：站点文件直接位于仓库根（Pages 从根发布）。
# 有 meditation/ 时优先用它，否则把仓库根本身当作站点根。
_SITE_CANDIDATE = os.path.join(ROOT, "meditation")
SITE = _SITE_CANDIDATE if os.path.isdir(_SITE_CANDIDATE) else ROOT
DOCS = os.path.join(ROOT, "docs")
RESULTS_DIR = os.path.join(QA_DIR, "results")
SHOTS_DIR = os.path.join(QA_DIR, "screenshots")

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
UNVERIFIED = "UNVERIFIED"
PROVISIONAL = "PROVISIONAL"  # 预检观察：代码冻结前不下最终结论

_MARK = {
    PASS: "[PASS]",
    FAIL: "[FAIL]",
    SKIP: "[SKIP]",
    UNVERIFIED: "[UNVER]",
    PROVISIONAL: "[PROV]",
}


def ensure_dirs() -> None:
    """确保结果与截图目录存在。"""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(SHOTS_DIR, exist_ok=True)


@dataclass
class Case:
    """一条可执行断言。"""

    id: str
    name: str
    requirement: str          # 对应 P0-xx / Axx / S-xx / AD-xx
    status: str
    expected: str = ""
    actual: str = ""
    detail: str = ""
    duration_ms: int = 0
    phase: str = "full"       # preflight | full
    environment: str = ""     # 浏览器 / 环境标识


@dataclass
class Suite:
    """一个测试脚本的结果集合。"""

    name: str
    phase: str = "full"
    cases: List[Case] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)

    # -- 核心登记 ---------------------------------------------------------
    def add(self, case: Case) -> Case:
        case.phase = self.phase
        self.cases.append(case)
        mark = _MARK.get(case.status, "[????]")
        line = "%s %-6s %s" % (mark, case.id, case.name)
        if case.environment:
            line += "  <%s>" % case.environment
        if case.status in (FAIL, PROVISIONAL, UNVERIFIED):
            line += "\n        期望: %s\n        实际: %s" % (case.expected, case.actual)
        if case.detail and case.status in (FAIL, PROVISIONAL):
            line += "\n        说明: %s" % case.detail[:400]
        print(line, flush=True)
        return case

    def check(
        self,
        cid: str,
        name: str,
        requirement: str,
        ok: bool,
        expected: str = "",
        actual: str = "",
        detail: str = "",
        environment: str = "",
        provisional: bool = False,
    ) -> bool:
        """登记一条布尔断言。provisional=True 时失败不计入最终结论。"""
        if ok:
            status = PASS
        elif provisional:
            status = PROVISIONAL
        else:
            status = FAIL
        self.add(
            Case(
                id=cid,
                name=name,
                requirement=requirement,
                status=status,
                expected=expected,
                actual=actual,
                detail=detail,
                environment=environment,
            )
        )
        return bool(ok)

    def skip(self, cid: str, name: str, requirement: str, reason: str,
             environment: str = "") -> None:
        """环境/前置条件不满足时显式标注 SKIP（不计通过、不伪造）。"""
        self.add(Case(cid, name, requirement, SKIP, expected="可执行",
                      actual="跳过", detail=reason, environment=environment))

    def unverified(self, cid: str, name: str, requirement: str, reason: str,
                   environment: str = "") -> None:
        """无法实际执行的断言一律标注「未验证」。"""
        self.add(Case(cid, name, requirement, UNVERIFIED, expected="可验证",
                      actual="未验证", detail=reason, environment=environment))

    def run_case(
        self,
        cid: str,
        name: str,
        requirement: str,
        fn: Callable[[], Any],
        expected: str = "",
        detail: str = "",
        environment: str = "",
        provisional: bool = False,
    ) -> Any:
        """执行 fn：返回 (bool, actual) 或 bool；异常统一转成 FAIL，不中断套件。"""
        t0 = time.time()
        try:
            result = fn()
            if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool):
                ok, actual = result
            else:
                ok, actual = bool(result), str(result)
            self.check(cid, name, requirement, ok, expected=expected,
                       actual="" if ok else actual, detail=detail,
                       environment=environment, provisional=provisional)
            self.cases[-1].duration_ms = int((time.time() - t0) * 1000)
            return result
        except Exception as exc:  # noqa: BLE001 - 测试框架需兜住一切异常
            self.check(cid, name, requirement, False, expected=expected,
                       actual="%s: %s" % (type(exc).__name__, exc),
                       detail=detail, environment=environment,
                       provisional=provisional)
            self.cases[-1].duration_ms = int((time.time() - t0) * 1000)
            return None

    # -- 汇总 -------------------------------------------------------------
    def counts(self) -> Dict[str, int]:
        out = {PASS: 0, FAIL: 0, SKIP: 0, UNVERIFIED: 0, PROVISIONAL: 0}
        for c in self.cases:
            out[c.status] = out.get(c.status, 0) + 1
        return out

    def summary(self) -> Dict[str, Any]:
        c = self.counts()
        formal_total = c[PASS] + c[FAIL]
        return {
            "suite": self.name,
            "phase": self.phase,
            "total": len(self.cases),
            "passed": c[PASS],
            "failed": c[FAIL],
            "skipped": c[SKIP],
            "unverified": c[UNVERIFIED],
            "provisional": c[PROVISIONAL],
            "formalTotal": formal_total,
            "formalPassRate": (round(c[PASS] / formal_total * 100, 1)
                               if formal_total else 0.0),
            "cases": [asdict(x) for x in self.cases],
            "artifacts": self.artifacts,
            "durationSec": round(time.time() - self.started_at, 2),
        }

    def print_report(self) -> None:
        c = self.counts()
        print("\n" + "-" * 72)
        print("套件 %s  阶段=%s" % (self.name, self.phase))
        print("  用例 %d | 通过 %d | 失败 %d | 预检观察 %d | 跳过 %d | 未验证 %d"
              % (len(self.cases), c[PASS], c[FAIL], c[PROVISIONAL],
                 c[SKIP], c[UNVERIFIED]))
        print("-" * 72, flush=True)

    def save(self, filename: Optional[str] = None) -> str:
        ensure_dirs()
        path = os.path.join(RESULTS_DIR, filename or (self.name + ".json"))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.summary(), fh, ensure_ascii=False, indent=2)
        return path


def load_manifest(path: Optional[str] = None) -> Dict[str, Any]:
    """读取权威清单 JSON。"""
    p = path or os.path.join(SITE, "data", "audio-sources.json")
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_verified_pool() -> Dict[str, Any]:
    """读取主理人实测曲库（QA 比对基线）。"""
    with open(os.path.join(DOCS, "00-verified-tracks.json"), "r",
              encoding="utf-8") as fh:
        return json.load(fh)


def read_text(rel: str) -> str:
    """读取站点内相对路径的文本文件。"""
    with open(os.path.join(SITE, rel), "r", encoding="utf-8") as fh:
        return fh.read()


def merge_summaries(paths: List[str], out_path: str) -> Dict[str, Any]:
    """合并多个套件 JSON，生成总览。"""
    suites = []
    for p in paths:
        with open(p, "r", encoding="utf-8") as fh:
            suites.append(json.load(fh))
    total = sum(s["total"] for s in suites)
    passed = sum(s["passed"] for s in suites)
    failed = sum(s["failed"] for s in suites)
    provisional = sum(s["provisional"] for s in suites)
    skipped = sum(s["skipped"] for s in suites)
    unverified = sum(s["unverified"] for s in suites)
    out = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "suites": suites,
        "total": total,
        "passed": passed,
        "failed": failed,
        "provisional": provisional,
        "skipped": skipped,
        "unverified": unverified,
        "formalTotal": passed + failed,
        "formalPassRate": round(passed / (passed + failed) * 100, 1)
        if (passed + failed) else 0.0,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    return out

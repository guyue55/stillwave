# -*- coding: utf-8 -*-
"""静澜 Stillwave · QA 报告素材生成器（工具，不产出最终报告）。

从 qa/results/summary.json 与各套件 JSON 中提取最终报告所需的全部结构化数据：
  1. 逐条 P0-01~P0-18 / A1~A14 的覆盖矩阵与判定；
  2. 三类故障注入实测数据（含 lastDegradeDurationMs）；
  3. 跨浏览器 / 环境能力表；
  4. 控制台与网络审查、性能数字、脚本实跑输出、音频逐条探测；
  5. 未验证 / 遗留清单。

用法：
  python3.9 qa/gen_report_data.py                 # 读默认 qa/results/summary.json
  python3.9 qa/gen_report_data.py --out <path>   # 写 JSON 素材
  python3.9 qa/gen_report_data.py --markdown     # 打印 Markdown 表格（供报告粘贴）

纪律：本脚本只做数据提取与呈现，不修改 meditation/ 源码，
      不预先判定验收结论；最终结论由 QA 在 CODE_FROZEN 后出具。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RESULTS_DIR  # noqa: E402

P0_TITLES = {
    "P0-01": "四场景切换 + 平滑过渡",
    "P0-02": "播放 / 暂停",
    "P0-03": "主音量滑块 + 分轨相乘",
    "P0-04": "≤3 轨混音与上限提示",
    "P0-05": "定时器 15/30/45/60/90 + 渐弱 30/60/120s + 取消恢复",
    "P0-06": "三类故障注入 ≤3s 自动回退且不改 playing",
    "P0-07": "纯静态零依赖、file:// 与 https 子路径双环境",
    "P0-08": "320/768/1440 三档响应式 + 亮度三档",
    "P0-09": "无登录、无追踪、无第三方统计/广告/凭据",
    "P0-10": "真实在线音乐 + 许可署名",
    "P0-11": "首次手势才出声",
    "P0-12": "localStorage 持久化与内存降级",
    "P0-13": "手动刷新曲库三态",
    "P0-14": "失效可感知但不打断",
    "P0-15": "30 首逐条可播与四场景覆盖",
    "P0-16": "许可署名展示",
    "P0-17": "失效自动回退不打断体验（端到端）",
    "P0-18": "中文展示名与标题净化",
}
A_TITLES = {
    "A1": "P0 全 18 条逐条通过 + P1-01/03/07",
    "A2": "真实浏览器 Chrome/Firefox/Safari 各一完整路径",
    "A3": "故障注入 404/超时/断网均自动回退且播放不中断",
    "A4": "file:// 与 https 子路径双环境 P0 全通过",
    "A5": "320px 真机视口无溢出、控件 ≥44px",
    "A6": "控制台零未捕获异常/零 404/零混合内容",
    "A7": "首屏 <300KB、DCL <1.5s、60 分钟无内存泄漏",
    "A8": "键盘走通 / aria / prefers-reduced-motion",
    "A9": "隐私网络审查：无登录/统计/广告/API key",
    "A10": "许可与署名四要素、链接可访问",
    "A11": "默认路径确实播放 archive.org MP3",
    "A12": "零构建部署",
    "A13": "曲库 30 首且 byKind music21/nature9，逐条可播",
    "A14": "四处曲目名 100% display，originalTitle 零泄露",
}


def load_summary(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def all_cases(summary: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    out: List[Tuple[str, Dict[str, Any]]] = []
    for suite_name, suite in summary.get("suites", {}).items():
        for c in suite.get("cases", []):
            out.append((suite_name, c))
    return out


def matrix(summary: Dict[str, Any]) -> Dict[str, Any]:
    """逐条 P0 / A 的关联用例与判定（判定取最严：FAIL > UNVERIFIED > PASS）。"""
    cases = all_cases(summary)

    def verdict(statuses: List[str]) -> str:
        if "FAIL" in statuses:
            return "FAIL"
        if "UNVERIFIED" in statuses:
            return "UNVERIFIED"
        if not statuses:
            return "未覆盖"
        return "PASS"

    blocks: Dict[str, Any] = {}
    for label, titles in (("P0", P0_TITLES), ("A", A_TITLES)):
        rows = []
        for tag, title in titles.items():
            # A1 这类短标签需精确匹配，避免 A1 命中 A10~A14
            pat = re.compile(r"(?<![0-9A-Za-z])" + re.escape(tag) + r"(?![0-9])")
            hit = [(sk, c["id"], c["status"])
                   for sk, c in cases
                   if pat.search(str(c.get("requirement", "")))]
            derived = ""
            if label == "A" and tag == "A1":
                # A1 =「P0 全 18 条逐条通过」的汇总判据，语义上继承所有 P0 用例，
                # 否则仅显示显式标注 A1 的 BR-32 会低估覆盖度。
                p0_hit = [(sk, c["id"], c["status"])
                          for sk, c in cases
                          if "P0-" in str(c.get("requirement", ""))]
                seen = {x[1] for x in hit}
                hit += [x for x in p0_hit if x[1] not in seen]
                derived = "汇总型判据：判定继承全部 P0-01~P0-18 用例"
            rows.append({
                "id": tag, "title": title, "caseCount": len(hit),
                "cases": [x[1] for x in hit],
                "statusCount": dict(collections.Counter(x[2] for x in hit)),
                "verdict": verdict([x[2] for x in hit]),
                "derived": derived,
            })
        blocks[label] = rows
    return blocks


def fault_data(summary: Dict[str, Any]) -> Dict[str, Any]:
    """从 browser 套件 artifacts 提取三类故障注入与音频探测数据。"""
    b = summary.get("suites", {}).get("browser", {})
    art = b.get("artifacts", {}) or {}
    out: Dict[str, Any] = {}
    for kind in ("404", "timeout", "network"):
        if "fault_" + kind in art:
            out[kind] = art["fault_" + kind]
    out["audioLoadProbe"] = art.get("audioLoadProbe")
    out["audioLoadFirstPass"] = art.get("audioLoadFirstPass")
    out["audioLoadRetries"] = art.get("audioLoadRetries")
    out["audioPlayProbe"] = art.get("audioPlayProbe")
    out["audioPlayRetries"] = art.get("audioPlayRetries")
    out["faviconObservation"] = art.get("faviconObservation")
    out["favicon404Present"] = art.get("favicon404Present")
    out["fault404InjectedUrl"] = art.get("fault404InjectedUrl")
    return out


def non_pass(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for sk, c in all_cases(summary):
        if c.get("status") != "PASS":
            rows.append({
                "suite": sk, "id": c["id"], "name": c.get("name"),
                "requirement": c.get("requirement"),
                "status": c.get("status"),
                "expected": c.get("expected"),
                "actual": c.get("actual"),
                "environment": c.get("environment"),
            })
    return rows


def build(path: str) -> Dict[str, Any]:
    s = load_summary(path)
    return {
        "generatedAt": s.get("generatedAt"),
        "phase": s.get("phase"),
        "round": s.get("round"),
        "totals": {
            "total": s.get("total"), "passed": s.get("passed"),
            "failed": s.get("failed"), "provisional": s.get("provisional"),
            "skipped": s.get("skipped"), "unverified": s.get("unverified"),
            "formalPassRate": s.get("formalPassRate"), "ROUTE": s.get("ROUTE"),
        },
        "suites": {k: {kk: v.get(kk) for kk in
                       ("total", "passed", "failed", "provisional",
                        "skipped", "unverified", "formalPassRate")}
                   for k, v in s.get("suites", {}).items()},
        "matrix": matrix(s),
        "faults": fault_data(s),
        "nonPass": non_pass(s),
        "note": s.get("note"),
    }


def markdown(data: Dict[str, Any]) -> str:
    L: List[str] = []
    t = data["totals"]
    L.append("## 总览")
    L.append("")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append("| 阶段 / 轮次 | %s / Round %s |" % (data["phase"], data["round"]))
    L.append("| 用例总数 | %s |" % t["total"])
    L.append("| 通过 / 失败 / 未验证 | %s / %s / %s |"
             % (t["passed"], t["failed"], t["unverified"]))
    L.append("| 正式断言通过率 | %s%% |" % t["formalPassRate"])
    L.append("| ROUTE | %s |" % t["ROUTE"])
    L.append("")
    for label, name in (("P0", "P0-01~P0-18 逐条"), ("A", "A1~A14 逐条")):
        L.append("## %s" % name)
        L.append("")
        L.append("| 编号 | 判据摘要 | 用例数 | 关联用例 | 判定 |")
        L.append("|---|---|---:|---|---|")
        for r in data["matrix"][label]:
            L.append("| %s | %s | %d | %s | %s |"
                     % (r["id"], r["title"], r["caseCount"],
                        ", ".join(r["cases"]) or "—", r["verdict"]))
        L.append("")
    L.append("## 非 PASS 明细")
    L.append("")
    L.append("| 套件 | 用例 | 状态 | 需求 | 实际 | 环境 |")
    L.append("|---|---|---|---|---|---|")
    for r in data["nonPass"]:
        L.append("| %s | %s | %s | %s | %s | %s |"
                 % (r["suite"], r["id"], r["status"],
                    str(r["requirement"])[:28],
                    str(r["actual"]).replace("|", "\\|")[:90],
                    str(r["environment"])[:24]))
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", default=os.path.join(RESULTS_DIR, "summary.json"))
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR, "report_data.json"))
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    data = build(args.summary)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    if args.markdown:
        print(markdown(data))
    else:
        print("报告素材已写入:", args.out)
        print("阶段=%s 轮次=%s 用例=%s 通过=%s 失败=%s 未验证=%s ROUTE=%s"
              % (data["phase"], data["round"], data["totals"]["total"],
                 data["totals"]["passed"], data["totals"]["failed"],
                 data["totals"]["unverified"], data["totals"]["ROUTE"]))
        for label in ("P0", "A"):
            miss = [r["id"] for r in data["matrix"][label] if r["verdict"] == "未覆盖"]
            print("  %s 覆盖: %d/%d，未覆盖=%s"
                  % (label, sum(1 for r in data["matrix"][label]
                                if r["verdict"] != "未覆盖"),
                     len(data["matrix"][label]), miss or "无"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

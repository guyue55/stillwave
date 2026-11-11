# 自动化测试套件

本目录存放静澜 Stillwave 的自动化测试，与 `meditation/` 站点源码解耦，不参与 GitHub Pages 运行。

## 环境

- Python 3.9+（**仅标准库**，无 pip 依赖）
- Playwright 1.60（`pip install playwright` + `playwright install chrome`，或直接复用本机 Google Chrome）
- Google Chrome：本机实测 `p.chromium.launch(channel="chrome")` 可用

`run_all.sh` 会优先使用 Homebrew 的 `python3.9`，否则回退到 `python3`。

## 运行

```bash
cd qa
./run_all.sh --phase full --round 2                    # 全量
./run_all.sh --phase full --round 2 --only browser     # 只跑浏览器套件
./run_all.sh --phase full --round 2 --offline-only     # 刷新脚本不联网
```

也可以单独调用（便于快速回归）：

```bash
python3 -c "import test_static_contracts as t; print(t.run('full').summary())"
python3 -c "import test_refresh_script as t; print(t.run('full').summary())"
```

结果写入 `qa/results/`，截图写入 `qa/screenshots/`（两者均已 gitignore）。

## 套件

| 文件 | 套件 | 用例 | 内容 |
|---|---|---|---|
| `env_probe.py` | env_probe | 11 | 浏览器/环境能力探测（跨浏览器启动能力多为 UNVERIFIED） |
| `test_static_contracts.py` | static_contracts | 24 | 文件树、相对路径、无 ESM/框架/凭据、清单同源与字段隔离、常量与响应式契约 |
| `test_refresh_script.py` | refresh_script | 7 | 刷新脚本离线/联网/失效注入/发现/污染检查 |
| `test_browser.py` | browser | 43 | 真实 Chrome 端到端：30 首逐条可播、四场景、在线升级、信息面板、降级自愈、性能、控制台零错误、`file://` 与 Pages 子路径 |
| `test_degrade_repeats.py` | degrade_repeats | 6 | 3 类故障 × 2 组配置 × 5 次降级耗时复现（≤3000ms） |
| `longrun_stability.py` | — | — | CDP 长时采样（JS heap / DOM 节点 / listeners / rAF） |
| `gen_report_data.py` | — | — | 生成报告素材 |

`run_all.py` 负责调度、合并 `summary.json` 并给出 `ROUTE`（`NoOne` / `Engineer`）。

## 路径兼容

`common.py` 自动识别两种布局，无需手工配置：

- 开发工作区：站点位于与 `qa/` 平级的 `meditation/` 目录 → `SITE = ROOT/meditation`；
- 本 GitHub 仓库：站点文件直接位于仓库根 → `SITE = ROOT`。

`test_static_contracts.py` 遍历文件树时会跳过 `.git/`、`qa/`、`docs/` 等仓库级目录，保证 ST-01「源文件树」口径在两种布局下一致。

## 纪律

- 测试**不得修改站点源码或 `data/`**：`RS-07` 会比对前后 SHA256，确保刷新相关用例全部为 dry-run。
- 跨浏览器（Firefox / Safari / WebKit）与 60 分钟长时判据，本环境无法执行时一律标 `UNVERIFIED`，**不得把 Chrome 结果外推、不得伪造通过**。
- 环境性失败（如极高 CPU 负载导致首屏超时）要与源码缺陷区分：需在低负载下独立复跑确认，并在报告中说明。

完整结果与限制披露见 [`docs/04-qa-report.md`](../docs/04-qa-report.md)。

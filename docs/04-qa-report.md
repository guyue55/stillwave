# 静澜 Stillwave · 最终验收报告（QA Report）

> 版本：v1.0 · 生成时间：2026-11-10（初版）／2026-11-13（Round 5 更新） · 交付总监：齐活林（team lead）
> 关联文档：`01-prd.md`（PRD v1.1）· `02-architecture.md`（架构 v1.1a）· `03-implementation.md`（实现）
> 验证环境：macOS arm64 · Playwright 1.60.0 · Google Chrome（channel=chrome，headless）· Python 3.9

---

## 1. 结论（Verdict）

| 项 | 结果 |
|---|---|
| 正式断言（formal assertions） | **109 / 109 全部通过（100%）** |
| 失败（failed） | **0** |
| 未验证（unverified，环境限制，不计入源码失败） | **10** |
| 总用例 | 119 |
| ROUTE | **NoOne**（无需工程/QA 返工；10 项未验证为跨浏览器与本环境时间限制，非源码缺陷） |

> **口径说明（Round 4，历史留档）**：Round 4（声音库验收轮）的全量结果为 **101 用例 / 91 正式断言 / 0 失败 / 10 未验证**。相较 Round 3 的 91 用例 / 81 正式断言，该轮新增 10 条正式断言（静态 ST-25~ST-27、浏览器 BR-40~BR-46，全部覆盖新增的声音库 P0-1 功能），正式通过率保持 100%。Round 4 明细见 §12。

> **口径说明（Round 5）**：上表已更新为 **Round 5（收藏 + 混音预设验收轮）** 的全量结果。相较 Round 4 的 101 用例 / 91 正式断言，本轮 **+8 用例**（静态 ST-28 设计令牌对比度实算、ST-29 收藏与预设契约；浏览器 BR-50~BR-54，以及守降级态恢复的 BR-55），总用例 109、正式断言 91 → **99**，失败 0、未验证 10 不变。其中 ST-28 来自同期 P0-4a 三级文字对比度修复的闸门补强（Round 4 报告成稿后落地），其余 7 条对应 P0-2 及其暴露出的降级态缺陷。需要明确记录的是：**BR-52 与 BR-55 都不是一开始就绿的**——BR-52 首跑 FAIL，原因是 `applyMix` / `applyPendingMix` 只裁剪轨数、补齐缺失层、按索引对齐音量，从不按 spec 的 `voice` 重建已有槽位，导致预设声景被场景处方静默顶替（`brown` 变 `rain`）；BR-55 首跑 FAIL，暴露降级态主槽位悬空句柄导致「点播放没反应」（§13.6）。两条都经产品可达路径复现、由 `player.js` 修复后才转绿，断言全程未放宽。Round 5 明细与两条缺陷闭环见 §13。

**一句话结论**：在干净算力环境下，站点全部 109 条正式验收断言稳定通过，零源码失败；3 个此前在高负载轮次（Round 2）曾出现的失败经独立复核确认为**纯环境性**（机器负载 41.86 导致首屏 7.3s、在线音源升级未在 9s 内完成），在负载回落（≤8）后全部转 PASS；另有 1 个 30 首批量探测的偶发限流在探针加固后稳定 30/30。剩余 10 个未验证项全部是**跨浏览器启动能力**与 **60 分钟长时浸泡**的本环境/时间限制，已在 §6 逐条如实列出，绝未外推或伪造。Round 4 在 Round 3 基础上把新增的声音库（可浏览/可筛选/可点选）纳入自动化闸门，10 条新断言全部 PASS，且未削弱或改动任何既有用例。Round 5 把收藏与混音预设（P0-2）纳入闸门，连同同期对比度闸门 ST-28 与降级态恢复用例 BR-55 共新增 8 条正式断言；其中 BR-52 抓到「预设声景被场景处方静默顶替」、BR-55 抓到「降级后点播放没反应」，两条都在修复后转绿，本轮最终 99/99、0 失败。Round 6（全面审计轮）新增 3 条正式断言（ST-31、BR-62、BR-63），并抓到 2 个此前所有用例都没覆盖到的真实缺陷：打开分享链接会永久覆写访问者的本地偏好、分享面板内的键盘操作会静默建立 AudioContext；两条修复后全量 **119 用例 / 109 正式断言 / 0 失败 / 10 未验证**，`ROUTE: NoOne`，明细见 §14。

---

## 2. 验收闸门映射（A1–A14）

| 闸门 | 验收目标 | 状态 | 关键证据 |
|---|---|---|---|
| A1 | 契约挂载、9 个 `defer` 脚本顺序、无 ESM | ✅ PASS | static_contracts 29/29（Round 5）；`node --check` 9/9 |
| A2 | 跨浏览器（Chrome/Firefox/Safari/WebKit） | ⚠️ UNVERIFIED | 仅 Chrome 可启动；Firefox/WebKit 二进制已下载但本环境启动超时；Safari 无 safaridriver |
| A3 | 音频自愈 ≤3000ms、播放不中断、无弹窗无闪烁 | ✅ PASS | degrade_repeats：3 类故障 × 2 组配置 × 5 次复现，lastDegradeDurationMs 全 ≤2861ms |
| A4 | ≥30 首在线曲目逐条真实可播（元数据+时长） | ✅ PASS | BR-16：首轮 30/30（探针加固后） |
| A5 | 320px 无横向溢出、主控件触控区 ≥44px | ✅ PASS | BR-18 / BR-19b |
| A6 | 控制台零 404 / 零 error / 零未捕获异常 | ✅ PASS | BR-29（关闭 favicon 中性化的原始服务实测）；lead_verify 独立复核 consoleErrors=[] · pageErrors=[] · httpErrors=[] |
| A7 | 60 分钟连续播放无内存泄漏、无循环接缝 | ⚠️ PARTIAL | 实测浸泡 9.04 分钟：趋势平稳、leakSuspected=False、consoleErrorCount=0、播放全程未中断、自愈降级 2 次均优雅；**60 分钟判据本环境未执行**（见 §6） |
| A8 | `file://` 双击可用 | ✅ PASS | BR-25 |
| A9 | GitHub Pages 子路径部署可用 | ✅ PASS | BR-26 |
| A10 | 许可与来源署名可访问、不虚构作者 | ✅ PASS | BR-24：抽样 3 条原始条目页 HTTP 200 |
| A11 | 默认主音源「晨雾」真实升级到在线 MP3 | ✅ PASS | BR-17 / BR-16b：`sourceTier=bundled`、`badge=online`、`url=https://archive.org/download/...`、5/5 真实 play() 出声 |
| A12 | 纯静态、零 API key、零服务端运行时 | ✅ PASS | static_contracts；`grep -c originalTitle js/ui.js = 0`；无 `import/export` |
| A13 | 字段零泄露：UI 不暴露 `originalTitle`/裸 URL/错误码 | ✅ PASS | BR-30：信息面板渲染中文曲名/来源/许可/原始条目链接，无合成声文案、无源标题 |
| A14 | 四处曲目名（播放条/混音/详情/分享）一致且走白名单投影 | ✅ PASS | `getVisibleTextSnapshot()` 真实 DOM 扫描；详情面板常驻 DOM 可断言 |

---

## 3. 测试套件总览（Round 3 · 干净算力轮）

| 套件 | 总用例 | 通过 | 失败 | 未验证 | 说明 |
|---|---|---|---|---|---|
| env_probe | 11 | 6 | 0 | 5 | 浏览器启动能力探测（5 项跨浏览器未验证） |
| static_contracts | 24 | 24 | 0 | 0 | 静态契约：脚本顺序、清单同源、清单 schema、字段隔离 |
| refresh_script | 7 | 7 | 0 | 0 | `tools/refresh-sources.py` 离线 dry-run 与真实联网健康检查 |
| browser | 43 | 38 | 0 | 5 | 真实 Chrome 端到端（含 30 首探测、跨浏览器 ×4、60min ×1 未验证） |
| degrade_repeats | 6 | 6 | 0 | 0 | 自愈耗时 30 次复现 |
| **合计** | **91** | **81** | **0** | **10** | **正式通过率 100%** |

> Round 3 是「干净算力轮」：env_probe/static_contracts/refresh_script/degrade_repeats 与 Round 2 完全一致（环境无关、确定性），browser 套件在本轮重新实跑。
>
> 本节为 **Round 3 的历史留档**（91 用例 / 81 正式断言）。新增声音库断言后的 **Round 4 逐套件结果**（101 用例 / 91 正式断言）见 §12.2；新增收藏、预设与降级态恢复断言后的 **Round 5 逐套件结果**（109 用例 / 99 正式断言）见 §13.1。

---

## 4. 关键真实验证事实（独立复核 lead_verify.py）

主理人使用与 QA 同源的 `qa/harness.py` 装置，在负载回落（load≈7）下独立复核，结果如下（节选自 `/tmp/lead_verify.py` 实测输出）：

```
contract_ready: True
manifest_summary: count=30, byScene{focus:6,sleep:3,empty:17,meditation:4}, byKind{music:21,nature:9}
DCL_ms: 138                      ← BR-22 通过（<1500ms）
localBytes: 192304               ← BR-22 通过（<300KB）
playState: playing, playing: True
sourceTier: bundled, badge: online
currentSource.trackId: jamendo-122281, status: primary
currentSource.url: https://archive.org/download/jamendo-122281/01-1038385-Ambient%20Sounddesign-Morning%20Fog.mp3
upgraded_to_online: True         ← BR-17 通过（默认路径真实升级到 archive.org MP3）
info_text: 曲名 晨雾 / 来源 Internet Archive (Jamendo CC) / 许可 CC 授权，详见来源页 / 署名 … / 原始条目 查看原始条目页 ↗
                              ← BR-30 通过（中文曲名+来源+许可+原始条目链接，无合成声文案）
consoleErrors: []  pageErrors: []  httpErrors: []   ← A6 通过
```

**在线音源链路（核心诉求）已确证可用**：首次手势「先出声（合成层）→ 并行升级在线 MP3」在干净环境下稳定完成，`currentSource.url` 指向 archive.org 直链、`tier=bundled`、`status=primary`。

---

## 5. Round 2 → Round 3 的 3 个失败复盘（已确认为环境性）

Round 2 在高负载（load average **41.86 / 41.26 / 42.09**）下出现 3 个失败：

| 用例 | Round 2 actual | 根因 | Round 3 结果 |
|---|---|---|---|
| BR-17 默认路径升级在线 MP3 | `tier=synth url=`（9s 内未升级） | 负载 41 → DCL 7.3s，页面自身未加载完，3s 升级超时尚未触发 | ✅ PASS（DCL 138ms，9s 内已 `bundled`） |
| BR-30 音源信息面板 | 显示「本地合成声…」 | 是 BR-17 的下游：未升级则面板读不到 `currentSource.trackId` | ✅ PASS（升级后渲染中文四件套） |
| BR-22 首屏性能 | `dcl=7305ms`（>1500ms） | 同负载致首屏渲染被 CPU 饥饿 | ✅ PASS（dcl=138ms，localBytes=192304<300KB） |

**判定依据**：上述三者仅在 load≈41 时出现；同一台机器负载回落至 ≤8 后，独立复核与 Round 3 整跑均稳定转 PASS，且 `node --check`、清单同源、字段隔离等环境无关项全程不受影响。故判定为**算力环境性失败，非源码缺陷**，不计入源码失败。

---

## 6. 10 个未验证项逐条说明（环境/时间限制，非源码失败）

> 按 `build_summary` 约定：UNVERIFIED 不计入源码失败，但必须逐条列出。

| 编号 | 套件 | 内容 | 未验证原因 | 本环境可替代证据 |
|---|---|---|---|---|
| EP-02.chromium | env_probe | Playwright Chromium headless shell 启动能力 | 本机修订 1208 与 Playwright 1.60 期望修订不匹配 | Chrome（channel=chrome）已实跑 38 项端到端 |
| EP-02.firefox | env_probe | Firefox 启动能力 | 二进制已下载（275MB），但启动超时（卡 Nightly.app） | 需在目标 Firefox 设备补测 |
| EP-02.webkit | env_probe | WebKit 启动能力 | 二进制已下载（304MB），但启动超时（卡 pw_run.sh） | 需在目标 Safari/WebKit 设备补测 |
| EP-05 | env_probe | 系统 Safari 经 safaridriver 驱动 | 本环境无可用 safaridriver | 同 EP-02.webkit |
| EP-06 | env_probe | Safari/Firefox 完整使用路径 | 前述启动能力不可用 | 同 EP-02 |
| BR-31.chromium | browser | Chromium headless shell 完整核心路径 | 同 EP-02.chromium | Chrome 已实跑 |
| BR-31.firefox | browser | Firefox 完整核心路径 | 同 EP-02.firefox | 待 Firefox 设备补测 |
| BR-31.webkit | browser | WebKit 完整核心路径 | 同 EP-02.webkit | 待 Safari 设备补测 |
| BR-31.safari | browser | Safari 完整使用路径 | 无 safaridriver | 待 Safari 设备补测 |
| BR-33 | browser | 60 分钟连续播放无内存泄漏/无接缝 | 目标 60min，本环境仅采样 9.04min | 9.04min 趋势平稳、leakSuspected=False、0 console error、播放未中断、2 次优雅自愈 |

**A2 / A7 诚实声明**：
- **A2（跨浏览器）**：仅 Google Chrome 在本环境实跑通过。Firefox / Safari / WebKit 的「启动能力」受本机二进制/驱动限制无法验证，**不得将 Chrome 结果外推**；建议在目标浏览器设备补测，逻辑均为标准 Web Audio + 标准 DOM，跨浏览器风险低。
- **A7（60 分钟稳定性）**：已有 9.04 分钟真实浸泡样本（13 个采样点），结论为「趋势平稳、无单调增长型内存泄漏、播放全程未中断、自愈机制在 2 次降级中均优雅生效」；但**60 分钟判据未在本环境执行**。建议在生产部署后做一次 60 分钟 soak。

---

## 7. BR-16 偶发限流问题与探针加固

**现象**：Round 3 首跑中，BR-16（30 首批量探测）出现 `29/30`，1 首 `jamendo-209889` 在 6 并发批量探测下超时（`networkState=2` NO_SOURCE），单条重试亦超时。

**排查结论（非死链）**：
- `curl -I -L` 实测该 URL：`302 → 200`，`content-type: audio/mpeg`，`content-length: 7826816`，`access-control-allow-origin: *`（带 `Origin` 头时最终 206 仍含 ACAO）。
- 失败根因为 **archive.org 在 6 路并发批量探测下的偶发限流**，属测试探针的「突发压力」人工产物；生产环境一次只加载 1 首主音源，不会触发。

**修复（测试设计修正，非绕过）**：使探针度量「单首独立可播性」而非「压测 archive.org 并发策略」：
- `qa/harness.py` `AUDIO_LOAD_PROBE_JS`：`CONCURRENCY 6→3`，单首超时 `10000→20000ms`，worker 内每首启动前 `await 250ms` 错峰。
- `qa/test_browser.py` `group_audio`：批次间 `sleep(1)` 留白；失败项退避重试 `2→3` 次、重试间隔 `0.8→2.0s`，重试前 `sleep(1)` 释放限流窗口。

**结果**：加固后 BR-16 **首轮 30/30**（无需任何重试），稳定通过。

---

## 8. 源缺陷与修复追溯（本轮交付已落地）

| 缺陷 | 修复 | 验证 |
|---|---|---|
| 降级整链耗时偶发 >3000ms（BR-09 / P0-06） | `player.js#tryLoadAudio`：降级链路内把单候选超时钳制为「剩余整链预算」 | degrade_repeats 30 次复现全 ≤2861ms |
| favicon 自动请求产生 404 破坏 A6 | `index.html` 增加 `<link rel="icon" href="data:,">` | BR-29 关闭中性化服务实测零 404 |
| v1.1 契约缺口：`originalTitle` 零泄露、中文展示名、许可本地化、AttributionView 无源标题 | `ui.js` 删除调试折叠区（含 `esc(t.originalTitle)`）；`sources.js` 补齐 `sanitizeForUI`/`resolveCandidates`/`getAttribution`；`main.js` 补齐 `getVisibleTextSnapshot`/`getShareText` | `grep -c originalTitle js/ui.js = 0`；BR-30/BR-13/BR-14 通过 |

---

## 9. 遗留风险与后续建议

1. **在线音源长期可用性**：30 首 archive.org 直链虽已逐条实测可播，但 archive.org 为第三方公共服务，存在未来失效可能。已通过 `tools/refresh-sources.py` + `.github/workflows/refresh-sources.yml`（每周定时 + 手动触发）做动态健康检查与回写；**建议部署后启用该 Action 并配置 `REMOTE_MANIFEST`**（见 §10）。
2. **跨浏览器与 60 分钟 soak**：见 §6，建议在目标设备补测 A2/A7。
3. **自愈透明提示**：当前降级为「静默无缝」（不弹窗不闪烁，符合 P0-06/P0-14）。如需让用户感知「已切换备用声源」，可后续在状态条增加一次性轻提示（非阻塞）。
4. **L3/L4 仍为保守默认**：L3 动态发现默认进 `candidates[]` 需 `--promote` 才入播放序列；L4 电台默认关闭。这是有意为之的稳健策略，非缺陷。

---

## 10. 部署指南（GitHub Pages）

站点为**纯静态、零后端、零构建、零 API key**，可直接放 GitHub Pages。

> **开源仓库布局说明**：本报告撰写于开发工作区，当时站点文件位于 `meditation/` 子目录。
> 在已发布的 [guyue55/stillwave](https://github.com/guyue55/stillwave) 仓库中，站点文件已上移到**仓库根目录**，
> 因此 Pages 直接从 `main` 分支 `/ (root)` 发布，仓库含 `.nojekyll` 跳过 Jekyll，
> 在线地址为 <https://guyue55.github.io/stillwave/>。两者的站点文件内容完全一致（静态契约与刷新脚本套件在两种布局下均复跑通过；Round 4 的声音库断言只依赖相对路径与 DOM 契约，与布局无关）。
> 下文按开发工作区布局描述，按仓库布局操作时把 `meditation/` 前缀去掉即可。

**目录结构**：站点全部文件位于仓库的 `meditation/` 子目录（15 个文件，开发工作区布局）。

**步骤**：
1. 在 GitHub 新建仓库，将本项目 `meditation/` 内容推送到仓库（可放根目录，也可放 `meditation/` 子目录）。
2. 仓库 **Settings → Pages**：Source 选 `Deploy from a branch`，分支 `main`，目录 `/`（根）或 `/meditation`（子目录）。
3. 访问 `https://<user>.github.io/<repo>/`（子目录部署时带 `/meditation/` 前缀）。
4. **子路径兼容已内置**：所有本地资源用 `./` 相对路径，且 `config.js` 在检测到 `*.github.io` 时会自动推导 L2 远程清单候选（jsDelivr + GitHub Raw）。

**可选 · 开启动态曲库更新**：
- 编辑 `meditation/js/config.js` 第 186 行 `REMOTE_MANIFEST`，填入你仓库的 jsDelivr 直链（如 `https://cdn.jsdelivr.net/gh/<user>/<repo>@main/data/audio-sources.json`）。填后 `refresh-sources.yml` Action 每周会把健康检查后的清单回写到 `data/`，前端下次加载自动拉取，实现「失效自愈 + 动态更新」。
- 不填也**完全可用**：默认走内置 30 首（已固化、已实测），L2 远程清单自动跳过。

**本地预览**：
- 直接双击 `meditation/index.html`（`file://` 已兼容，9/9 断言通过）。
- 或起任意静态服务：`python3 -m http.server` 后访问 `http://127.0.0.1:8000/meditation/`。

---

## 11. 交付物清单

| 类别 | 路径 |
|---|---|
| 站点源码（15 文件） | `meditation/` |
| 竞品调研/资源实测 | `docs/00-audio-sources-research.md` |
| 已验证曲库（30 首逐条） | `docs/00-verified-tracks.json` |
| PRD | `docs/01-prd.md`（v1.1） |
| 架构 | `docs/02-architecture.md`（v1.1a） |
| 实现记录 | `docs/03-implementation.md` |
| 本验收报告 | `docs/04-qa-report.md` |
| QA 套件与证据 | `qa/`（9 脚本 + `results/round3/`、`results/round4/`、`results/round5/` 数据 + `screenshots/`） |
| 曲库动态更新 | `meditation/tools/refresh-sources.py` + `meditation/.github/workflows/refresh-sources.yml` |

**最终 ROUTE：NoOne** —— 全部 99 条正式断言（Round 5 口径）稳定通过，0 源码失败；10 项未验证为跨浏览器与本环境时间限制，已逐条如实披露，无需工程或 QA 返工。

---

## 12. Round 4：声音库（P0-1）功能验收

> 触发需求：P0-1「曲目浏览与主动选择」——把原本只能「换一曲」盲听的 30 首曲目，变成可浏览、可按场景/类型筛选、可点选播放的声音库。
> 本轮 QA 只做一件事：把该功能**契约化**进自动化套件，并跑一次完整回归作为推送前的最终闸门。站点源码（`meditation/**`）本轮**零改动**。

### 12.1 本轮新增的 10 条正式断言

| 用例 | 断言内容 | 判定要点 |
|---|---|---|
| ST-25 | HTML 契约 | `#btn-library` 同时带 `aria-expanded="false"` 与 `aria-controls="library-panel"`；`#library-panel` 默认带 `hidden`（默认收起、不预加载） |
| ST-26 | 样式契约 | `app.css` 定义 `.library-panel` / `.lib-track` / `.lib-chip` / `.is-current`；`.lib-track` 的 `min-height` 取 `var(--touch)`（=44px）；声音库 CSS/JS 区块内 **0 处** `data-track-name`（避免与 A14 许可清单的 30 条扫描锚点混淆） |
| ST-27 | 白名单投影 | `ui.js` 只输出 `data-lib-name` / `data-lib-track` / `getUiTrackList` 投影，**0 处** `originalTitle`；`main.js` 导出 `getLibrarySnapshot` / `selectTrack` / `setLibraryFilter` |
| BR-40 | 默认态 + 禁自动播放 | 面板 `hidden=true`、`aria-expanded=false`、`aria-controls=library-panel`；首次手势前 media 请求 0、`playState=idle` |
| BR-41 | 30 首 + 零泄露 | 恰好 30 个 `.lib-track`；曲名集合与清单 `display` 集合**完全相等**；面板 `innerText` 无任何 `originalTitle`、无 `http://`/`https://`、0 个 `[data-track-name]` 节点 |
| BR-42 | 筛选计数 | 场景 focus 6 / sleep 3 / empty 17 / meditation 4；类型 music 21 / nature 9；每种筛选恰一个 `aria-pressed="true"` 且与所选一致 |
| BR-43 | 空结果组合 | 场景=助眠 + 类型=自然录音 → 0 首；计数显示 0；出现空态提示；筛选条仍可点回非空组合；零新增控制台错误 |
| BR-44 | 快照形状 | `getLibrarySnapshot()` 顶层键恰为 `{filter, visibleCount, total, tracks}`；`filter` 恰为 `{scene, kind}`；每条曲目键恰为 `{id, display, scene, kind}`；`total=30`；`tracks.length === visibleCount` |
| BR-45 | 点选 + 收敛自洽 | 点击瞬间仅该按钮 `aria-pressed="true"` 且 `.is-current`；`tracks[0].trackId` = 所选 id；`currentSource.trackId ∈ {null, 所选 id}` 且**绝不等于上一首**；20s 内收敛为自洽终态（见 §12.5） |
| BR-46 | 键盘 / a11y / 收口 | `.lib-track` 可通过 `.focus()` 获得焦点；每个按钮的 `data-lib-name` 与可见曲名逐一相等；再次点击收起面板（`hidden=true` + `aria-expanded=false`）；整组零 console / pageerror / HTTP 4xx-5xx |

### 12.2 Round 4 逐套件结果（`qa/results/round4/summary.json`）

| 套件 | 总用例 | 通过 | 失败 | 未验证 | 耗时 |
|---|---|---|---|---|---|
| env_probe | 11 | 6 | 0 | 5 | 10.2s |
| static_contracts | 27 | 27 | 0 | 0 | 0.2s |
| refresh_script | 7 | 7 | 0 | 0 | 15.4s |
| browser | 50 | 45 | 0 | 5 | 114.7s |
| degrade_repeats | 6 | 6 | 0 | 0 | 81.8s |
| **合计** | **101** | **91** | **0** | **10** | **100% 正式通过率（91/91）** |

- 10 个 UNVERIFIED 与 Round 3 完全同源、同条目（EP-02.chromium/firefox/webkit、EP-05、EP-06、BR-31 ×4、BR-33），均为跨浏览器启动能力与本环境 60 分钟浸泡限制，未新增、未美化。
- 本轮 **0 FAIL**，无需任何用例降级、重试豁免或断言放宽；既有用例编号与判据一律未改动（新增编号从 ST-25 / BR-40 起，不冲突）。
- ST-01 在清理 `__pycache__` / `.pyc` 后的干净树上复跑仍为「实际文件数=15、缺失=[]、违规=[]」。
- 原始控制台输出归档于 `qa/results/round4_console.log`；逐套件 JSON 与合并结果在 `qa/results/round4/`（`summary.json` 的 `round=4`、`ROUTE=NoOne`）。
- 本轮 BR-45 实测终态为 `bundled-primary`（`pick=jamendo-002032`，`tier=bundled`、`currentSource.trackId=jamendo-002032`），即所选曲目成功在线接入；另两种自洽终态见 §12.5。

### 12.3 闸门映射（新增断言 → 验收要点）

| 验收要点 | 覆盖用例 |
|---|---|
| P0-1 曲目可浏览 / 可筛选 / 可点选 | BR-41 / BR-42 / BR-43 / BR-45 |
| P0-11 首次手势前零发声（禁自动播放） | BR-40 |
| A5 触控区 ≥44px、aria 状态可读 | ST-26 / BR-42 / BR-46 |
| A6 控制台零 error / 零 404 | BR-43 / BR-46 |
| A13 契约快照字段零冗余 | BR-44 |
| A14 / AD-21 展示层只吃白名单投影（零 `originalTitle`、零裸 URL） | ST-27 / BR-41 |
| P1-09 面板结构 / 默认收起 / 可恢复 | ST-25 / ST-26 / BR-40 / BR-46 |

### 12.4 两处 lead 修复的回归护栏

BR-45 同时守护本轮修掉的两个状态一致性缺陷，二者都是「高亮/署名指向上一首」的用户可见错误：

1. **`player.js#switchMainTrack` 清空 `currentSource`**：切换主音源时先摘除旧在线音源、再重建合成垫声。如果在「合成垫声 → 在线升级」窗口内不清空 `currentSource`，`renderInfoPanel` / `renderLibraryPanel` 会读到上一首的 `trackId`，把旧曲的署名与高亮错配到新点选的曲目上。BR-45 的「点击瞬间 `currentSource.trackId ∈ {null, 所选 id}` 且 ≠ 旧值」正是这条修复的断言。
2. **`player.js#attachOnline` 用 `attachedTrackId`**：`resolveCandidates()` 允许「同场景其它已验证曲目」作为真实备选池，因此备用 URL 可能属于另一首曲目。署名、高亮、健康度必须跟着**实际在播的 URL** 走（`attachedTrackId = track ? track.id : currentMainTrackId`）。BR-45 的终态判据要求「DOM 高亮 == `tracks[0].trackId` == `currentSource.trackId`」三者互指，实际在播是备选曲目时高亮也必须跟着备选曲目，而不是最初请求的 id。

### 12.5 诚实说明：3s 加载预算 vs archive.org 首包时延

BR-45 **不要求**终态必须是 `tier=bundled`（在线）。原因有三：

1. 设计常量 `LOAD_TIMEOUT_MS = 3000` 是首屏「3 秒内必须出声」的硬约束（P0-06），而 archive.org 是第三方公共服务：本轮 BR-16 批量实测单曲完整下载 5.7~9.6s；本轮独立探针（`preload=none` + `play()`）测得三个样本的首包 `canplay` 分别约 **2.5s（jamendo-002032）/ 4.5s（jamendo-131817）/ 1.6s（jamendo-122281）**，抖动极大。
2. 因此点选一首曲目后，实际可能出现三种**均为设计内**的自洽终态：
   - **(a) bundled-primary**：所选曲目在线接入成功（本轮 Round 4 实测即此态）；
   - **(b) bundled-backup**：主源超出预算，按 AD-16 切到**同场景真实备选**曲目，徽标显示「备用音源」；
   - **(c) synth-degraded**：全部候选失败，自愈回落 L0 合成层（永不静音）。
   三种终态在开发期的重复实测中**都实际出现过**（同一台机器、同一份代码，仅网络抖动不同）。
3. BR-45 于是断言「**状态自洽**」而非「必须为 bundled」：无论落到哪一态，`currentSource.trackId` / `tracks[0].trackId` / DOM 高亮三者必须互指，且合成层态必须 `trackId=null` 且不留高亮、并确实记录了一次降级事件。这样既不掩盖真实故障（错配、残留旧曲目、假高亮一律 FAIL），也不会把 archive.org 的网络抖动误判成源码缺陷。

> **需产品侧知悉的 UX 口径**：当所选曲目首包超出 3s 预算时，用户可能听到同场景的**另一首**曲目（徽标为「备用音源」），面板高亮与信息面板会如实跟随实际在播曲目。这是既有自愈设计的必然结果，不是本轮引入的缺陷；若产品要求「点了哪首就必须是哪首」，则需调整 `LOAD_TIMEOUT_MS` 或改为「仅同曲目候选、失败即降级 L0」。本轮 QA 按现状如实断言，不擅自改判。

### 12.6 本轮 QA 变更清单（仅 `qa/*` 与本文档）

| 文件 | 变更 |
|---|---|
| `qa/test_static_contracts.py` | 新增 ST-25 / ST-26 / ST-27（HTML、CSS、白名单投影三组静态契约） |
| `qa/test_browser.py` | 新增 `group_library(s, browser, base_url, manifest)` 与 BR-40~BR-46；在 `run()` 中紧随 `group_core` 之后调用，复用同一页面以控制耗时 |
| `qa/run_all.py` | `--round` 合法值扩展为 `[1, 2, 3, 4]`，本轮结果归档到 `qa/results/round4/` |
| `docs/04-qa-report.md` | 结论数字更新为 Round 4 口径，并追加本节 |

---

## 13. Round 5：收藏与混音预设（P0-2）功能验收

> 触发需求：P0-2「收藏 + 自定义混音预设」——把「再听一次刚才那套混音」变成可收藏曲目、可保存/跨场景还原的混音处方。
> 本轮 QA 只做一件事：把该功能**契约化**进自动化套件，并跑一次完整回归。断言开发阶段站点源码零改动；本轮站点源码的改动全部集中在两处缺陷修复：BR-52 抓到的预设还原缺口（§13.2）、BR-55 抓到的降级态悬空句柄（§13.6）。

### 13.1 本轮新增的 8 条正式断言

> 8 条的构成：ST-28（P0-4a 对比度闸门，Round 4 报告成稿后随 a11y 修复落地）+ **P0-2 相关 7 条**（ST-29 静态契约、BR-50~BR-54 浏览器端到端、BR-55 降级态恢复）。用例总数 101 → 109、正式断言 91 → 99。

| 用例 | 断言内容 | 判定要点 |
|---|---|---|
| ST-28 | 设计令牌对比度实算 | 直接由 `app.css` 中的颜色令牌两两实算对比度：正文 ≥ 4.5:1、控件/焦点 ≥ 3:1（不靠肉眼与截图） |
| ST-29 | 收藏与预设静态契约 | ① `STORAGE_KEYS` 恰 5 个键，含 `sw.favorites.v1` / `sw.presets.v1`；② `clearAll` 体内同时有 `removeStorage(K.favorites)` 与 `removeStorage(K.presets)`；③ `SW.store` 导出 6 个收藏/预设方法；④ `main.js` 契约含 3 个快照（favorites / presets / mixSpec）与 4 个动作（toggleFavorite / savePreset / deletePreset / applyMix）；⑤ `ui.js` **0 处** `prompt(` / `alert(` / `confirm(`（不用阻塞式弹窗）；⑥ `#btn-presets` 带 aria 关联且 `#preset-panel` 默认 `hidden`；⑦ `#btn-fav-only` 不在 `.lib-filters` chip 组内；⑧ `.lib-fav` / `.preset-apply` / `.preset-delete` 三条规则均含 `min-height: var(--touch)`；⑨ 展示层零 `originalTitle` |
| BR-50 | 收藏往返 + 只看收藏 | 收藏 3 首 → `count=3`；`localStorage['sw.favorites.v1']` 键恰为 `{v:1, ids}` 且 `v=1`；重绘后 `.lib-fav[aria-pressed="true"]=3`（总星标 30）；点 `#btn-fav-only` → 列表恰 3 首且 id 集合等于收藏集、按钮不在筛选组内；再点 → 30 首；reload 后仍 3；取消 1 首 → 2 且存储同步；零 console / pageerror |
| BR-51 | 预设跨场景精确还原 | 播放后采样 `getMixSpec()` 至连续两次一致得 `specA` → `savePreset` 成功 → 切场景后 `getMixSpec()` **必须与 `specA` 不同**（防「本来就没变」的假绿）→ `applyMix(specA)` 返回 `{ok:true,pending:false}` → 8s 内 `getMixSpec()` 与 `specA` **逐字段深比较相等**、`playing` 仍为 true、零新增错误 |
| BR-52 | 未启动应用预设：禁自动播放 + 首次手势落地 | `applyMix` 在未启动态返回 `{ok:true,pending:true}`；AudioContext 未创建（`none` / `suspended`）；`playing=false`、`playState=idle`；配置态已生效（`scene=sleep`、`masterVolume=0.42`）；点 `#btn-play` 后 6s 内 `playing=true` 且 `getMixSpec().tracks` 与传入 `tracks` **逐条相等** |
| BR-53 | 存储不可用降级 | `inject.setStorageUnavailable(true)` 后 `toggleFavorite` / `savePreset` 均 `{ok:true}` 不抛错；`getState().storageMode=memory`；声音库仍 30 首可交互；零 console / pageerror |
| BR-54 | `clearAll` 彻底性 + 损坏数据容错 | 先造 2 收藏 + 1 预设 → `clearStorage` → 直读 `sw.favorites.v1` / `sw.presets.v1` / `sw.prefs.v1` **三键均为 null**；写入损坏 JSON（`{not json`）与版本不符数据（`{"v":99,...}`）后 reload → 两个快照 `count=0`、声音库仍 30 首、零新增 page error |
| BR-55 | 降级态：定时器渐弱结束后再播放仍能恢复且零异常 | 全程 `inject.setOffline(true)`（不依赖 archive.org）：起播并降到 `sourceTier=synth`（8s 未降级即 FAIL）→ `setTimer(0.05, 30)` → 等 `timer.phase=ended`（12s）→ 断言 `playing=false`、`effectiveGain.fade=1` → 再 `play()`：**不抛异常**、`playing=true`、`playState=playing`、pageerror 与 console error 增量均为 0、`tracks≥1`、`master>0` |

本轮全量逐套件结果（`qa/results/round5/summary.json`，`round=5`）：

| 套件 | 总用例 | 通过 | 失败 | 未验证 | 耗时（单机一次全量，量级参考） |
|---|---|---|---|---|---|
| env_probe | 11 | 6 | 0 | 5 | 10.9s |
| static_contracts | 29 | 29 | 0 | 0 | 0.4s |
| refresh_script | 7 | 7 | 0 | 0 | 12.7s |
| browser | 56 | 51 | 0 | 5 | 142.8s |
| degrade_repeats | 6 | 6 | 0 | 0 | 90.7s |
| **合计** | **109** | **99** | **0** | **10** | **≈4m18s，正式通过率 100%（99/99）** |

变更边界：`qa/test_static_contracts.py` 新增 ST-29 与 `strip_js_comments()`（ST-28 由 P0-4a 对比度修复一并加入）；`qa/test_browser.py` 新增 `group_presets()` / BR-50~BR-54、`group_resume_degraded()` / BR-55，并把 BR-17/BR-30 从「单次采样」改为「3 次内任一次在线即通过」；`--round` 合法值已含 5。`meditation/`、`stillwave/`、`qa/common.py`、`qa/harness.py` 未被 QA 改动。

### 13.2 BR-52 抓到的真实缺陷与修复闭环

**现象（修复前）**：`applyMix` / `applyPendingMix` 只做三件事——裁剪到预设轨数（`trimSlots`）、补齐缺失层（`fillMissingSlots`）、按索引对齐音量（`applyMixVolumes`）。全程没有任何一步把 spec 里的 `voice` 写回**已有**槽位。当目标场景处方的层数 ≥ spec 轨数、且同索引的 voice 不同时，预设里的声景就被场景处方**静默顶替**。

**实测**（未启动路径与已启动路径结果相同）：

```
spec  : {scene:'sleep', masterVolume:0.42, tracks:[rain@0.33, brown@0.21]}
before: [rain@0.33, rain@0.21]        ← brown 被 sleep 处方的 rain 顶替
```

全程 `console` / `pageerror` 均为 0——这是**静默**错误，只有逐字段比对 `getMixSpec()` 才能发现，靠「看着能出声」永远抓不到。

**产品可达路径**：播放 → 打开混音 → 删掉 layer-0 / layer-1 → 加「白噪」→ 保存预设 → 切到助眠（`applyScene` 按处方重建槽位）→ 切回原场景 → 应用该预设 → 自定义的「白噪」层丢失。即不是只有契约层才能构造的极端入参。

**修复（`meditation/js/player.js`）**：删除 `trimSlots` / `fillMissingSlots`，收敛为 `reconcileLayers(mix)`：

- 只比较 `slots[1..]` 与 `mix.tracks[1..]` 的 voice 序列；**完全一致时零扰动**（不删不建，仅改音量），并以 `SW.RUNTIME.reconcileSkipped` 留下自检痕迹——守住「不打断正在播放的声景」的低刺激边界；
- 不一致时：倒序 `removeTrack()`（沿用既有淡出 + `scheduleRelease`，不直接 `splice`）清空全部非 main 槽位，再按 spec 顺序 `addTrack(voice)` 重建（触顶即停）；
- `slots[0]`（main）**永不触碰**：不改其 voice / trackId / url / display / volume，也不移除；在线主音轨仍只由 `selectTrack` / `upgradeMain` 处理；
- `applyPendingMix` 与 `applyMix` 都改为 `reconcileLayers(mix) → applyMixVolumes(mix)`；
- 还原过程不触碰 `recordDegrade` / badge / playing：还原混音不是降级事件。

**附带收紧（`sanitizeMix`）**：索引 >0 的 `{kind:'track'}` 条目一律丢弃。因为同时只有一首在线曲目，`slots[1..]` 恒为合成声景；若接受这类条目，`applyMix` 会返回 `{ok:true}` 但还原时必然丢轨，破坏「**被接受的 spec 一定能被 `getMixSpec()` 精确复现**」这一不变式。独立复核：传入 `[rain@0.33, {kind:'track', trackId:'jamendo-002032'}@0.21]`，`applyMix` 仍 `{ok:true,pending:true}`，手势后 `getMixSpec()` 只返回 1 条 `rain@0.33`，与收窄后的 spec 一致（`equal=true`，零 console）。

**修复后**：BR-52 的九项子判据全绿——`{ok:true,pending:true}` / `ctxState ∈ {none, suspended}` / `playing=false` / `playState=idle` / `scene=sleep` / `masterVolume=0.42` / 手势后 `playing=true` / `expectedTracks == actualTracks` / 零 console·pageerror。实测 `actualTracks=[rain@0.33, brown@0.21]`，与传入逐条相等。

**断言强度未变**：BR-52 自首跑起就是「逐条逐字段相等」的完整比较，转绿不是放宽判据换来的；同一次全量内 BR-40~BR-46、BR-50 / BR-51 / BR-53 / BR-54 与 BR-16 / BR-16b、BR-17、BR-30、DR-A/B 均无回归。

### 13.3 断言有效性验证（注入 → 变红 → 还原 → 复绿）

| # | 注入位置 | 注入方式 | 变红用例 | 实测红态 |
|---|---|---|---|---|
| 1 | `js/store.js#clearAll` | 注释掉 `removeStorage(K.favorites)` | ST-29 | `clearAll=False`（收藏键不再被清除） |
| 2 | `js/ui.js#renderLibraryPanel` | 「只看收藏」分支改为 `if (false && onlyFavorites…)` | BR-50 | `domOnly.tracks=30`（列表未收敛到 3 首） |
| 3 | `js/player.js#applyMix` | 删去 `applyScene(mix.scene)` | BR-51 | `specB == specA`，`changed=False`（「必须变过」的前提不成立） |
| 4 | `js/player.js#applyMix` | 未启动分支加入 `startFromGesture()` | BR-52 | `ctxState=running`、`playing=true`（禁自动播放判据红） |

四次注入在还原后 4 条断言全部复绿；每处还原都用 `cmp` 与注入前快照做字节比对、`shasum -c` 全 OK，确保「变红」不是别处改坏导致的连带效应。

**另一类有效性证据：先红后绿（非注入）**。BR-55 的红不是人为注入造出来的——它是在**未修复的站点**上首跑就红（`playError` 含 `Cannot read properties of null (reading 'gain')`、`playingAfter=false`、`playStateAfter=paused`），修复后同一个用例、同一套判据转绿（`playError=null`、`playingAfter=true`、`playStateAfter=playing`、错误增量 0）。这比注入验证更强：它证明这条断言确实指向一个真实缺陷，而不是为了绿而写的空壳。详见 §13.6。

**必须单独记一条「自证伪」**：ST-29 的第一版实现用全文文本匹配判定条件，注入 #1 之后**依然是绿的**——因为被注释掉的那行仍留着 `removeStorage(K.favorites)` 子串，断言被注释骗过。这是一次典型的**假绿**。修正为先 `strip_js_comments()` 剥掉块注释与行注释、再在剥净后的代码上评估 `clearAll` 体 / `SW.store` 导出 / `buildActions` 块 / `prompt|alert|confirm` 扫描 / `originalTitle` 计数，同一注入才如实变红。这条记录的意义大于 ST-29 本身：它证明本套件对「文本匹配型静态断言」的假绿风险做过对抗验证，而不是把「绿」当可信。

### 13.4 三处实现偏差（如实记录）

1. **`getMixSpec()` 数据源**：原实现只读运行时槽位，首播前 `slots` 尚未建立 → 「首播前保存当前混音」必然失败（`reason:'tracks'`）。已改为三级数据源：运行时槽位 → `pendingMix` → 场景处方。
2. **`actions.toggleFavorite` 是纯数据入口**，不 emit 重绘事件。BR-50 的 DOM 星标断言（`.lib-fav[aria-pressed="true"]=3`）前需触发一次真实渲染（用例用 `setLibraryFilter('all','all')` 驱动一次），并同时记录「未重绘时 `pressed=0`」，以区分「数据没写进去」与「只是没重绘」。
3. **`getLibrarySnapshot()` 按设计只反映 scene / kind 筛选**，不反映「只看收藏」（后者由 `getFavoritesSnapshot().onlyFavorites` 暴露）。因此 BR-50 对「只看收藏」的结果用 `.lib-track` DOM 计数断言，而不是拿快照当唯一真相。

### 13.5 已知边界（不修，声明）

预设 / 分享 spec 的 `tracks[0]` 若为 `{kind:'voice', voice:X}` 且 X ≠ 该场景处方的 `padVoice`，还原后主槽位仍是**场景垫声**而非 X：`reconcileLayers` 只对齐 `slots[1..]`，主槽位 voice 由 `applyScene` / `buildSceneSlots` 决定。

- 现有 P0-2 UI 走不到这一态：主槽位 voice 只能由场景决定，保存预设时 main 的 voice 也来自同一场景处方，二者天然一致；track 型主音轨走 `selectTrack` / `upgradeMain`。
- 同一语义的另一面：`tracks[0].kind:'track'` 的 spec 只有在在线音源**真正挂上**之后（`selectTrack` → `attachOnline` 完成）才会与 `getMixSpec()` 深等；在挂载窗口内以及降级 / 离线态，主槽位如实报 `{kind:'voice', voice:padVoice}`（`getMixSpec()` 只在槽位 `kind==='audio'` 且有 `trackId` 时才投影为 track）。这是 A14 白名单投影下的真实语义，**不应为了让断言变绿而改动**；BR-51 采样前等到连续两次读数一致、BR-52 在 pending 落地后取样，因此都不落在该窗口内。
- 该缺口**未修复**，也不影响 BR-52 的九项判据；记为 P1 候选——未来若开放「自定义主垫声」或支持外部分享链接，必须一并处理。

### 13.6 降级态悬空句柄：点播放没反应

**现象（用户可见）**：网络到 archive.org 不可达或超时、产品按 AD-16 降到 L0 合成层之后，用户起播 → 设定时器 → 渐弱到点自然结束 → **再按播放没有任何反应**。没有报错提示，按钮状态也不动。

**根因（函数级）**：`player.js#degradeToSynth` 对 `handles['main']` **无条件**执行 `scheduleRelease([old], 220)`，随后又因为 `old.type === 'synth'` 走「不重建」分支。于是当主槽位本来就是合成垫声时，`handles['main']` 被释放成空壳——`releaseVoice` 把 `trackGain` 置为 null，但没有任何代码把这个键从 `handles` 里摘掉。调试副本站实测：从 `start + 0.4s` 起该句柄就是 `{"id":"main","type":"synth","hasGain":false,"released":true}`，一路持续到 `timer ended`。

**后果链**：`play()` 里读 `h.trackGain.gain` 抛 `TypeError: Cannot read properties of null (reading 'gain')`（`player.js:476`）→ 异常发生在 `store.patch({playing:true})` **之前** → `playing` 永远停在 false（用户点播放无反应），同时产生未捕获 pageerror（破坏 A6 零异常）。

**修复（`meditation/js/player.js`，净 +25/−7）**：

1. `degradeToSynth`：只在 `old.type !== 'synth'`（即真的在播在线音源）时淡出并释放；synth 垫声直接复用。已释放的句柄（`!old.trackGain`）先归一化为 null，走幂等重建分支。这是根因修复。
2. `play()`、`applyDrift()`（两处）、`setTrackVolume()` 四处无保护解引用补空值守卫。明确**不使用**整体 `try/catch`——那会把真故障变成静默失败，正是这条缺陷难被发现的同类错误。
3. `scheduleRelease()` 释放后从 `handles` 中删除仍指向同一对象的键，使「`handles` 只装活句柄」成为不变式（兜底，不替代第 1 条）。

**红 → 绿闭环**：新增 `BR-55` 先在旧件上跑红——`playError` 含 `Cannot read properties of null (reading 'gain')`、`playingAfter=false`、`playStateAfter=paused`，全量 **109 / 98 / 1**；修复件上转绿——`playError=null`、`playingAfter=true`、`playStateAfter=playing`、pageerror 与 console error 增量均为 0、`tracks=3`、`master=0.45`，全量 **109 / 99 / 0**，`ROUTE: NoOne`。同一次全量里 BR-09~BR-12 与 DR-A/DR-B（30 次降级复现，2802~2804ms）全部 PASS，说明修复没有改变自愈耗时与降级行为。

**必须记下的一条过程事实**：这条缺陷在上一轮曾被 QA 误判为「既有产品边界、与本次改动无关」——当时的对照实验只证明了「正常路径不触发」，却被外推成「不是缺陷」。随后主理人用带调试钩子的副本站把根因定位到函数级并证伪了该结论，缺陷按 P0 修复，BR-55 长期守住它。这是本轮质量体系里最值得记的一条：**把真缺陷说成「边界」，比漏测更危险**——漏测至少还留有被发现的机会，而错误结论会直接关掉追查的方向。该错误判断已在本报告中撤回，保留在此作为流程教训。

### 13.7 未验证 10 条（沿用不美化）

| 用例 | 原因 |
|---|---|
| EP-02.chromium / EP-02.firefox / EP-02.webkit | Playwright 三个引擎的 headless shell 在本机不可启动（二进制存在，启动超时） |
| EP-05 | 系统 Safari 经 `safaridriver` 不可驱动 |
| EP-06 | Safari / Firefox 完整使用路径（因上述能力缺失而未执行） |
| BR-31.chromium / .firefox / .webkit / .safari | 跨浏览器完整核心路径，随 EP-02 / EP-05 一并未验证 |
| BR-33 | 60 分钟连续播放（内存泄漏 / 循环接缝），本环境时间成本不划算，仅做了 9 分钟浸泡（A7 PARTIAL） |

这 10 条与 Round 3 / Round 4 完全同源、同条目，本轮**未新增、未美化、未用其他用例替代**；它们不计入正式断言分母（109），也不被算作通过。

---

## 14. Round 6：全面审计轮（P0-3 收尾 · 2 个缺陷 · P0-4b 键盘收口）

> 本轮输入：「全面检查和审核，挖掘值得改进或修复的地方，逐一处理、测试。」
> 结论：**修复 2 个真实缺陷、补齐 1 项键盘/焦点能力、明确 1 条不修的产品边界**；全量 **119 用例 / 109 正式断言 / 0 失败 / 10 未验证（100%）**，`ROUTE: NoOne`。
> 纪律：本轮所有结论都先有实测数据再下判断；每个新断言都做了「注入 → 变红 → 还原 → 复绿」的有效性验证，未验证的推断不写进结论。

### 14.1 逐套件结果（`qa/results/round2/summary.json`）

| 套件 | 用例 | 通过 | 失败 | 未验证 |
|---|---|---|---|---|
| `env_probe`（环境能力探测） | 11 | 6 | 0 | 5 |
| `static_contracts`（静态契约） | 31 | 31 | 0 | 0 |
| `refresh_script`（曲库刷新脚本） | 7 | 7 | 0 | 0 |
| `browser`（真实浏览器） | 64 | 59 | 0 | 5 |
| `degrade_repeats`（降级耗时复现） | 6 | 6 | 0 | 0 |
| **合计** | **119** | **109** | **0** | **10** |

本轮新增 3 条正式断言：`ST-31`（静态：分享还原挂起偏好回写）、`BR-62`（浏览器：分享链接不改写本地偏好）、`BR-63`（浏览器：Escape 收起面板并归还焦点）；另把 `BR-61` 扩展为「分享面板内键盘操作零 AudioContext」。

### 14.2 缺陷 A：打开别人的分享链接，会永久覆写访问者自己的本地偏好（已修）

**现象（用户可见）**：访问者本地偏好是「放空 + 主音量 0.8」。点开朋友发来的链接 `#sw=1&s=sleep&mv=60&tr=v:rain:33` 之后，配置确实变成「助眠 + 0.6」；**但访问者从此以后正常打开站点，看到的都是这条链接的配置**——他自己的设置被静默替换，没有任何提示。

**一手证据（修复前）**：

```
本地偏好(前)      : {"scene":"empty","masterVolume":0.8,"brightness":"normal", ...}
本地偏好(开链接后): {"scene":"sleep","masterVolume":0.6,"brightness":"extreme",
                    "timerPresetMinutes":30,"timerPresetFade":60, ...}
后续访问普通页面  : scene=sleep mv=0.6      ← 原设置（放空/0.8）已丢失
```

**根因（函数级）**：分享还原走 `player.applyMix()`，而 `applyMix` 内部会经四条路径调到 `store.savePrefs()`：`applySceneConfigOnly()`（未启动时改场景处方）、`applyScene()`、`setMasterVolume()`、以及 `syncSlots()`（每次槽位同步）。于是「读一个链接」这个动作被当成了「用户改了自己的设置」。

**修复**：
1. `store.js` 新增 `holdPrefs()` / `releasePrefs()`（**计数式**挂起，避免嵌套调用被一次释放提前解冻）与 `getPrefsWriteStats()`；`savePrefs()` 在挂起期间只改内存、**不回写 `sw.prefs.v1`**，并累加 `skipped` 计数。
2. `main.js#restoreFromHash()` 用 `try/finally` 把 `player.applyMix(...)` 整段包住：进入前 `holdPrefs()`，无论成功/异常/抛错都 `releasePrefs()`。
3. 语义收口：**分享链接只对本次会话生效**；访问者此后自己拖动音量、切场景等主动操作产生的写入照常持久化（不做任何"魔法"拦截）。

**红 → 绿闭环**：
- 静态断言 `ST-31` 做了**两次独立注入**，各自如实变红，还原后复绿：① 把 `savePrefs()` 里的 `if (prefsHoldDepth > 0)` 改成 `if (false)`（守卫失效）→ `30/31，失败 1`；② 把 `restoreFromHash()` 里的 `store.holdPrefs()` 换成空语句 → `30/31，失败 1`；两次都已 `cmp` 逐字节还原。
- 行为断言 `BR-62` 在同一次探针上先给出红证据（上表「后续访问普通页面＝sleep/0.6」），修复后 PASS：`before/afterHash/afterFresh` 三处 `sw.prefs.v1` 均为 `empty/0.8`，而 `state` 在两条路径（同标签页 `hashchange`、新文档首屏）上都还原为 `sleep/0.6`，之后再访问无 hash 页面仍是 `empty/0.8`，零 pageerror / console error。

### 14.3 缺陷 B：分享面板内的键盘操作会静默建立 AudioContext（已修）

**现象**：剪贴板不可用时点「分享当前配置」会展开手动复制面板并把焦点放进输入框；这时按 **Escape 收起面板**，`state.audioContext` 会从 `none` 变成 `running`——即"复制一条链接"这个纯读配置的动作，把音频图建起来了。

**一手证据（修复前）**：探针在强制 `navigator.clipboard = undefined` + `execCommand → false` 后，点击 `#btn-share` → 面板展开、焦点 `share-fallback-input` → 按 Escape → `{"hidden": true, "expanded": "false", "focused": "btn-share"}` 但 `ctx=running`。

**根因**：`main.js#bindFirstGesture` 的首次手势监听器把 `#btn-share` 内的点击排除了，但**只排除了按钮本身**；Escape 的 `ev.target` 是面板里的输入框，`closest('#btn-share')` 为 null，于是被当成"真实音频意图"去 `synth.ensureContext()`。

**为什么算缺陷而不是边界**：同一个动作走两条路得到两种状态——`actions.copyShareLink` 后 `audioContext` 是 `none`，真实键盘操作后是 `running`。P0-3 自己声明的口径是「分享路径严格零 AudioContext（硬边界 3）」，行为与声明不一致就是缺陷。

**修复**：守卫从 `target.closest('#btn-share')` 扩为 `target.closest('#btn-share, #share-panel')`——按钮与面板内的任何操作（含输入框里按 Escape）都不解锁音频；监听器保留，下一次真实音频意图（点播放 / 切场景 / Tab 进入控件）照常静默解锁。

**红 → 绿闭环**：把守卫注入回 `#btn-share` 单值 → `lead_audit2` 第 3 项 `FAIL（ctx=running）`；还原 → `PASS（ctx=none）`。`BR-61` 同步扩成三段：契约动作复制（`ctx none`）、面板内 Escape（`ctx none`、`playing=false`）、`file://` 还原可用。

### 14.4 P0-4b：Escape 收起面板 + 焦点归还 + aria-expanded 同步

**背景**：此前六个折叠面板（分享 / 添加声景 / 预设 / 声音库 / 详情 / 音源信息）在键盘上"进得去、出不来"——Escape 无任何反应，读屏用户只能一路 Tab 回触发按钮。

**实现**（`ui.js`）：
- 新增单一面板表 `PANEL_TRIGGERS`（面板 id ↔ 触发按钮 id）与 `closeTopPanel()`；`keydown` 监听只在 `Escape`（含旧名 `Esc`）时动作，**一次只关最上层那一个**，避免一次按键把整屏收掉。
- 收起后同步 `aria-expanded="false"` 并把焦点交还 `aria-controls` 指向本面板的那个按钮（"从哪来回哪去"）。
- `#btn-add` 补上 `aria-expanded="false"` / `aria-controls="voice-picker"`，并在展开、选中声景后同步——此前这个按钮完全不告诉辅助技术"我打开了一个东西"。
- 分享面板复用既有 `closeSharePanel()`，保证 `hidden` 与 `aria-expanded` 只有一处真源。

**证据（BR-63 实测）**：`{"library":{"hidden":true,"expanded":"false","focus":"btn-library"}, "addOpen":{"hidden":false,"expanded":"true"}, "add":{"hidden":true,"expanded":"false","focus":"btn-add"}}`。

### 14.5 独立探针（17 项，不复用 QA 脚本）

主理人另写 `lead_audit2.py` 独立驱动真实 Chrome，全部 PASS：

| 检查 | 结果 |
|---|---|
| 分享面板 Escape 收起 + `aria-expanded=false` | PASS |
| 关闭后焦点回到 `#btn-share` | PASS |
| 打开/关闭分享面板都不触发播放、不建 AudioContext | PASS（`ctx=none`） |
| 声音库 Escape 收起 + 焦点回 `#btn-library` | PASS |
| 添加声景 `aria-expanded` 随展开/收起同步 | PASS |
| 添加声景 Escape 收起 + 焦点回 `#btn-add` | PASS |
| 连发 3 次 hash 后最终值生效（节流末值不丢） | PASS（`meditation/0.25`） |
| 连发 hash 零 `pageerror` / console error | PASS |
| 播放中还原分享链接：播放不中断 | PASS（`playing=true`、`playState=playing`） |
| 播放中还原：场景与声景层换成链接内容 | PASS（`rain`+`brown`） |
| 播放中还原零错误 | PASS |
| 四场景混音往返一致（focus / sleep / empty / meditation） | PASS ×4（`getMixSpec()` 逐字段相等） |
| `file://` 下点分享不抛错、不触发播放 | PASS |
| `file://` 下分享链接为 `file:` 协议、无原始标题泄露 | PASS |

### 14.6 明确不修的产品边界：手写外来链接的首段 voice

**事实**：主槽位（`slots[0]`）的 `voice` 由场景处方 `buildSceneSlots()` 决定（`C.SCENES[scene].padVoice`），`applyMixVolumes()` 按索引对齐音量。所以一条**手写/裁剪过**的链接，如果首段 `v:<voice>` 不等于该场景的垫声，只有音量会被采纳，声景会变成场景垫声。

**实测**：场景 `focus`（垫声 `brown`）打开 `#sw=1&s=focus&mv=50&tr=v:rain:30` → 还原为 `[{"voice":"brown","volume":0.3}]`。

**为什么判定为边界而不是缺陷**：站内生成的链接首段恒等于该场景垫声，四场景（含用户自加声景层）往返 **4/4 逐字段相等**（§14.5 表），真实用户链路零损失；这条只影响人工改写的链接，且音量仍然被尊重、不静默清空。

**为什么不在这轮改**：改动主槽位 voice 语义会牵动已被 8 条分享/预设断言与自愈升级链（`upgradeMain` / `degradeToSynth`）验证过的路径，收益（仅手写链接）与回归风险不成比例。列为 **P1**，将来若做，方向是在 `sanitizeMix()` 里把"非本场景垫声的首段 voice"下移为叠加层，并按 `buildSceneSlots()` 的 `mainVolume`（有主音源曲目时 `1.0`、冥想场景 `0.06`）插入垫声段，再做四场景往返 + 满 3 轨边界验证。

### 14.7 本轮变更清单

| 文件 | 变更 |
|---|---|
| `js/store.js` | `holdPrefs` / `releasePrefs` / `getPrefsWriteStats`，`savePrefs` 挂起期间跳过回写 |
| `js/main.js` | `restoreFromHash` 用 `try/finally` 包住偏好挂起；首次手势守卫扩到 `#share-panel` |
| `js/ui.js` | `PANEL_TRIGGERS` + `closeTopPanel()` + Escape 监听；`#btn-add` 的 `aria-expanded` 同步 |
| `index.html` | `#btn-add` 补 `aria-expanded="false"` / `aria-controls="voice-picker"` |
| `qa/test_static_contracts.py` | 新增 `ST-31` |
| `qa/test_browser.py` | 新增 `BR-62`、`BR-63`；`BR-61` 扩展"面板内键盘操作零 AudioContext" |

> 站点源文件数仍为 **15**（未新增文件），仍为纯静态、零构建、`file://` 与 Pages 子路径双兼容。

### 14.8 提交后复核发现的第三个问题：静态门禁在仓库布局下假红（已修）

**触发**：把同一份静态契约脚本直接放在 `stillwave/`（站点即仓库根）下跑，`ST-30` 报 `FAIL`，而 `ST-01` 仍是 PASS；`actual` 显示 `files=22`。

**根因**：`ST-30` 第 6 条写的是 `len(files) == 15`，而 `files` 来自 `all_site_files()` 的全目录遍历。仓库根布局额外包含 `README.md` / `LICENSE` / `NOTICE.md` / `CONTRIBUTING.md` / `CHANGELOG.md` / `.gitignore` / `.nojekyll` 共 7 个**仓库元文件**，它们不随 Pages 发布，却被算进了站点源文件数。`meditation/` 布局没有这些文件，所以之前的全量轮次一直是绿的——**同一份源码、两种布局、两种结论**，属于门禁自身的可移植性缺陷。

**修复**：`ST-30` 改为只统计会随 Pages 发布的子树（`index.html` + `js/` `styles/` `data/` `tools/` `.github/`），要求 15 个清单文件全在、且**零未登记文件**；仓库元文件不再计入。这既保留「新增站点文件必须显式更新 `EXPECTED_FILES`」的原意，又与布局无关。

**有效性验证**：两个布局各跑静态契约，均 **31/31 PASS**；随后在 `meditation/js/` 注入一个未登记的 `__qa_unexpected.js` → `ST-30` 如实 `FAIL（30/31）`；移除后 `31/31 PASS`。断言没有因修正而被放宽。





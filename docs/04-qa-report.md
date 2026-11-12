# 静澜 Stillwave · 最终验收报告（QA Report）

> 版本：v1.0 · 生成时间：2026-11-10 · 交付总监：齐活林（team lead）
> 关联文档：`01-prd.md`（PRD v1.1）· `02-architecture.md`（架构 v1.1a）· `03-implementation.md`（实现）
> 验证环境：macOS arm64 · Playwright 1.60.0 · Google Chrome（channel=chrome，headless）· Python 3.9

---

## 1. 结论（Verdict）

| 项 | 结果 |
|---|---|
| 正式断言（formal assertions） | **91 / 91 全部通过（100%）** |
| 失败（failed） | **0** |
| 未验证（unverified，环境限制，不计入源码失败） | **10** |
| 总用例 | 101 |
| ROUTE | **NoOne**（无需工程/QA 返工；10 项未验证为跨浏览器与本环境时间限制，非源码缺陷） |

> **口径说明（Round 4）**：上表为 **Round 4（声音库验收轮）** 的全量结果。相较 Round 3 的 91 用例 / 81 正式断言，本轮新增 10 条正式断言（静态 ST-25~ST-27、浏览器 BR-40~BR-46，全部覆盖新增的声音库 P0-1 功能），因此总用例 101、正式断言 91，失败仍为 0，正式通过率保持 100%。Round 4 明细见 §12。

**一句话结论**：在干净算力环境下，站点全部 91 条正式验收断言稳定通过，零源码失败；3 个此前在高负载轮次（Round 2）曾出现的失败经独立复核确认为**纯环境性**（机器负载 41.86 导致首屏 7.3s、在线音源升级未在 9s 内完成），在负载回落（≤8）后全部转 PASS；另有 1 个 30 首批量探测的偶发限流在探针加固后稳定 30/30。剩余 10 个未验证项全部是**跨浏览器启动能力**与 **60 分钟长时浸泡**的本环境/时间限制，已在 §6 逐条如实列出，绝未外推或伪造。Round 4 在 Round 3 基础上把新增的声音库（可浏览/可筛选/可点选）纳入自动化闸门，10 条新断言全部 PASS，且未削弱或改动任何既有用例。

---

## 2. 验收闸门映射（A1–A14）

| 闸门 | 验收目标 | 状态 | 关键证据 |
|---|---|---|---|
| A1 | 契约挂载、9 个 `defer` 脚本顺序、无 ESM | ✅ PASS | static_contracts 27/27（Round 4）；`node --check` 9/9 |
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
> 本节为 **Round 3 的历史留档**（91 用例 / 81 正式断言）。新增声音库断言后的 **Round 4 逐套件结果**（101 用例 / 91 正式断言）见 §12.2。

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
| QA 套件与证据 | `qa/`（9 脚本 + `results/round3/`、`results/round4/` 数据 + `screenshots/`） |
| 曲库动态更新 | `meditation/tools/refresh-sources.py` + `meditation/.github/workflows/refresh-sources.yml` |

**最终 ROUTE：NoOne** —— 全部 91 条正式断言（Round 4 口径）稳定通过，0 源码失败；10 项未验证为跨浏览器与本环境时间限制，已逐条如实披露，无需工程或 QA 返工。

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


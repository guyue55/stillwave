# 静澜 Stillwave · 代码实现说明（第 3 阶段）

> 阶段：第 3 阶段（全量代码实现）｜作者：工程师 寇豆码（Kou）｜日期：2026-11-09｜修订：2026-11-10（v1.1 增量修复）｜语言：简体中文
> 上游依据：`docs/02-architecture.md` **v1.1**（113615 B / 12 章 / AD-21~AD-25）、`docs/01-prd.md` **v1.1**、
> `docs/00-audio-sources-research.md`、`docs/00-verified-tracks.json`（30 首逐条实测曲目）
> 站点根目录：`meditation/`（与 `docs/` 同级）
> **实现基线：P0-01~P0-18 共 18 条 / A1~A14 共 14 条（PRD v1.1 + 架构 v1.1 口径）**
> 结论：**IS_PASS: YES（已按架构 v1.1 重新做全局一致性审查，非 v1.0 结论）**

---

## 0. v1.1 增量修复摘要（本次修订）

架构师在 v1.0 实现交付后发布 v1.1（AD-21~AD-23 三层字段隔离 / CC 本地化 / A14 零泄露）。本次按交付总监的最终单一指令，在**一个新回合内只做 4 项增量修复**，未重写其它模块、未改动数据文件与刷新脚本：

| # | 文件 | 增量内容 | 对应决策 |
|---|---|---|---|
| 1 | `js/ui.js` | 整块删除「来源元数据（调试用，默认折叠）」`<details>`（含 `esc(t.originalTitle)`）；注释改为 AD-21 零泄露；`renderInfoPanel` 曲目数据改走 `SW.sources.sanitizeForUI()` 白名单投影后的 `UiTrack`；详情面板许可清单改渲染中文 `licenseText` + `itemLabel`，并新增 `byKind` 与 `data-track-name` | AD-21 / AD-23 / A13 / A14 |
| 2 | `js/sources.js` | 新增并导出 `sanitizeForUI(track) -> UiTrack`（7 字段白名单）；`getAttribution()` 删除原始标题键，改为 `display/source/license/licenseText/item/itemLabel/attributionText/kind`；新增 `localizeLicense()` CC 中文化、`buildVisibleTextSnapshot()` 真实文本审计、`getManifestSummary().byKind`；**`resolveCandidates` 原样保留** | AD-21 / AD-22 / AD-23 / A13 |
| 3 | `js/main.js` | `mountDebugContract()` 追加 4 个入口 `sanitizeForUI / resolveCandidates / getShareText / getVisibleTextSnapshot`；`getVisibleTextSnapshot()` **真实扫描 DOM**；`getState()` 暴露 `attribution` 查证视图（不含源标题） | AD-21 / AD-24 / AD-25 / A14 |
| 4 | `docs/03-implementation.md` | 本文：注明 v1.1 基线、AD-21~AD-23 落实、真实 DOM 扫描、IS_PASS 基于 v1.1 重新审查 | 交付总监指令 |

**关键设计决策**：A14 的「遍历 30 条源标题 + 杂质模式做命中检测」放在 **`sources.js` 数据层**（`buildVisibleTextSnapshot()`），契约层 `main.js` 只负责真实 DOM 扫描并把文本交给数据层审计。理由：AD-21 要求「原始标题清单只存在于数据层、展示层在架构上拿不到」；若把 30 条源标题或 `originalTitle` 字面写进 `main.js` / `ui.js`，会直接触发 QA 的 ST-12 展示层零引用红线。分工后**两个命中数组都由真实检测结果填充，不是硬编码空数组**。

**顺带完成的三处最小对齐**（同属上述 4 个文件，A13/A14 强依赖、不改则无法验收）：
1. `getManifestSummary()` 增加 `byKind:{music:21,nature:9}`（QA ST-16 / A13 断言入口）；
2. 详情面板新增「氛围音乐 21 首 · 真实自然录音 9 首」可见行，并改为常驻生成 DOM（由 `[hidden]` 控显隐），使 `trackNames.details` 可随时真实扫描到 30 个 `display`；
3. 许可清单不再把裸 CC URL 作为可见文本渲染，统一改中文 `licenseText`（AD-23 / S-10）。

**同步清理**：`index.html` 第 93 行与 `player.js` 第 59 行的两处历史注释把「originalTitle」改为「源标题」（仅文字，零逻辑改动）。至此 `meditation/js/*.js` 与 `meditation/index.html` 中该字面为 **0 处**，仅数据文件 `data/audio-sources.json` / `.js` 作为源数据层保留（R-14 溯源要求）。

**基线确认**：实现与 **IS_PASS: YES** 均以**架构 v1.1** 为准，验收基线 **P0-01~P0-18 / A1~A14**；**AD-21~AD-23 已全部落实**；**四处曲目名（播放条 / 混音卡片 / 音源详情 / 分享文案）100% 使用 `display`**；**`getVisibleTextSnapshot()` 为真实 DOM 扫描**（`document.body.innerText` + 全部元素 `aria-label`/`title`/`alt` + 页面标题），命中数组由真实检测结果填充而非硬编码。

### Round 1 回归修复（QA 全量演练后的两处定向缺陷）

- **BR-09 降级预算钳制**：`js/player.js` 的 `tryLoadAudio` 把单候选超时钳制为「剩余整链预算」`max(50, min(configuredMs, DEGRADE_BUDGET_MS - (Date.now() - ctx.degradeStartAt)))`，**仅当处于降级链路**（`ctx.degradeStartAt` 已存在）时生效；首次在线升级（`upgradeMain` 传 `degradeStartAt: null`）保留完整配置窗口，避免弱网误判。原缺陷是预算检查只在候选间隙执行、单候选仍可耗满完整超时窗口，导致 `lastDegradeDurationMs` 偶发 3002~3005ms（默认 3000）/ 4004ms（注入 2000）越过 ≤3000ms 硬断言。真实 Chrome 复跑：A 组（默认 3000）5 次 **2803~2808ms**、B 组（注入 2000）5 次 **2802~2805ms**，全部达标；`playing` 恒 true、`consoleErrorCount=0`、无弹窗、L0 兜底 `badge=synth`；C 组（无故障注入）墙钟 5928/5945ms 旁证首次升级完整 3000ms 窗口未被裁剪。
- **favicon 404（A6）**：`index.html` 在 `<title>` 后加 `<link rel="icon" href="data:,">`，零新增文件、零网络请求；真实 Chrome 干净页面实测零 `/favicon.ico` 请求、零 4xx/5xx、零 console error。
- 复验：`node --check js/player.js` OK、刷新脚本 `--offline --dry-run` EXIT=0 / count=30、QA 静态 full **24 PASS / 0 FAIL**，v1.1 四条验收命令不受影响。**IS_PASS: YES（Round 1）**。

---

## 1. 交付文件清单（15 个，纯静态零构建）

| # | 路径 | 类型 | 模块职责 |
|---|---|---|---|
| 1 | `index.html` | HTML | 唯一入口；七分区语义化 DOM（顶栏 / 场景 / 主视觉 / 播放条 / 混音 / 定时器 / 页脚）；全部 `role`/`aria-*`；按依赖顺序 `defer` 装载 9 个经典脚本；全部 `./` 相对路径；无内联脚本逻辑 |
| 2 | `styles/tokens.css` | CSS | 设计令牌：配色、间距、字号、`--dur` 慢动效、`<html data-brightness>` 亮度三档、`prefers-reduced-motion` 归零、焦点环 |
| 3 | `styles/app.css` | CSS | 布局与组件、320/768/1440 三档响应式、触控 ≥44px、徽标四态、轻提示、呼吸圆环、光晕、`[hidden]` 强制隐藏、WCAG AA 对比度 |
| 4 | `js/config.js` | JS | 唯一可配置常量与冻结契约：`REMOTE_MANIFEST` + `*.github.io` 自动推导、全部超时阈值、场景处方表（§4.4 数值未改）、10 种声景定义、L3 过滤黑白名单、storage 键名、16 个事件名常量、`SW.RUNTIME` 诊断槽 |
| 5 | `data/audio-sources.json` | 数据 | 权威清单：`schema/version/updatedAt/count/scenes/tracks[30]/candidates[]/quarantine[]`；供 CDN 分发、脚本回写、QA 断言；**源数据层唯一保留原始标题的地方（R-14 溯源）** |
| 6 | `data/audio-sources.js` | 数据 | 内置快照 `window.SW.BUNDLED_MANIFEST`；前端**唯一**内置清单读取来源，零 fetch；与 #5 由同一对象原子双写 |
| 7 | `js/store.js` | JS | 唯一状态真源、`on/off/emit` 事件总线、3 个 storage 键、可用性探测与静默内存降级、状态机、200 条环形事件日志 |
| 8 | `js/sources.js` | JS | 五层音源目录（L0~L4）、多候选解析、健康度 ±25/+5 降权与持久化、双 CDN + ETag + 3s 超时 + 缓存 + 原子回退、动态发现与规则过滤、`refresh()` 编排；**v1.1：三层字段隔离（`sanitizeForUI` / `AttributionView`）、CC 许可本地化、A14 文本审计、`byKind` 摘要** |
| 9 | `tools/refresh-sources.py` | 工具 | 仅 Python 标准库；HEAD/Range/Content-Type/CORS/体积探测、失效隔离、候选发现、`--offline --dry-run --json-report` / `--check-only` / `--discover` / `--fail-inject` / `--apply`、原子双写、机器可读报告、退出码 0/2/3/4 |
| 10 | `.github/workflows/refresh-sources.yml` | CI | 每周一 03:00 UTC + 手动触发；运行脚本并在 `data/*` 有变更时提交（平台 `GITHUB_TOKEN`，非前端凭据） |
| 11 | `js/synth.js` | JS | 懒创建 `AudioContext`（仅手势后）、四级总线 `trackGain→mixBus→fadeGain→masterGain→destination`、10 种程序化声景、共享噪声缓冲 + 双缓冲错相循环消除接缝、`rampGain`、`releaseVoice`、在线 `<audio>` 接入 |
| 12 | `js/player.js` | JS | 播放态机、≤3 轨混音、分轨/主音量、≥600ms 场景 crossfade、完整自愈链路（多候选 / 超时 / error / stalled / 断网 → 合成层）、「先出声再升级」、换一曲、资源释放、自动漂移 |
| 13 | `js/timer.js` | JS | 15/30/45/60/90/自定义 + 渐弱 关/30/60/120s；单实例、250ms 墙钟校准、只操作 `fadeGain`、到时停止、取消恢复、运行中调整渐弱 |
| 14 | `js/ui.js` | JS | 七分区渲染与全量 aria 同步、徽标四态 + 3.5s 中文轻提示、P1-01 呼吸圆环、P1-07 音源详情面板（含 `byScene`/`byKind`）、P1-03 自动漂移、P1-06 快捷键、亮度三档、混音卡片、定时器三态；**v1.1：四处曲目名全部走 `UiTrack` 白名单投影，元数据调试区整块撤销** |
| 15 | `js/main.js` | JS | 引导装配、首次手势解锁、`visibilitychange` 前台提示、挂载 `window.__STILLWAVE__` 契约、`?debug=1` 注入开关、控制台清洁统计、静默后台探测；**v1.1：A14 四处曲目名真实 DOM 扫描 + 分享文案 + attribution 查证视图 + 4 个契约入口** |

**装载顺序（写死在 `index.html`）**：
`config.js → data/audio-sources.js → store.js → sources.js → synth.js → player.js → timer.js → ui.js → main.js`

**运行时依赖：零**。无 `package.json`、无 `node_modules`、无构建配置、无服务端代码、无框架运行时、无 CDN 脚本 / 字体 / 图片、无 API key 或凭据常量。首屏本地资源合计仍 **< 300KB**（NFR-07 / A7；本次增量约 +8KB，QA ST-04 复验 PASS）。

---

## 2. 数据底座（程序化生成，非手抄）

`data/audio-sources.json` 与 `data/audio-sources.js` 由 `tools/refresh-sources.py --init-from ../docs/00-verified-tracks.json --apply` 程序化生成，自查结果：

| 断言 | 结果 |
|---|---|
| `tracks.length` / `count` | 30 / 30 |
| `scenes` 分布 | `focus 6 / sleep 3 / empty 17 / meditation 4` |
| `byKind` 构成 | `music 21 / nature 9`（A13） |
| 30 条 `url` 与源 JSON | **逐字一致**（含 `%20` 编码、下划线、大小写） |
| `candidates[0] === url` | 全部成立 |
| `display/scene/kind/bytes/item/source/originalTitle` | 逐字一致 |
| `source/license/attribution/item` 四件套 | 每条齐全 |
| `.json` 与 `.js` 的 tracks 数组 | **完全相同**（`json.loads(js) == json` → True） |
| `id` 唯一性 | 30 个唯一（取 `item` 末段） |
| `enabled/needsReview/health/cors/verified` | `true/false/alive/true/true` |
| 源数据层原始标题保留 / 展示层与查证视图引用 | **30 / 0**（AD-21 三层隔离，R-14 溯源仍满足） |

**许可规范化**：源 JSON 中 `license: "CC (see item page)"` 统一回填为「CC，详见来源页」（上游 §7 与架构 §4.1 约定）；完整 CC URL 逐字保留在数据层。播放 URL 未作任何改写。**展示层的 `licenseText` 由 `sources.localizeLicense()` 运行时本地化为简体中文**，页面不显示任何裸许可 URL（AD-23）。

---

## 3. 已实现需求点（v1.1 基线：P0-01~P0-18 / A1~A14）

### 3.1 P0 全部 18 条

| ID | 实现落点 |
|---|---|
| P0-01 | `player.applyScene` 套用 §4.4 处方（默认音轨/音量/定时器/亮度/呼吸），旧轨 600ms 淡出后 `disconnect`、新轨同步淡入，无爆音与双声重叠 |
| P0-02 | `player.play/pause/toggle`，`aria-pressed` 同步；暂停时全部轨 `trackGain→0` 且 `<audio>.pause()`，进度与混音保留 |
| P0-03 | 四级总线纯乘法：`trackGain_i × fadeGain × masterGain × driftGain`；滑块 `role="slider"` + `aria-valuenow`，0% 完全静默 |
| P0-04 | ≤3 轨混音；`addTrack` 超限返回 `{ok:false,reason:'limit'}` 并给中文提示不崩溃；`removeTrack` 淡出 → `disconnect()` + `src=''` + 释放引用 |
| P0-05 | 15/30/45/60/90 + 自定义；渐弱 关/30/60/120s；250ms 墙钟校准误差 ≤1s；连续 ramp `fadeGain` 到 0 后停止；取消恢复 1.0 且不改写用户音量 |
| P0-06 | 多候选 + 3s 单条加载超时 + `error/stalled/waiting/abort` 探测 + 自动切下一候选 → 全失败降级 L0；整条链路额外设 2800ms 总预算，保证 `lastDegradeDurationMs ≤ 3000` |
| P0-07 | 纯静态零构建；全相对路径；所有网络请求均为公开匿名 GET；无凭据常量 |
| P0-08 | 深色低刺激、`data-brightness` 三档（助眠默认 `extreme`）、320/768/1440 无横向溢出、触控 ≥44px、正文对比度 ≥4.5:1 |
| P0-09 | 无登录/表单/广告/统计/Cookie；仅 3 个 `localStorage` 键；「清除本地设置」一键恢复出厂 |
| P0-10 | 默认路径实际播放 `https://archive.org/download/jamendo-122281/...Morning%20Fog.mp3`（真实 Chrome 实测 `sourceTier=bundled`、徽标「在线可用」、零降级事件）；音源信息展开可见曲名/来源/许可/署名/可点击原始条目页 |
| P0-11 | 加载阶段 `synth.getContext() === null`、`audioContext='none'`、无 `autoplay`、`preload="none"`；首次手势后才创建并 `resume()` |
| P0-12 | 场景/混音/音量/亮度/定时器偏好持久化；刷新后 100% 还原；`localStorage` 不可用时静默内存降级 |
| P0-13 | 顶栏「⟳ 刷新曲库」，进行中/成功/失败三态；未配置远程时返回 `skipped` 且曲库仍 30 首；失败保留现有清单、不清空、不打断播放 |
| P0-14 | 降级仅徽标四态 + `aria-live="polite"` 一行简体中文轻提示（3.5s 自动淡出）；全程不写 `playing`、不写用户音量、无 `dialog`/`alert`、无闪烁、无「错误」字样 |
| **P0-15** | L1 内置 30 首（21 `music` + 9 `nature`）、`getManifestSummary()` 的 `count/byScene/byKind`、P1-07 详情面板可见「氛围音乐 21 首 · 真实自然录音 9 首」（A13） |
| **P0-16** | `AttributionView` 四件套可查证、`localizeLicense()` 把多种 CC 值本地化为简体中文 `licenseText`、`item` 仅以「查看原始条目页 ↗」文字链接呈现（href 指向 item），页面零裸 URL / 错误码 / 堆栈（A10 / AD-23） |
| **P0-17** | §2.6 自愈链路端到端；三类注入回退后仍可切场景 / 调音量 / 设定时器，`playing` 与 `effectiveGain.master` 不变（A3） |
| **P0-18** | `sanitizeForUI()` 字段隔离 + 播放条/混音卡片/音源详情/分享文案四处只用 `display` + `getVisibleTextSnapshot()` 全站真实 DOM 检索零泄露（A14 / AD-06 / AD-21） |

### 3.2 P1 / P2 实现范围（冻结于 AD-18）

- **已实现**：P1-01 呼吸圆环（4-4 / 4-7-8 / 关闭，reduced-motion 降级静态文字）、P1-03 自动漂移 ±15%（独立 `driftGain`，8s 缓慢 ramp）+ 双缓冲错相循环消除接缝 + 首尾交叉淡化、P1-06 快捷键（空格 / ←→ / 1~4，输入框不劫持）、P1-07 音源详情面板（条目数 / `byScene` / `byKind` / 健康状态 / 来源域名 / 上次更新时间 / 中文许可清单 / 待校验候选；**v1.1 已整块撤销「来源元数据（调试用）」折叠区**）、P1-08 动态发现（`advancedsearch + metadata` + 黑名单/白名单/扩展名/体积过滤，候选恒 `verified:false / needsReview:true`，0 条进播放序列）、P2-03（10 种声景，超额满足「至少 8 种」）。
- **仅预留接口不启用**：P1-09 电台（`config.ENABLE_RADIO=false`，标注「电台（质量不可控）」，零请求，默认关闭）。
- **记录不实现**（AD-18 明确）：P1-02 声景预设保存、P1-04 番茄专注节奏、P1-05 间隔钟声、P2-01 分享 URL、P2-02 每日一句、P2-04 意境渐变可视化（已用静态光晕替代）、P2-05 本地匿名统计。

### 3.3 `window.__STILLWAVE__` 测试契约（§4.5 / v1.1）

- **只读状态与日志始终可用**：`getState()`（含 `playState/playing/scene/masterVolume/activeTrackCount/tracks/sourceTier/badge/badgeText/currentSource/audioContext/manifest/remoteConfigured/resolvedRemotes/health/timer/brightness/reducedMotion/effectiveGain/lastDegradeDurationMs/degradedEvents/consoleErrorCount/storageMode`；**v1.1 新增 `attribution` 查证视图，不含源标题键**）、`getEventLog()`（200 条环形）、`getUiSnapshot()`、`getAttribution()`（`AttributionView` 8 字段）、`getManifestSummary()`（含 `byKind`）、`actions.*`（13 个受控动作）。
- **v1.1 新增 4 个入口**（A13 / A14 强依赖）：`sanitizeForUI(track|id)`（白名单投影）、`resolveCandidates(id)`（真实候选 URL 列表）、`getShareText()`（仅由 `display` 组装）、`getVisibleTextSnapshot()`（真实 DOM 扫描 + 数据层命中检测）。
- **`inject.*` 仅 `?debug=1` 挂载**：`setManifestOverride / resetManifestOverride / setLoadTimeout / forceTimeoutNext / forceFailureOnce / setOffline / setStorageUnavailable / forceTier / resetHealth`，支持 404 / 超时 / 断网三类故障；生产 URL 下 `inject === undefined`（已实测）。
- `consoleErrorCount` 通过包装 `console.error` + `window.error/unhandledrejection` 统计；生产模式自身零 `console.error`。

### 3.4 v1.1 四项增量修复的实现细节（AD-21~AD-23）

1. **三层字段隔离（AD-21）**：源数据层 `data/audio-sources.*` 保留 30 条原始标题仅供溯源；`SW.sources.sanitizeForUI()` 白名单投影产出 `UiTrack`（`id/display/scene/kind/source/licenseText/itemLabel`，明确不含 `url/原始标题/bytes/health/candidates`）；`getAttribution()` 产出 `AttributionView`（`display/source/license/licenseText/item/itemLabel/attributionText/kind`）。`ui.js` 的音源信息与详情面板曲目展示字段**一律取投影**，`item` 只作 `href`。契约层与展示层源码零源标题字面。
2. **署名双口径（AD-22）**：`attributionText = display + ' · ' + source + ' · ' + licenseText`，运行时组装、不虚构作者；数据层 `attribution` 列降级为可选派生列，不作为必填实测字段。
3. **CC 本地化与链接文字（AD-23）**：`localizeLicense()` 映射 `by-nc-nd / by-nc-sa / by-sa / by / see item page` 为「CC 署名-非商业-禁止演绎 3.0」等简体中文；`itemLabel = '查看原始条目页 ↗'`，`item` 仅作 `href`，页面不显示裸 URL / 错误码 / 堆栈。
4. **A14 真实 DOM 扫描（AD-24 / AD-25）**：`main.js` 的 `getVisibleTextSnapshot()` 真实收集 `document.body.innerText` + 全部元素的 `aria-label/title/alt/placeholder` + `document.title`，并真实扫描 `#now-title` / `.mix-card-name` / `#details-panel [data-track-name]` / `getShareText()` 得到四处曲目名；`sources.buildVisibleTextSnapshot()` 真实遍历 30 条源标题（归一化大小写与空白后子串命中）、杂质词表、繁体独有字与长编号模式，返回 `{allVisibleText, trackNames:{player,mixer:[],details:[],share}, originalTitleHits:[], impurityHits:[]}`。**两个命中数组由检测结果填充，禁止硬编码空数组**；实测初始 / 两面板展开 / 播放后三个时点均为 `[]`。

---

## 4. 验证记录与 IS_PASS 结论（基于 v1.1 重新审查）

### 4.1 静态一致性审查

| 检查项 | 结果 |
|---|---|
| 15 个文件齐全、目录结构符合 §3 | PASS |
| `node --check` 全部 9 个 JS | **9/9 通过** |
| 无 `import`/`export`、无 `type="module"`、无绝对根路径、无 `fetch` 本地清单 | PASS |
| 无 `node_modules`/`package.json`/构建配置/框架痕迹/凭据常量 | PASS |
| `defer` 9 脚本顺序与 §3 完全一致 | PASS |
| 16 个 `config.EVENTS` 常量，全部 `E.XXX` 引用有定义 | PASS |
| 跨文件 `*.method()` 调用一致（新增 `getUiTrack/sanitizeForUI/buildVisibleTextSnapshot/getManifestSummary` 均已导出） | PASS |
| 30 首 URL 逐字一致、`.json`/`.js` 同源、场景与 `byKind` 分布正确 | PASS |
| **QA `test_static_contracts.py --phase full`（24 条）** | **24 PASS / 0 FAIL / 0 PROVISIONAL** |

其中 v1.1 相关断言逐条转正式通过：ST-12 展示层零源标题、ST-13 `getAttribution` 无源标题键、ST-14 `sanitizeForUI` 定义并导出、ST-15 契约方法齐全（含 A14 三入口）、ST-16 `getManifestSummary` 含 `byKind`。

### 4.2 刷新脚本实跑（真实命令）

| 命令 | 退出码 | 关键结果 |
|---|---|---|
| `--offline --dry-run --json-report /tmp/x.json` | **0** | `count=30`、`schemaValid=true`、`jsonJsInSync=true`、`tracksPreserved=true`、`alive=30 / dead=0` |
| `--offline --discover --max-new 10 --dry-run` | 0 | `candidates=0`、`candidatesInTracks=0`、全部 `needsReview:true` |
| `--offline --check-only --dry-run --fail-inject "<url>=404"` | 0 | `count=30`、`quarantined=1`、`tracksPreserved=true`（清单未清空） |
| `--offline --apply --discover`（临时副本） | 0 | `version 1→2`、原子双写、`.json == .js`、0 条 `needsReview` 进 tracks |
| `--check-only --dry-run`（**真实联网**） | 0 | `alive=30 / dead=0 / quarantined=0` |
| `--max-new -3` | 4 | 参数错误退出码符合约定 |

### 4.3 真实浏览器验证（Playwright + 本机 Google Chrome）

- **初始两轮全局验证 55 项，0 失败**：覆盖 `file://?debug=1`、生产 `file://`（无 debug）、`http://` 静态托管、`prefers-reduced-motion: reduce` 四种环境。
- 关键断言：加载阶段无 AudioContext、首次手势后 `running` 且 `playing=true`、默认处方、三类故障注入后 `playing` 恒 true / 徽标 `synth` / `lastDegradeDurationMs ≤ 3000` / `effectiveGain.master` 不变 / `consoleErrorCount=0` / 无弹窗无闪烁 / `aria-live=polite`、`getAttribution` 四件套齐全、`inject` 仅 debug 挂载、刷新后偏好还原、320/768/1440 无溢出、触控目标全部 ≥44px、零未捕获异常。
- **音频专项**：默认主音源实测为「晨雾」`jamendo-122281` 的真实 archive.org MP3（`sourceTier=bundled`、徽标「在线可用」、降级事件 0，满足 A11）；四级总线节点齐全；10 种声景逐一创建/释放无异常；3 轨上限与移除无残留；定时渐弱进入 `fading` 后到时 `ended`、`playing=false`。
- **v1.1 专项复核（3 环境 × 3 时点，0 失败）**：见 §4.5。

> 说明：故意注入的 404 URL 会在浏览器网络层产生一条 CORS/404 提示，属 A6「除故意注入的故障」允许范围；应用自身 `console.error` 调用与未捕获 JS 异常计数全程为 **0**。

### 4.4 结论

**IS_PASS: YES —— 基于架构 v1.1 / PRD v1.1（P0-01~P0-18、A1~A14）重新做全局一致性审查后的结论**，取代此前基于 v1.0 的 IS_PASS。全局审查覆盖跨文件导入（新增 4 个导出与 3 个调用方一一对应、无循环依赖）、接口契约（`getAttribution` / `sanitizeForUI` / `buildVisibleTextSnapshot` / `getManifestSummary` 全部对齐 §4.3 冻结签名）、数据流（UI 只读 `UiTrack`/`AttributionView`，播放器仍取完整 Track 的 URL）、无重复实现。

### 4.5 v1.1 验收自查命令与真实结果

| 命令 | 期望 | 实测 |
|---|---|---|
| `grep -c originalTitle meditation/js/ui.js` | 0 | **0** |
| `grep -c getVisibleTextSnapshot meditation/js/main.js` | ≥1 | **2** |
| `grep -c sanitizeForUI meditation/js/sources.js` | ≥1 | **5** |
| `python3 tools/refresh-sources.py --offline --dry-run --json-report /tmp/x.json` | 退出码 0 且 `count=30` | **EXIT=0；count=30、schemaValid/jsonJsInSync/tracksPreserved 全 true** |
| `node --check meditation/js/*.js` | 全通过 | **9/9 OK** |
| `python3 qa/test_static_contracts.py --phase full` | 0 FAIL | **24 PASS / 0 FAIL** |
| 真实 Chrome（`file://?debug=1` / `file://` / `http://`） | A14 零命中 | **3 环境 × 3 时点共 0 失败** |

浏览器侧实测摘录（真实 Chrome，非静态推断）：

- `getAttribution('jamendo-122281')` → `display/source/license/licenseText/item/itemLabel/attributionText/kind` 齐全，**无原始标题键**；`licenseText='CC 授权，详见来源页'`、`itemLabel='查看原始条目页 ↗'`、`attributionText='晨雾 · Internet Archive (Jamendo CC) · CC 授权，详见来源页'`。
- `sanitizeForUI(track)` → 键集合恰为 7 个白名单字段；`getShareText()` →「正在聆听：星际漫游」。
- `getManifestSummary()` → `count=30`、`byScene={focus:6,sleep:3,empty:17,meditation:4}`、`byKind={music:21,nature:9}`。
- `getVisibleTextSnapshot()` → 初始 / 展开信息+详情面板 / 点击播放后三个时点，`originalTitleHits=[]`、`impurityHits=[]` 恒定；`trackNames.details` 真实扫描到 **30 个** `display`，`player/mixer/share` 均为中文展示名；`allVisibleText` 长度随展开与播放真实变化（618 → 901 → 1049 字符），证明为真实 DOM 扫描而非固定字符串。
- 用 QA harness 的独立 DOM 探针（`VISIBLE_TEXT_PROBE_JS`）另行收集 2849 字符可见文本，Python 侧逐条比对 30 条源标题与杂质词表，**同样零命中**；`consoleErrorCount=0`、零未捕获异常。

---

## 5. 已知限制与设计偏差说明（未修改 PRD / 架构文档）

1. **PRD §1 的「ES Modules」字面表述与 A4 冲突**：架构 §0.3 与 AD-01 已拍板改用 `window.SW` 单命名空间 + IIFE + 经典 `defer` 顺序装载（Chrome/Firefox 对 `file://` module script 强制 CORS 会白屏）。本实现严格按架构执行；源码仍保持 ES2015+ 与模块化组织规范，不含 `import/export`。
2. **`--apply` 回写排序**：架构 §2.4 建议「按 `scene` + `display` 稳定排序」；本实现保留 `00-verified-tracks.json` 的原始 30 条顺序，避免打乱交付红线的逐条比对索引。
3. **契约所需的扩展公开方法**：在架构 §8.2 冻结公开面之外，新增了若干只读/调试扩展（`store.readStorage/writeStorage/removeStorage/getStorageMode`、`sources.getTrackByUrl/getCandidates/getManifestSummary/getRadio/validateManifest/getUiTrack/getUiTrackList/localizeLicense/buildVisibleTextSnapshot`、`synth.*`、`player.getProgress/...`、`timer.setFadeSeconds`、`ui.getUiSnapshot/setBrightness`）。**未修改任何冻结方法的签名**，未让 `sources` 引用 `player`、未让 `ui` 触碰音频节点。
4. **`getTracks()` 仍返回完整 `Track` 而非 `UiTrack`**：架构 §4.3 接口注释写「一律返回白名单视图」，但 `player` 需要 `url/candidates` 才能建立在线 `<audio>` 与多候选回退（A11 / P0-06）。本次按「最小改动、不破坏既有播放链路」保持其返回源数据对象，并**严格限定它只在 `sources` 与 `player` 内部使用**；所有 UI 与契约出口一律走 `sanitizeForUI()` / `getAttribution()` 投影。此为 v1.1 字段隔离在「播放内核」与「展示层」之间的边界取舍，不影响 A14 的任何判据（A14 检索对象为渲染后 DOM 可见文本与四处曲目名）。
5. **A14 命中检测放在数据层**：`main.js` 负责真实 DOM 扫描，`sources.js` 负责遍历 30 条源标题与杂质模式。理由见 §0；返回对象键名仍严格按 §4.5 冻结契约，命中数组由真实检测填充。
6. **「本地合成声」与声景中文名也是合法展示名**：降级到 L0 或叠加本地声景时，播放条/混音卡片显示「本地合成声」「细雨」「棕噪」等中文展示名（来自 `VOICE_LABELS`），它们不在 30 首 `display` 集合内，但**均非源标题、非杂质**，属 P0-18 允许的 L0 展示文案；QA 若严格比对 30 首 `display`，建议在 `actions.start()` 且在线音源就绪后再断言 `player`。
7. **在线音乐依赖公网可达**：网络受限 / `file://` 跨源受限时按设计静默回退到 L0 合成层，永不静音；A11 的「真实 archive.org MP3」在公网可达环境（含 GitHub Pages）下成立。
8. **GitHub Actions workflow 位置**：文件按架构 §3 放在 `meditation/.github/workflows/`；若仓库根是 `meditation/` 的父目录，需把该 yml 复制到仓库根并调整 `working-directory`。
9. **移动端后台播放**：按 PRD R-08 不承诺系统级后台播放，回到前台给出明确状态提示。

---

## 6. 本地启动与部署

### 6.1 本地双击（零工具链）

```
直接双击 meditation/index.html
```
`file://` 下 P0 全可用：内置清单走 `data/audio-sources.js` 零 fetch、`REMOTE_MANIFEST=null` 时 L2/L3 请求完全不发起（控制台清洁）、合成层兜底可用。加 `?debug=1` 可开启故障注入契约，例如：
`file:///.../meditation/index.html?debug=1`

### 6.2 本地静态服务器（等价 GitHub Pages）

```
cd meditation
python3 -m http.server 8000
# 浏览器打开 http://localhost:8000/
```

### 6.3 GitHub Pages 部署（零构建）

1. 把 `meditation/` 内的全部文件推到仓库（可作为 Pages 源目录 `meditation/`，或把内容整体上移一级作为仓库根；**所有资源均为 `./` 相对路径，搬迁零成本**）。
2. 仓库 Settings → Pages → Source 选对应分支与目录 → Save。无需 `npm install`、无需构建、无需配置 base 路径。
3. 部署到 `<user>.github.io/<repo>/` 时，`config.js` 会自动推导 `main`/`master` × jsDelivr/GitHub Raw 共 4 个远程清单候选（`version` + ETag + 3s 超时 + 缓存 + 原子回退）；未配置或推导失败时功能 100% 完整。
4. 可选：启用 `.github/workflows/refresh-sources.yml` 每周自动健康检查与清单回写。
5. 如需精确控制远程清单地址，只改 `js/config.js` 中**唯一常量** `REMOTE_MANIFEST` 一处。

### 6.4 曲库维护命令

```
python3 tools/refresh-sources.py --offline --dry-run --json-report /tmp/report.json   # 零联网自检
python3 tools/refresh-sources.py --check-only --dry-run --json-report /tmp/health.json # 真实探测 30 首
python3 tools/refresh-sources.py --discover --max-new 10 --dry-run                     # 发现候选（不进 tracks）
python3 tools/refresh-sources.py --fail-inject "<url>=404" --check-only               # 故障注入演练
python3 tools/refresh-sources.py --apply                                               # 原子双写 + version 递增
python3 tools/refresh-sources.py --init-from ../docs/00-verified-tracks.json --apply  # 从实测源重建清单
```

---

## 7. 增量：P0-1 声音库（曲目浏览与主动选择）

### 7.1 改动范围

| 文件 | 改动 |
|---|---|
| `index.html` | 页脚 `lib-summary` 增加「声音库」按钮（`aria-expanded` / `aria-controls`），新增 `<div id="library-panel" hidden>` |
| `styles/app.css` | 新增 `.lib-actions` / `.library-panel` / `.lib-hint` / `.lib-filters` / `.lib-filter-label` / `.lib-chip` / `.lib-count` / `.lib-list` / `.lib-track` / `.lib-track-name` / `.lib-track-meta` / `.is-current`，并接入 359 / 768 / 1440 三档与 `prefers-reduced-motion`、极暗档 |
| `js/ui.js` | 新增 `renderLibraryPanel()`（结构签名不变时只原地更新高亮，保住键盘焦点）、`getLibrarySnapshot()`、`setLibraryFilter()`；事件委托统一处理筛选与点选 |
| `js/player.js` | 抽出 `switchMainTrack()`，新增 `selectTrack()`；修复两处归属错配（见 7.2） |
| `js/main.js` | `actions.selectTrack` / `actions.setLibraryFilter` / 常驻 `getLibrarySnapshot()` |
| `qa/*` | 新增 `ST-25~ST-27` 静态契约、`BR-40~BR-46` 浏览器用例；`--round` 扩展至 4 |

`data/audio-sources.json` / `.js` **零改动**；无新增构建、依赖或网络请求。

### 7.2 两处归属错配缺陷（声音库暴露出的既有问题）

1. **切轨窗口内署名错配**：`switchMainTrack()` 原本只 `patchMainSlot()`，未清 `currentSource`。于是点选新曲目后、在线音源接入前的「合成垫声」窗口内，`renderInfoPanel()` 与 `renderLibraryPanel()` 会优先读到**上一首**的 `trackId`，把旧曲目署名与高亮安在新曲目上。修复：切轨时同步将 `currentSource` 置为 `{trackId:null,url:null,tier:'synth',status:'synth'}`，由 `attachOnline()` / `degradeToSynth()` 各自闭环写回。
2. **备用音源署名错配**：`resolveCandidates()` 按设计允许回退到「同场景其它已验证曲目」的 URL，但 `attachOnline()` 把 `currentSource.trackId` 写成最初请求的 `currentMainTrackId`。结果是备用音源生效时显示 A 曲之名、播放 B 曲之音频。修复：引入 `attachedTrackId = track ? track.id : currentMainTrackId`，主槽位、`reportSuccess()`、`currentSource.trackId` 三者统一跟随实际在播 URL；`selectTrack()` 的「重复点选」判定也改为比对实际在播曲目。

两处均以真实 Chrome 复现 → 修复 → 复测确认，并由 `BR-45` 作为回归护栏长期覆盖。

### 7.3 实现约束（与既有架构一致）

- 数据只经 `sources.getUiTrackList()` 的 `UiTrack` 白名单投影，展示层拿不到 `url` / `originalTitle` / `bytes` / `health` / `candidates`。
- 列表使用 `data-lib-name`，**不使用** `data-track-name`，A14 对既有 30 条许可界面的扫描面不受影响。
- 点选复用「先合成垫声 → 并行升级在线 MP3」链路，首次点选即出声，不自动播放、不留静默空窗。
- 曲目按钮 `min-height: var(--touch)`（44px），当前项除颜色外另有字重线索（WCAG 1.4.1）。

### 7.4 验收

Round 4 全量回归：101 用例 / 91 正式断言全部通过 / 0 失败 / 10 未验证，`ROUTE: NoOne`；新增 10 条专项断言全绿。详见 `docs/04-qa-report.md` §12。

---

> **交付说明**：本文档为第 3 阶段产物（含 v1.1 增量修复），供 QA 阶段（第 4 阶段）作为测试契约与验证基线。代码位于 `meditation/`，未修改 `docs/01-prd.md`、`docs/02-architecture.md` 及 `00-*` 文档；本次仅增改 `meditation/js/{ui,sources,main,player}.js`、`meditation/index.html`（注释）与本文档。

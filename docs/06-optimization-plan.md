# 静澜 Stillwave 优化实施计划（P0 收口批）

> 文档编号：06-optimization-plan
> 制定时间：2026-11-13
> 依据：`docs/05-optimization-roadmap.md`（调研与路线）+ 对本仓库源码的二次核对
> 适用批次：P0-4a（缺陷）→ P0-2 → P0-3 → P0-4b，随后 P1-1
> 性质：本文件是**实施契约**。任何开发与验收都以本文件的「边界」「验收要点」「完成定义」为准。

---

## 1. 本文件的作用

`docs/05` 给的是「做什么、为什么」。本文件回答「**怎么做、做到什么程度算完成、什么绝对不能做**」。

制定本文件时执行了三件事，以确保不是照抄文档：

1. **逐条回到源码核对** `docs/05` 的事实性主张（第 2 节），凡结论与源码不符的当场修正；
2. **用可计算的证据**核实无障碍主张（对比度实算，见 §6.1），而不是凭观感判断；
3. 明确列出**非目标**（第 4 节），防止范围蔓延把冥想站做成播放器/调音台。

---

## 2. 事实基线：二次核对结果

核对方法：只读 `meditation/` 与 `stillwave/` 源码 + `git show/diff` + Python 实算。核对时间 2026-11-13。

| # | `docs/05` 的主张 | 核对方法 | 核对结论 | 处理 |
|---|---|---|---|---|
| F-1 | 声音库实现只在 `meditation/`，`stillwave/` 尚无，存在目录分叉 | `grep -c` 两目录的 `data-lib-name` / `renderLibraryPanel` / `selectTrack`；逐文件 `cmp` | **已过时**。`stillwave/` 已含声音库（ui.js 命中 7 处、player.js 3 处）；两份目录 7 个关键文件**逐字节相同**，分叉已消除 | 该风险项关闭，无需动作 |
| F-2 | P0-1「未改动 `data/audio-sources.*`」未经版本库确证 | `git diff --name-only 4d4eeab 23a9529 -- data/` | **证实为真**：输出为空，`data/` 零改动；提交共改 14 个文件 | 该「未确证」项关闭 |
| F-3 | `store.js` 具备 `readStorage / writeStorage / collectPrefs / savePrefs / loadPrefs / clearAll / storageUsable`，可复用 | 读 `js/store.js` 第 54–114、178–235 行 | **证实**，且 `SW.store` 已导出 `readStorage/writeStorage/removeStorage/getStorageMode`（第 249–252 行） | P0-2 直接复用，不新建存储层 |
| F-4 | 存储键集中在 `STORAGE_KEYS` | 读 `js/config.js` 第 99–103、220 行 | **证实**：`{prefs,health,manifest}` 三键，且第 220 行 `Object.freeze` | 新键必须在 freeze **之前**加入 |
| F-5 | `clearAll()` 会一并清除新增键 | 读 `js/store.js` 第 219–235 行 | **不成立**：`clearAll()` 只 `removeStorage` 三键 + 清空内存 Map。新键若不显式加入，会出现「点了清除本地设置但收藏还在」 | **必须**同步扩展 `clearAll()`，并列入验收 |
| F-6 | 预设可直接复用 `applyScene()` 还原混音 | 读 `js/player.js` 第 508–560 行 | **不成立**：`applyScene()` 一律用场景处方**覆盖** `tracks / masterVolume / brightness / breath`，会冲掉自定义混音 | 预设还原必须在 `applyScene()` **之后**再叠加，或改用新增的 `applyMix()` |
| F-7 | 分享链接可「还原同一混音」 | 读 `js/player.js` 第 416–460 行 | **需限定语义**：`startFromGesture()` 会用 `buildSceneSlots()` 重建槽位，`AudioContext` 又必须在用户手势后创建。因此「打开链接即还原混音并出声」**不可能也不允许**（违反禁自动播放） | 分享语义定为「**还原配置，首次点击播放时生效**」，并通过 pending 机制落到 `startFromGesture` 内 |
| F-8 | 现有焦点环满足 3:1 | 读 `styles/tokens.css` 第 110–114 行 + 实算 | **证实**：`#9bc2ba` 在 `#0e1418` 为 9.56:1，在 `#172128` 为 8.42:1 | 保持不动 |
| F-9 | 现有正文/次级文字满足 4.5:1 | Python 实算对比度 | **部分不成立**：`--c-text-3` `#6d807c` 在 `#0e1418` 仅 **4.44:1**、在 `#172128` 仅 **3.91:1**。而上一轮新增的 `.lib-track-meta / .lib-filter-label / .lib-count` 正好用它 | **列为 P0-4a 缺陷先行修复**（§6.1） |
| F-10 | 目前没有 hash 解析、没有 Escape 关闭面板 | `grep -r "location.hash\|hashchange\|URLSearchParams" js/`；`grep "'Escape'" js/ui.js` | **证实**：两者均无命中，属全新实现 | P0-3 / P0-4b 无历史包袱，也无迁移风险 |
| F-11 | `addTrack()` 可用于还原预设音轨 | 读 `js/player.js` 第 580–598 行 | **需注意**：返回 `{ok,id}` 或 `{ok:false,reason:'limit'}`，槽位音量**固定 0.30**，上限 `MAX_TRACKS=3`，`id` 由时间戳生成 | 还原时必须先 `addTrack` 再 `setTrackVolume` 覆盖音量 |
| F-12 | 30 首曲库场景/类型分布 | 读 `data/audio-sources.json` + 浏览器实测 | **证实**：focus 6 / sleep 3 / empty 17 / meditation 4；music 21 / nature 9 | 作为 P1-1 搜索的基线断言 |

**结论**：路线图中的 F-1、F-2 已关闭；F-5、F-6、F-7、F-9 是必须修正的设计前提，已进入本计划的验收项。

---

## 3. 硬边界（不可协商，任一违反即回滚）

1. **纯静态**：无构建步骤、无框架、无 ES Module、无 API key、无后端、无数据库、无新外部服务。
2. **`file://` 双击可开**：不得出现因 `fetch` / module / localStorage 抛错导致的白屏。
3. **禁自动播放**：`AudioContext` 只能在用户手势后创建；任何「打开链接/刷新页面就出声」都禁止。
4. **零新增网络请求**：本批次所有功能只用内存清单与 `localStorage`，不得新增 `fetch` / `XMLHttpRequest`。
5. **不改音源清单**：`data/audio-sources.json` / `.js` 本批次零改动。
6. **A14 零泄露**：新增 UI 不得渲染 `originalTitle`、裸 URL、错误码；不得新增 `data-track-name`（该属性专供 30 条许可清单扫描）。
7. **低刺激**：不得引入封面墙、推荐流、弹窗、自动播放、频谱动画、调音台式面板。
8. **无障碍基线**：正文 ≥4.5:1、控件与焦点环 ≥3:1、键盘全可达、焦点可见、`prefers-reduced-motion` 下无展开动效。
9. **隐私**：新增持久化与 URL 只含「曲目 id / 声景 id / 音量 / 场景」，不含任何可识别个人信息；hash 内容**不得**经 `innerHTML` 注入。

---

## 4. 明确非目标（本批次不做）

| 不做 | 理由 |
|---|---|
| 账号、云同步、跨设备 | 与「无后端」硬冲突；用导出/导入（P2-2）替代 |
| 10 段 EQ / 声像 / 精细滤波 | 会把低刺激站点变成调音台，且相位/梳状滤波风险无实测依据 |
| 提升混音轨数上限（现 ≤3） | 多轨叠加易成噪音墙，且抬升移动端 CPU |
| 运行时接 Freesound / Jamendo API | 需密钥，硬违反边界 |
| 电台流默认开启 | 内容不可控（人声/广告/版权） |
| L3 动态发现结果直接入播 | 必须保持「只进候选 + 人工审核」纪律 |
| 自动播放、打开链接即出声 | 违反边界 3 |
| P1-2 扩库的人工策展 | 属独立维护批次，且需人工试听，不在本次代码批次内 |

---

## 5. 批次与顺序

每个子项独立开发、独立测试、独立门禁；**前一项不通过门禁，不进入下一项**。

| 顺序 | 子项 | 依赖 | 改动文件 | 门禁 |
|---|---|---|---|---|
| 1 | **P0-4a 对比度缺陷修正** | 无 | `styles/tokens.css`、`qa/test_static_contracts.py` | 全令牌对比度实算达标；静态契约全绿 |
| 2 | **P0-2 收藏 + 混音预设** | 1 | `js/config.js`、`js/store.js`、`js/ui.js`、`index.html`、`styles/app.css`、`qa/*` | 刷新保持、降级不崩、`clearAll` 清干净、A14 不受扰 |
| 3 | **P0-3 URL 分享状态** | 2 | `js/main.js`、`js/player.js`、`js/ui.js`、`index.html`、`qa/*` | 分享往返一致、非法 hash 安全回退、**零自动播放** |
| 4 | **P0-4b 键盘与焦点收口** | 2、3 | `js/ui.js`、`index.html`、`styles/app.css`、`qa/*` | Escape 关闭并归还焦点、Tab 序合理、对比度复验 |
| 5 | P1-1 轻量搜索 | 2 | 待定 | 本批次**只设计不实施**，见 §6.5 |

批次完成后统一：同步 `meditation/` → `stillwave/`、跑全量回归、推送、Pages 重建、线上复验。

---

## 6. 逐项设计

### 6.1 P0-4a 对比度缺陷修正（先行，最小改动）

**缺陷**：`--c-text-3: #6d807c` 在 `--c-surface (#172128)` 上仅 3.91:1、在 `--c-bg (#0e1418)` 上仅 4.44:1，均低于 WCAG AA 正文 4.5:1。使用点仅 3 处，全部是上一轮新增的声音库文案。

**修法**：改令牌单一来源，不动使用点。
- `--c-text-3: #6d807c` → `#82948f`
- 实算：在 `#172128` 上 **5.12:1**、`#1c272e` 上 **4.77:1**、`#0e1418` 上 **5.81:1**、极暗档 `#05080a` 上更高。全部达标且保留视觉层级（字号 13px 与 `--c-text` 15px 仍可区分）。

**新增防回归断言**（静态契约 `ST-28`）：在 QA 中用 Python 实算 `tokens.css` 中下列配对，任一低于阈值即失败：
- `--c-text` / `--c-text-2` / `--c-text-3` / `--c-primary-soft` 对 `--c-bg` 与 `--c-surface`：≥4.5
- `--c-primary` / `--c-primary-soft`（焦点环）对 `--c-bg` 与 `--c-surface`：≥3.0
- `--c-text-2` / `--c-text-3` 对极暗档 `--c-bg`：≥4.5

**验收**：脚本输出全部 PASS；断言在人为把 `--c-text-3` 改回 `#6d807c` 时会 FAIL（需现场验证脚本有效性，避免「假绿」）。

---

### 6.2 P0-2 收藏 + 自定义混音预设

#### 数据模型

新增两个存储键（`config.js` 第 99–103 行内、`Object.freeze` 之前）：

```
STORAGE_KEYS.favorites = 'sw.favorites.v1'
STORAGE_KEYS.presets   = 'sw.presets.v1'
```

结构（均带 `v` 以便未来迁移）：

```js
// sw.favorites.v1
{ v: 1, ids: ['jamendo-002032', 'aporee-xxxx'] }

// sw.presets.v1
{ v: 1, items: [{
    name: '深夜雨读',            // 1..24 字符，去首尾空白
    scene: 'focus',              // 必须 ∈ SCENE_IDS
    masterVolume: 0.7,           // 0..1，两位小数
    tracks: [                    // 1..3 条
      { kind: 'track', trackId: 'jamendo-002032', volume: 1.0 },
      { kind: 'voice', voice: 'rain',             volume: 0.22 }
    ]
  }] }
```

**只存 id / voice / volume / scene / masterVolume**，不存 `display`、不存 URL、不存时间戳以外任何元数据（时间戳留在内存排序用，不入库）。

#### 校验与降级（对齐边界 2、9）

| 场景 | 行为 |
|---|---|
| 键不存在 / JSON 解析失败 / 顶层非对象 | 返回空集合，不抛错 |
| `v` 不等于 1 | 忽略该键（未来迁移入口），不崩溃 |
| 收藏 id 不在当前清单白名单 | 读取时静默丢弃（曲目下线不会让面板报错） |
| 预设 `tracks` 为空 / >3 / 字段类型错 | 丢弃该条预设 |
| `volume` 越界 | 钳制到 0..1，保留两位小数 |
| `name` 超长 / 空白 / 含控制字符 | 截断至 24 字符、去空白；为空则丢弃 |
| `localStorage` 不可用 | 走 `writeStorage` 既有内存降级，**不报错、不白屏** |
| 预设数量超过 20 | 拒绝新增并轻提示「预设已满（20）」 |

#### `store.js` 变更

- 新增 `getFavorites() / toggleFavorite(trackId) / isFavorite(trackId)`
- 新增 `getPresets() / savePreset(name) / applyPreset(index) / deletePreset(index)`
- `collectPrefs()` **不**包含收藏与预设（避免与 `prefs` 键重复写、避免体积膨胀）
- `clearAll()` 必须追加 `removeStorage(K.favorites)` 与 `removeStorage(K.presets)`（修 F-5）
- 所有读写均包 `try/catch`，失败静默

#### UI 变更

- **收藏**：声音库每条曲目右侧新增星标按钮 `.lib-fav`，`aria-pressed` + `aria-label="收藏 <曲名>"`，44×44 触控区；星标用字符（★/☆）而非图片，不新增请求。
- **只看收藏**：在列表上方新增**独立**开关按钮 `#btn-fav-only`（`aria-pressed`），**不**并入现有 `.lib-chip` 分组——避免打乱 `BR-42` 对场景/类型 chip 数量的断言。
- **预设区**：页脚新增 `<div id="preset-panel" hidden>`，与 `library-panel` 同级；由 `#btn-presets` 切换（`aria-expanded` / `aria-controls`）。
  - 列表项：名称 + 「应用」「删除」两个按钮（均带 `aria-label`，含预设名以免同名声控混淆）。
  - 保存：**内联 `<input>` + 保存按钮**，禁止用 `prompt()`（`ST-23` 禁止 `alert/dialog/prompt`）。
  - 应用预设：无播放时提示「已载入预设，点击播放生效」；播放中则立即应用。

#### 与播放器的衔接（修 F-6）

新增 `player.applyMix(spec)`：
- 未启动：缓存为 `pendingMix`，返回 `{pending:true}`；
- 已启动：按序执行 `applyScene(spec.scene)` → `selectTrack(main)` → `removeTrack` 多余槽位 → `addTrack` 缺少的 voice → `setTrackVolume` 逐个覆盖 → `setMasterVolume`。

`startFromGesture()` 第 451–452 行处：若存在 `pendingMix`，改用其主音轨调用 `upgradeMain`，并在 `store.patch` 后应用混音，然后清空 `pendingMix`。
`applyScene()` **不修改**（避免影响既有 91 条断言）；预设应用一律在 `applyScene` 返回后叠加。

#### 验收要点

1. 收藏 3 首 → 刷新 → 仍是 3 首，星标状态一致。
2. 保存预设「A」→ 改变混音 → 应用「A」→ `state.tracks` 与保存时逐字段一致（音量误差 ≤0.01）。
3. 删除全部预设 → 刷新 → 预设列表为空。
4. 「清除本地设置」→ 收藏与预设同时清空且无残留键（读 `localStorage` 断言）。
5. `inject.setStorageUnavailable(true)` 后执行收藏/保存：不抛错、`storageMode==='memory'`、页面可用。
6. 收藏一首已下线曲目（通过 `inject.setManifestOverride` 模拟）→ 面板不报错、该条不显示或降级显示。
7. `getVisibleTextSnapshot().originalTitleHits` 仍为 `[]`（A14 不受扰）。

---

### 6.3 P0-3 URL 分享状态

#### 语义（关键决策，修 F-7）

- 分享链接 = **配置快照**，不是「自动播放」。
- 打开含 hash 的链接：**立即还原场景/音量/混音配置与界面**，但**不出声**；用户点击播放后按还原的配置发声。
- 反向：只有用户点「复制分享链接」时才写入 hash，**不随状态变化自动改写**（否则污染浏览器历史、违背低刺激）。

#### 编码格式

```
#sw=1&s=<scene>&mv=<0..100>&tr=<seg>|<seg>|<seg>
seg = t:<trackId>:<0..100>     // 在线曲目
    | v:<voiceId>:<0..100>     // 合成声景
```

示例：`#sw=1&s=empty&mv=80&tr=t:jamendo-002032:100|v:brown:30|v:rain:22`

设计理由：字段少、可人读、无 base64；`|` 与 `:` 在 URL 片段中合法；任一非法段可独立丢弃而不毁掉整条链接。

#### 防御性解析（对齐边界 9）

- 总长度 > 300 字符 → 整体忽略，回退默认。
- `sw !== '1'` → 忽略。
- `s` 不在 `SCENE_IDS` → 用当前场景。
- `mv` 非数字 → 忽略；数字则钳制 0..100 并 /100。
- 每个 seg：`t:` 的 id 必须命中清单白名单，`v:` 的 id 必须 ∈ `SYNTH_VOICES`，否则丢弃该段。
- 最多取前 3 段（`MAX_TRACKS`）。
- 全程 `try/catch`，解析失败一律回退默认，**绝不抛错、绝不白屏**。
- **禁止**把 hash 内容拼进 `innerHTML`；只允许经 `textContent` 或 `createElement` 使用。

#### 实现点

- `js/main.js`：`init()` 中新增 `restoreFromHash()`（在 `sources.init()` 之后、`ui.init()` 之前解析，保证白名单可用）；`hashchange` 监听器（节流 150ms）。
- `js/ui.js`：`#btn-share`（页脚，`aria-label="复制分享链接"`）→ 生成 hash → 复制 → toast；复制失败回退「选中只读输入框」。
- `js/player.js`：暴露 `getMixSpec()` 供生成 hash；`applyMix()` 复用 §6.2。
- 复制**不得**触发播放（`AudioContext` 状态前后都应为 `none`/`suspended`，测试断言）。

#### 验收要点

1. 配置「助眠 + 主音量 60% + 2 轨」→ 生成链接 → 新 context 打开 → 配置一致、`playing===false`、`AudioContext` 未运行。
2. 再点播放 → 生效的混音与链接一致（主音轨 trackId 与各槽音量）。
3. 非法 hash（`#sw=1&s=xxx&mv=999&tr=t:NOT_EXIST:50|v:zzz:50`）→ 回退默认、零 console 错误、页面可正常播放。
4. 超长 hash（>300 字符）→ 忽略、不崩溃。
5. hash 含 `<img src=x onerror=alert(1)>` → 不出现在 DOM 任何文本/属性中，无脚本执行。
6. `file://` 下分享与还原均可用。

---

### 6.4 P0-4b 键盘与焦点收口

- `Escape` 关闭当前打开的任一面板（`info-panel` / `library-panel` / `preset-panel` / `details-panel`），并把焦点**归还给对应触发按钮**。
- 四个面板的触发按钮 `aria-expanded` 与实际 `hidden` 严格同步（含 Escape 关闭路径）。
- 面板内 Tab 顺序为文档序，不出现 `tabindex` 正值。
- 新控件（`#btn-fav-only`、`.lib-fav`、`#btn-share`、`#btn-presets`、预设项按钮）全部：有可读 `aria-label`、触控区 ≥44px、`:focus-visible` 可见、`aria-pressed` 语义正确。
- `prefers-reduced-motion: reduce` 下新面板无展开/过渡动效。
- 复验对比度：新控件所用令牌组合全部达标（复用 `ST-28`）。

**验收**：键盘走查脚本 —— 从 `body` 起连续 Tab 至收藏按钮并 Enter 切换成功；Escape 后 `document.activeElement` 为打开该面板的按钮。

---

### 6.5 P1-1 轻量搜索（仅设计，本批次不实施）

- 在 `library-panel` 内新增 `<input type="search">`，对 `display` 做包含匹配（中文）+ 大小写不敏感。
- 输入节流 120ms；结果写入现有 `.lib-list`，沿用结构签名机制避免整表重建。
- **不得**搜索 `originalTitle`（A14 边界）。
- 依赖 P0-2 的收藏开关，二者可组合（搜索 ∩ 收藏 ∩ 场景 ∩ 类型）。

---

## 7. 横切设计

### 7.1 存储 schema 版本化

所有新键顶层带 `v: 1`。读取时 `v` 不匹配即视为空集合并忽略（不迁移、不猜），未来需要迁移时再写显式迁移函数。理由：静默猜测旧格式是数据损坏的主要来源。

### 7.2 错误处理统一策略

- 模块内 `try/catch` 吞掉异常，**不得** `console.error`（`ST-23` 静态断言禁止裸 `console.error`）。
- 用户可感知的失败走 `toast()`（`aria-live=polite`），不弹窗。
- 任何解析/还原失败都必须落到「默认可用状态」，不允许出现半初始化。

### 7.3 隐私

- 收藏、预设、hash 三类数据只含曲目/声景 id 与音量，不含时间戳以外的元数据，不含任何用户标识。
- 不新增埋点、不新增第三方请求。

---

## 8. 测试与验证矩阵

### 8.1 反幻觉取证要求（本批次的强制纪律）

任何「通过 / 已修复 / 无影响」的结论，必须附**可复现的一手证据**，不接受转述：

| 结论类型 | 最低证据标准 |
|---|---|
| 功能可用 | 真实浏览器（Playwright + 本机 Chrome）实跑，附断言输出 |
| 缺陷已修 | 修复前能复现（失败输出），修复后同一脚本通过 |
| 无障碍达标 | 对比度用脚本实算数值，不引用观感 |
| 断言有效 | 人为注入缺陷后断言必须变红（防「假绿」），随后还原 |
| 未改动某文件 | `git diff --name-only` / `cmp` 输出 |
| 静态约束 | 静态契约断言，且断言本身先经注入验证有效 |

### 8.2 用例规划

| 子项 | 静态契约 | 浏览器用例 |
|---|---|---|
| P0-4a | `ST-28` 令牌对比度（含注入验证） | — |
| P0-2 | `ST-29` 存储键与 `clearAll` 覆盖、无 `prompt/alert`、收藏不含 `originalTitle` | `BR-50` 收藏往返；`BR-51` 预设保存/应用一致性；`BR-52` 存储不可用降级；`BR-53` `clearAll` 彻底性 |
| P0-3 | `ST-30` hash 解析无 `innerHTML`、白名单校验存在 | `BR-54` 分享往返一致；`BR-55` 非法/超长/XSS hash 安全回退；`BR-56` 复制不触发播放 |
| P0-4b | `ST-31` 新控件 `aria-label` 与 `aria-expanded` 齐全 | `BR-57` Escape 关闭并归还焦点；`BR-58` 键盘全可达 |

### 8.3 门禁

每个子项完成后必须同时满足：
1. 新增用例全 PASS；
2. **既有 91 条正式断言零回归**（尤其 `BR-15/A14`、`BR-42` 声音库筛选计数、`BR-45` 点选收敛）；
3. 无 `__pycache__` / `.pyc` 污染（`ST-01` 会因文件计数失败）。

---

## 9. 风险登记与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 新面板破坏 `BR-42`（chip 计数） | 既有断言误红 | 「只看收藏」用独立按钮，不并入 `.lib-chip` 组 |
| `applyScene` 覆盖混音 | 预设应用后配置被冲掉 | 一律在 `applyScene` 返回后叠加；不改 `applyScene` 本身 |
| 分享 hash 被当成自动播放 | 违反硬边界 3 | `pendingMix` 机制 + `BR-54` 断言 `playing===false` |
| `localStorage` 配额/隐私模式 | 写入抛错、白屏 | 复用 `writeStorage` 内存降级；预设上限 20 条、名称 ≤24 字符 |
| `clearAll` 漏清新键 | 用户信任受损 | 显式加入 + `BR-53` 直接读 `localStorage` 断言键不存在 |
| 新 UI 引入 A14 泄露 | 既有闸门失败 | 复用 `UiTrack` 白名单与 `textContent`；`BR-15` 回归 |
| archive.org 抖动导致点选用例误红 | 门禁不可用 | 沿用 `BR-45` 的「三种自洽终态」判定口径 |
| 一次改太多难以定位 | 缺陷难归因 | 严格按 §5 顺序，单项单项过门禁 |

---

## 10. 回滚策略

- 每个子项独立提交，提交信息标明子项编号；任一子项线上异常可单独 `git revert` 该提交而不牵连其它。
- `data/` 本批次不动，因此**曲库层无需回滚**。
- 新增存储键均为可选：即使回滚代码，旧键残留也不会导致旧版本报错（旧代码不读这些键）。

---

## 11. 完成定义（DoD）

一个子项只有同时满足以下 6 条才算完成：

1. 代码改动仅限 §5 声明的文件；
2. §6 对应该子项的「验收要点」逐条有实测证据；
3. 新增断言 PASS，且断言经「注入缺陷 → 变红 → 还原」有效性验证；
4. 既有 91 条正式断言零回归；
5. 文档同步：`CHANGELOG.md` + `docs/03-implementation.md` + `docs/04-qa-report.md`；
6. `meditation/` 与 `stillwave/` 逐字节一致，且 `git status` 干净。

---

## 12. 附：本批次不做但已记录的技术债

- `loadPrefs()` 目前不还原 `prefs.tracks`（第 208 行注释说明「仅作展示还原」），实际连展示都未还原。属既有行为，本批次不改，记录在此以免误判为新缺陷。
- `collectPrefs()` 把 `display` 写入 `prefs`（派生字段入持久化），体积与一致性上不理想，待 P2-2 导出/导入时统一收敛。

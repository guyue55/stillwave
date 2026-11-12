# 静澜 Stillwave

> 让心，慢下来。一个纯静态、零依赖、零追踪的中文冥想与声景网站。

**在线体验：<https://guyue55.github.io/stillwave/>**

---

## 这是什么

静澜是一个打开就能用的声景播放器：选一个场景（学习 / 助眠 / 放空 / 冥想），按下播放，剩下的交给它。
它不是音乐平台的网页版，而是一个刻意做「减法」的低刺激空间 —— 没有账号、没有推荐流、没有广告、没有统计脚本，也没有必须联网才能出声的依赖。

核心设计目标有两条：

1. **永远有声音。** 浏览器本地实时合成的声景是永不失效的底座；在线曲目只是「更好听的升级」，加载失败会静默自愈，不会打断、不弹窗、不改你的音量。
2. **以后也不会失效。** 曲库不是硬编码完就丢在那里，而是有一套可自动健康检查、动态发现、隔离失效、恢复复用的更新机制（见下文「曲库如何长期不失效」）。

> 适用许可提示：站点代码为 MIT，但在线音频为第三方 CC 授权作品，**仅限个人非商业使用**，详见 [NOTICE.md](./NOTICE.md)。

---

## 主要特性

| 能力 | 说明 |
|---|---|
| 四场景处方 | 学习 / 助眠 / 放空 / 冥想，各自预置主音源、叠加声景、音量、亮度、定时器与呼吸引导 |
| 30 首实测曲库 | 21 首 Jamendo CC 氛围音乐 + 9 首 aporee 真实自然录音；每一首都逐条验证过 HTTP 206、`audio/*`、`Access-Control-Allow-Origin: *`，并在真实浏览器中确认可取得时长 |
| 声音库（浏览 / 筛选 / 点选） | 页脚「声音库」面板列出全部 30 首已验证曲目，按场景与类型筛选，点选任意一首即设为当前主音源；首次点选即出声 |
| 10 种程序化声景 | 白噪 / 粉噪 / 棕噪 / 细雨 / 溪流 / 风 / 海浪 / 颂钵 / 篝火 / 林风，全部 Web Audio 本地合成，零网络依赖 |
| 最多 3 轨混音 | 主音源 + 叠加声景自由组合，独立音量，600ms 平滑过渡，自动漂移 ±15% 避免听觉疲劳 |
| 睡眠定时 | 15 / 30 / 45 / 60 / 90 分钟或自定义，可选 30 / 60 / 120 秒渐弱；渐弱只作用于独立 fade 总线，绝不改写你的主音量 |
| 五层音源供应链 | L0 合成层（永不失效）→ L1 内置已验证清单 → L2 远端动态清单 → L3 运行时发现（只进候选、需人工审核）→ L4 电台（默认关闭） |
| 自动自愈 | 多候选 URL、加载超时、`error`/`stalled` 探测、健康度降权、自动切候选、全失败降级合成层，整链 ≤3 秒且不打断播放 |
| 隐私 | 无 Cookie、无登录、无第三方统计/广告/字体 CDN；仅 3 个 `localStorage` 键保存偏好，`localStorage` 不可用则静默降级为内存态 |
| 无障碍 | 语义化 `aria`、完整键盘操作、≥44px 触控区、320/768/1440 三档响应式、三档亮度、`prefers-reduced-motion` 动效归零 |
| 部署自由度 | 纯静态零构建；GitHub Pages 子路径、`file://` 双击打开、任意静态服务器均可运行 |

---

## 快速开始

**方式一：直接双击**（无需任何工具）

下载本仓库，双击 `index.html` 即可。站点不使用 ES Modules、不 `fetch()` 本地清单，因此在 `file://` 下同样可用。

**方式二：本地静态服务**

```bash
git clone https://github.com/guyue55/stillwave.git
cd stillwave
python3 -m http.server 8000
# 打开 http://127.0.0.1:8000/
```

首次播放需要一次用户点击（浏览器自动播放策略），这是刻意设计：绝不偷偷出声。

---

## 声音库：浏览与点选曲目

页脚状态区有一个「声音库」按钮，紧挨「详情」；点击它展开一个可折叠面板，里面列出全部 **30 首已验证曲目**。

- 用「场景」（全部 / 学习 / 助眠 / 放空 / 冥想）和「类型」（全部 / 氛围音乐 / 自然录音）两组筛选缩小范围。
- 点选任意一首曲目，它立即成为当前**主音源**；正在播放的曲目会高亮标记。
- 换曲**不会改动**当前场景的定时器、亮度、呼吸引导与主音量设置。

如果这是你进页面后的第一次播放手势，点选曲目同时会解锁音频并出声：沿用既有的「先本地合成垫声 → 并行升级在线 MP3」链路，本地合成声立即响起，在线曲目在后台加载并平滑接上——既**不会偷偷自动播放**，也**不会留下静默空窗**。在线曲目若加载失败，既有自愈机制会静默降级回本地合成层，不打断、不弹窗、不改音量。

**已知行为（不是缺陷，是自愈设计的必然结果）**：单次加载预算是 3000ms，而 `archive.org` 实测单曲完整下载需 5.7–9.6 秒、首包可播放时间抖动较大，因此点选后可能出现三种终态：

1. **在线接入所选曲目**——最常见，徽标显示「在线可用」；
2. **在线接入同场景的其它曲目**——徽标显示「备用音源」，会弹出轻提示，音源信息面板与声音库高亮都**如实跟随实际在播的曲目**，不会把 A 曲的名字安在 B 曲的音频上；
3. **降级回本地合成层**——徽标显示「本地合成」，信息面板说明当前为合成声，声音库不再高亮任何在线曲目，随时可以再点一次重试。

如果希望「点哪首就必须是哪首、失败即降级而不启用同场景备选」，可把 `js/config.js` 的 `LOAD_TIMEOUT_MS` 调大，或收窄 `sources.resolveCandidates()` 的备选池——两者都属于产品取舍，默认配置选择的是「尽量有在线音乐可听」。

---

## 部署到 GitHub Pages

本仓库**站点文件就在根目录**，因此 Pages 直接发布分支根目录即可，无需构建。

1. Fork 本仓库（或 Push 到你自己的仓库）。
2. 仓库 **Settings → Pages → Build and deployment**：
   - Source：`Deploy from a branch`
   - Branch：`main` / Path：`/ (root)`
3. 保存后等待约 1 分钟，访问 `https://<你的用户名>.github.io/<仓库名>/`。

所有本地资源都使用 `./` 相对路径，因此子路径部署天然兼容；仓库里的 `.nojekyll` 会让 Pages 跳过 Jekyll，按原样发布静态文件。

**自定义域名**：若绑定了自定义域（或部署在 `username.github.io` 用户主页仓库），`js/config.js` 的自动推导会失效，请手动填写唯一可配置常量：

```js
// js/config.js 第 186 行附近
var REMOTE_MANIFEST = 'https://cdn.jsdelivr.net/gh/<user>/<repo>@main/data/audio-sources.json';
```

不填也完全可用（内置 30 首 + 合成层兜底），只是拿不到远端热更新。

---

## 曲库如何长期不失效

这是本项目最花力气的部分。在线资源会失效、会被限流、CORS 会变，所以站点不依赖任何单条链接。

| 层 | 内容 | 失效时 |
|---|---|---|
| **L0** | Web Audio 程序化合成声景 | 永不失效，永远兜底 |
| **L1** | `data/audio-sources.json` 内置 30 首逐条实测曲目 | 前端直接读同源的 `data/audio-sources.js`，不 `fetch()` 本地文件，`file://` 可用 |
| **L2** | 远端动态清单（jsDelivr + GitHub Raw 双 CDN、ETag、版本化缓存、原子回退） | 任一失败自动切下一个；`config.js` 会自动从 `*.github.io/<repo>` 推导候选 URL |
| **L3** | archive.org 运行时发现 | 结果**只进 `candidates[]`**，恒定 `verified=false / needsReview=true`，0 条进入播放序列；必须人工 `--promote` |
| **L4** | radio-browser 电台 | 质量不可控，默认关闭，不发起任何请求 |

**每周自动健康检查**：`.github/workflows/refresh-sources.yml` 在每周一 03:00 UTC（也可手动触发）执行：

```bash
python3 tools/refresh-sources.py --offline --dry-run --json-report /tmp/stillwave-report.json
python3 tools/refresh-sources.py --check-only --discover --max-new 10 --apply \
  --json-report /tmp/stillwave-health.json
```

若 `data/` 有变化则自动提交回仓库，前端下次加载即可通过 L2 获取新版清单。健康脚本内置三重保护：

- **失败项错峰重试**：单次超时不会被误判为死链；
- **整批异常保护**：全部失败或失败率 >40% 时判定为源站/网络整体异常，**跳过本次回写**，绝不把曲库写废；
- **自动恢复**：曲目恢复可用时复位 `enabled` 并移出隔离区，曲库不会随时间单调缩水。

手动运行（只读体检，不写文件）：

```bash
python3 tools/refresh-sources.py --check-only --dry-run --json-report health.json
python3 tools/refresh-sources.py --offline --dry-run          # 完全离线校验
```

新增曲目必须逐条实测，见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

---

## 项目结构

```
.
├── index.html                     # 唯一入口：七分区 DOM + 9 个 defer 脚本顺序装载
├── styles/
│   ├── tokens.css                 # 设计令牌：深色低刺激配色、亮度三档、焦点环
│   └── app.css                    # 布局与组件、响应式
├── js/
│   ├── config.js                  # 唯一可配置常量 + 场景处方 + 事件名（第 1 位装载）
│   ├── store.js                   # 状态唯一真源、事件总线、本地持久化
│   ├── sources.js                 # 五层供应链、健康度、字段白名单投影
│   ├── synth.js                   # Web Audio 内核、四级增益总线、10 种声景
│   ├── player.js                  # 播放引擎、混音、自愈链路
│   ├── timer.js                   # 睡眠定时与渐弱
│   ├── ui.js                      # DOM 渲染、aria、呼吸圆环、快捷键
│   └── main.js                    # 引导装配 + window.__STILLWAVE__ 测试契约
├── data/
│   ├── audio-sources.json         # 权威清单（供 CDN / 脚本 / 静态断言）
│   └── audio-sources.js           # 同一清单的 window.SW.BUNDLED_MANIFEST 形态
├── tools/refresh-sources.py       # 曲库健康检查 / 动态发现 / 原子双写（纯标准库）
├── .github/workflows/             # 每周曲库刷新工作流
├── qa/                            # 自动化测试套件（见 qa/README.md）
└── docs/                          # 竞品调研、PRD、架构、实现记录、验收报告
```

**架构要点**：不使用 ES Modules / `import` / `export`，而是 `window.SW` 单命名空间 + IIFE + 经典 `<script defer>` 顺序装载。这是为了兼容 Chrome/Firefox 在 `file://` 下对模块脚本的 CORS 限制。四级统一增益总线为
`trackGain → mixBus → fadeGain → masterGain → destination`，定时渐弱只操作 `fadeGain`。

---

## 测试

```bash
# 全量回归（需要 Playwright + 本机 Chrome；约 4 分钟）
qa/run_all.sh --phase full --round 4

# 仅静态契约（不需要浏览器，秒级）
python3 qa/test_static_contracts.py
```

`qa/common.py` 会自动识别布局：站点在 `meditation/` 子目录（开发工作区）或直接在仓库根（本仓库），两种都能复跑。

最近一次干净算力轮的验收结果（Round 4，含声音库新增用例）：

| 指标 | 结果 |
|---|---|
| 用例总数 | 101 |
| 正式断言 | **91 / 91 通过（100%）** |
| 源码失败 | **0** |
| 未验证（环境限制，非缺陷） | 10 |
| QA 路由结论 | `ROUTE: NoOne` |

逐套件：静态契约 27/27、刷新脚本 7/7、浏览器 45/45（+5 未验证）、降级重复 6/6、环境探测 6/6（+5 未验证）。
其中声音库专项为 `ST-25~ST-27` 与 `BR-40~BR-46` 共 10 条，全部通过。

未验证项已逐条如实列在 [最终验收报告](./docs/04-qa-report.md) §6：仅 Chrome 在本环境实跑通过，Firefox / Safari / WebKit 因本机浏览器二进制启动超时无法验证；60 分钟长时判据仅完成 9.04 分钟浸泡采样（趋势平稳、无内存泄漏、零控制台错误）。**请勿把 Chrome 的结果外推到其它浏览器**，完整矩阵与证据见报告。

---

## 文档索引

| 文档 | 内容 |
|---|---|
| [音频资源与竞品调研](./docs/00-audio-sources-research.md) | CORS / HTTP 实测、可用与已排除的音源、真实浏览器播放验证 |
| [已验证曲库源数据](./docs/00-verified-tracks.json) | 30 首逐条实测的原始记录（清单由此程序化生成） |
| [产品需求文档 PRD](./docs/01-prd.md) | 竞品调研、用户故事、P0-01~P0-18、验收闸门 A1~A14 |
| [系统架构设计](./docs/02-architecture.md) | 分层设计、数据结构、时序、AD 决策记录、任务分解 |
| [实现记录](./docs/03-implementation.md) | 15 文件清单、红线落实、缺陷修复追溯 |
| [最终验收报告](./docs/04-qa-report.md) | 全量测试结果、闸门映射、环境限制披露、部署指南 |
| [优化路线](./docs/05-optimization-roadmap.md) | 后续优化方向的调研与排期 |
| [贡献指南](./CONTRIBUTING.md) | 新增曲目的实测流程与代码约束 |
| [音频来源与许可声明](./NOTICE.md) | 第三方作品署名、许可分布、使用限制 |

---

## 隐私与合规

- 不收集、不上传任何数据；无 Cookie、无登录、无统计、无广告、无第三方字体。
- 仅用 3 个 `localStorage` 键（`sw.prefs.v1` / `sw.health.v1` / `sw.manifest.v1`）保存偏好与音源健康度，可在页面内「清除本地设置」一键重置。
- 音频文件**不托管在本仓库**，页面仅保存公开直链，播放时由浏览器直接向 archive.org 请求。权利归各原作者所有，具体条款见 [NOTICE.md](./NOTICE.md)。
- 站点内所有曲目名使用中文展示名；原始标题仅存在于数据层，UI 通过白名单投影取字段，不暴露裸 URL、错误码或调试元数据。

---

## 致谢

音频资源来自 [Internet Archive](https://archive.org/) 上的 Jamendo CC 氛围音乐与 [aporee soundmap](https://aporee.org/maps/) 真实自然录音，感谢创作者与存档者。远端清单分发借助 [jsDelivr](https://www.jsdelivr.com/) 与 GitHub Raw。

---

## License

站点源代码采用 [MIT License](./LICENSE)。**该许可不涵盖第三方音频作品**，音频的使用范围与限制见 [NOTICE.md](./NOTICE.md)。

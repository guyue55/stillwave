# 静澜 Stillwave 优化调研报告与分阶段路线

> 文档编号：05-optimization-roadmap
> 归档时间：2026-11
> 适用项目：静澜 Stillwave（纯静态冥想 / 声景网站）
> 阅读说明：本文自包含，可直接供第三方阅读。文中网址均为「可查证来源链接」或「本轮实测端点」，文档本身不加载任何外部图片、脚本、样式或字体。

---

## 1. 调研目标与方法

### 1.1 调研目标与背景

站点已交付的核心能力：4 个场景（学习 / 助眠 / 放空 / 冥想）、30 首逐条实测可播的在线音频（21 首 Jamendo CC 氛围音乐 + 9 首 aporee 真实自然录音，均取自 archive.org 直链）、10 种 Web Audio 程序化合成声景（白噪 / 粉噪 / 棕噪 / 细雨 / 溪流 / 风 / 海浪 / 颂钵 / 篝火 / 林风）、最多 3 轨混音、主音量与分轨音量、睡眠定时与渐弱、五层音源供应链（L0 合成层永不失效，L1 内置清单，L2 远端动态清单 jsDelivr / GitHub Raw，L3 archive.org 运行时发现只进候选且需人工审核，L4 电台默认关闭）、失效自动切换候选或降级到合成层、中文展示名与来源许可署名。

已识别的交互短板：用户不能浏览和主动选择具体曲目，只能靠「换一曲」按顺序切换；曲目信息只在展开面板里以文字呈现；声音种类固定为上述 30 首加 10 种合成声景；没有收藏、没有自定义混音预设保存、没有搜索与筛选。

本次调研要回答：在不破坏「零密钥纯静态运行时」硬约束的前提下，如何补齐「可浏览、可选择、可组合」，以及曲库如何安全扩充。

### 1.2 硬约束「零密钥纯静态运行时」从何而来

站点的交付形态是 GitHub Pages 托管的纯静态前端：无后端、无构建步骤、无框架、无 API key、无数据库；资源一律用 `./` 相对路径；不使用 ES Modules，改用 `window.SW` 单命名空间 + 经典 `defer` 顺序脚本；支持 `file://` 双击打开。项目实现文档还记录了一个具体原因：Chrome / Firefox 对 `file://` 下的 module script 强制 CORS 会导致白屏，因此改用经典 `defer` 脚本（`docs/03-implementation.md` §5 第 1 条，本轮只读核对）。

由此推出的硬性边界：

- 运行时不得依赖任何需要密钥、账号或 OAuth 的接口；
- 不得引入需要服务端或构建期才能产出的环节；
- 跨域音频与清单直链必须 CORS 可用且稳定，且 `file://` 打开、网络不可达时要能静默回退到 L0 合成层；
- 页面必须保持低刺激 / 无打扰的冥想调性，首屏体积与性能克制。

### 1.3 调研方法

- 时间：2026-11。
- 联网检索：主流产品官方页与帮助中心、API 官方文档、社区讨论与许可说明。
- 一手 HTTP / CORS 实测：对候选 API 用 `curl -s -o /dev/null -D - -H "Origin: https://example.github.io" <URL>` 读取响应头，模拟浏览器跨域 GET；对直链 302 用 `-L` 跟随并逐跳检查 `Access-Control-Allow-Origin`。记录 HTTP 状态、`Content-Type`、`ACAO`、`WWW-Authenticate`、`Location`。该命令可复现。
- 只读源码核对：只读 `meditation/`、`stillwave/` 下的源码与 `docs/`，确认改动范围与本轮落地项；本轮未修改任何源码。
- 产品功能描述来自公开网页检索，未逐一登录实测各产品客户端。

### 1.4 标注约定

| 标注 | 含义 |
|---|---|
| [实测] | 本轮 curl 亲自观测到的响应头或状态码 |
| [文档] | 来自官方文档或公开检索，本轮未实测 |
| [未实测] | 无有效观测，不做推测 |
| [推断] | 基于事实给出的建议或判断 |

---

## 2. 一手实测数据表

`ACAO` 指响应头 `Access-Control-Allow-Origin`。所有请求均带 `Origin: https://example.github.io`，用于模拟 GitHub Pages 跨域场景。

| 端点 | 是否需要密钥 | 实测 CORS（ACAO） | HTTP 结果 | 能否零密钥纯静态运行时接入 | 结论 |
|---|---|---|---|---|---|
| `archive.org/advancedsearch.php?q=...&output=json` | 否 [实测] | `*` [实测]；另返回 `access-control-allow-headers: Accept-Encoding,Accept-Language,Authorization,Baggage,Cache-Control,Content-Length,Content-Range,DNT,Pragma,Range,Sentry-Trace,X-Requested-With` | `200` `application/json` [实测] | 能 | 无密钥、可前端直连的只读检索入口；但社区内容质量参差，宜仅作离线策展候选 |
| `archive.org/metadata/{id}`（实测 identifier 为 `etree`） | 否 [实测] | `*` [实测] | `200` `application/json` [实测] | 能 | 可由 identifier 取 `files[]` 拼出 `/download/` 直链，无密钥 |
| `archive.org/download/{id}/{file}.mp3`（实测 `testmp3testfile/mpthreetest.mp3`） | 否 [实测] | 首跳 `302` 带 `*`；第二跳 `200` 同样带 `*` [实测] | 首跳 `302`（`Location: https://dn710807.ca.archive.org/0/items/testmp3testfile/mpthreetest.mp3`，`text/html`）；第二跳 `200` `audio/mpeg` [实测] | 能 | 302 跳转链两跳均带 `ACAO:*`，这是 30 首已验证直链可用的关键；项目此前已对 30 首逐条实测 |
| `freesound.org/apiv2/search/text/`（无 token） | 是 [实测] | `*` [实测] | `401` `application/json`，`WWW-Authenticate: Bearer realm="api"` [实测] | 否 | CORS 虽开放，但无 token 直接 401；业务上需 API key 或 OAuth2，违反零密钥约束 |
| `api.jamendo.com/v3.0/tracks/`（带占位 `client_id=test`） | 是 [文档] | `*` [实测] | `200` `application/json; charset=UTF-8` [实测]；响应体未读取 | 否 | CORS 已实测为 `*`，但「需有效 `client_id`」来自官方文档而非本轮实测；带占位 ID 的 200 不能证明可取到可用曲目。官方条款对缓存 / 离线有限制 [文档，未实测] |
| `cdn.jsdelivr.net`（实测 `/gh/jquery/jquery@3.7.1/README.md`） | 否 [实测] | `*` [实测] | `200` `text/markdown; charset=utf-8` [实测] | 能 | 适合承载 L2 远端动态清单；需自有仓库 |
| `raw.githubusercontent.com`（实测 `/jquery/jquery/main/README.md`） | 否 [实测] | `*` [实测] | `200` `text/plain; charset=utf-8` [实测] | 能 | 与 jsDelivr 互为备用，适合 L2 清单双候选 |
| `upload.wikimedia.org`（实测 `/robots.txt`） | 否 [实测] | `*` [实测] | `200` `text/plain` [实测] | 能（有条件） | 以 `robots.txt` 探测该域 CORS 行为；`upload.wikimedia.org` 上具体音频文件的 CORS 与格式未复测 [未实测] |
| `de1.api.radio-browser.info/json/countries`（补充观测） | 否 [实测] | `*` [实测]；另 `access-control-allow-headers: origin, x-requested-with, content-type, User-Agent` | `200` `application/json` [实测] | 能（有条件） | 目录 API 可跨域，但内容不可控；主域 `api.radio-browser.info/json/tags` 实测 `404 text/html` 且未返回 ACAO [实测]，需走具体镜像 |

**关键判读 [推断]**

- archive.org 的检索、元数据、直链三个端点全部 `ACAO:*` 且无需密钥，是唯一「既能扩库又不破坏零密钥」的入口；直链 302 两跳均带 CORS 是重点，因为播放依赖重定向后的 CDN 响应。
- jsDelivr、GitHub Raw、`upload.wikimedia.org` 三个静态托管域均 `ACAO:*`，适合承载 L2 远端清单与静态资源，不构成瓶颈。
- Freesound 是「CORS 可用但需密钥」的典型：CORS 头不能替代鉴权，零密钥静态站不可接入。
- 第三方 API 目录（openpublicapis.com）曾把 archive.org 标为「CORS No」，与本轮实测及项目 30 首实测矛盾，以实测为准 [实测 / 文档]。

**本节未实测项（如实披露）**

- Jamendo 响应体内容、无效 `client_id` 的业务错误码、35,000 次/月与禁缓存 / 离线条款：未实测，仅见官方文档与检索资料。
- Freesound 60 次/分、2000 次/日限流，以及商用 API 需与 UPF 协商的条款：未实测。
- Wikimedia Commons MediaWiki Action API 的 `origin=*`、逐文件许可、descriptive User-Agent、串行 + `maxlag` 要求：未实测（本轮只测了 `upload.wikimedia.org/robots.txt`）。
- `upload.wikimedia.org` 上具体音频文件的 CORS 与格式占比：未复测。
- SomaFM Icecast 流（`ice1.somafm.com`）响应头：本轮未取得有效 ICY 头，未实测成功。
- archive.org advancedsearch 的深度分页上限与限流：未实测，仅见检索资料称查询昂贵、大 offset 受限。

---

## 3. 同类产品对比表

功能描述为公开网页检索所得，未逐一登录实测各产品客户端；标「未核实」者未找到可查证依据。来源列给出可查证链接。

| 产品 | 可浏览并主动选择曲目 | 分层混音与每声一条音量滑块 | 命名保存预设 | URL 分享 | 渐弱计时 | 按场景或类型分组（标题+类型+时长） | 登录墙 | 是否契合低刺激冥想调性 | 来源链接 |
|---|---|---|---|---|---|---|---|---|---|
| Noisli | 是（图标网格点选） | 是（每声一条音量滑块叠加） | 是（命名保存 / 分享混音） | 是 | 是 | 部分（免费版限 Productivity / Random / Relax 三类，非标题+类型+时长） | 部分（基础免登录，进阶需付费） | 是（单屏、不滚动、不自动播放、「设一次就忘掉」） | https://boringwebsites.blog/posts/noisli-the-website-that-mixes-ambient-noise-for-focus |
| A Soft Murmur | 是（图标行点选） | 是（每声滑块，含白噪 / 棕噪 / 雨的多种质感） | 是（命名保存） | 是 | 是（渐弱计时 + 淡入） | 否（平铺图标，无分组与时长） | 否 | 是（极简、即时、无账号门槛） | https://recommendedwebsites.online/blog/a-soft-murmur |
| Headspace | 是（Focus / Sleep 库按栏目浏览） | 否（单条播放） | 未核实 | 否 | 未核实 | 是（Focus Music / Soundscapes / Sound Baths / Binaural Beats / White Noise & Sleep Sounds / Sleep Radio；每条标题+类型+时长 45–480 min；噪声按颜色细分 9 种） | 是（订阅） | 是（分类克制，无推荐流） | https://www.headspace.com/content/categories/focus |
| myNoise | 是（250+ 生成器按用途分类） | 是（10 段彩色 EQ 滑块 20 Hz–20 kHz，远超每声一条） | 是（Presets / Save in this Browser） | 是（URL 嵌入滑块设置 / mini-player） | 是 | 是（按 Focus / Meditation / Sleep / Tinnitus 等用途分类） | 否（广告免费、重隐私） | 部分（ Audio 能力极强，但 10 段 EQ 偏调音台、信息密度高） | https://www.mynoise.com/ |
| Calm | 是（3 主题 + 子分类，音乐板块 200+ 独家曲） | 否 | 未核实 | 否 | 未核实 | 是（睡眠 / 冥想 / 音乐三主题，下设白噪音 / 自然 / ASMR / 离线等） | 是（订阅，独家 / 明星内容） | 部分（分类克制，但付费墙与独家首发偏高刺激） | https://www.163.com/dy/article/FCN3UC2R0542A4MJ.html |
| Endel | 否（无曲库，依心率 / 天气 / 时间 / 光照 / 运动实时生成） | 否 | 否（仅内置 Relax / Focus / Sleep 模式） | 未核实 | 未核实 | 部分（按 Relax / Focus / Sleep 模式组织） | 部分（客户端需下载 / 订阅，web demo 免登录，未核实） | 是（自适应、无打扰） | https://endel.zendesk.com/hc/en-us/articles/360011795480-What-is-Endel |
| Brain.fm | 部分（按心理状态×活动选模式，非曲目） | 否（有「neural effect」强度滑块，非分层混音） | 未核实 | 未核实 | 是（Timer / Interval / Infinite 计时器） | 是（按活动分类 + 时长） | 是（订阅） | 是（功能化、简洁、无打扰） | https://www.brain.fm/blog/adaptive-focus-music-technology-brain-fm |
| Free Music Archive | 是（搜索 / 筛选 / 曲库浏览） | 否 | 未核实 | 否（曲目页链接，非混音分享） | 否 | 是（按 genre / license / duration / 商用 / remix 过滤） | 否（无需账号即可听 / 下载） | 否（曲库发现型，封面 / 列表偏主动浏览） | https://freemusicarchive.org/faq/ |

**许可与来源展示小结** [文档]：FMA、Jamendo、ccMixter、Freesound、Wikimedia Commons 均要求逐曲 / 逐声核对许可与署名（FMA 用 TASL，即 Title / Author / Source / License），不存在「整库统一可商用」；Calm、Headspace、Endel、Brain.fm 为自有版权，不展示 CC。本项目已做的「中文展示名 + 来源许可署名」方向正确，应继续保持逐条来源页链接。[推断]

**补充来源链接**（许可、过滤、工程）

- FMA 署名指引：https://www.freemusicarchive.org/FAQ_For_Educators/
- archive.org 搜索基础指南（含按 CC 许可检索）：https://help.archive.org/help/search-a-basic-guide/
- archive.org 公开 API 说明：https://blog.archive.org/?p=17636/
- archive.org 许可过滤社区讨论：https://archive.org/post/1107525
- Freesound 鉴权文档：https://freesound.org/docs/api/authentication.html
- Freesound APIv2 概览：https://freesound.org/docs/api/overview.html
- Jamendo 条款汇总：https://agentgid.com/assets/jamendo
- Wikimedia Commons 复用规则：https://agentgid.com/assets/wikimedia-commons
- ccMixter 许可汇总：https://agentgid.com/assets/ccmixter
- Web Audio 参数平滑与爆音：https://audiofusion.com/docs/performance-tips/ ；https://simplified.media/guides/web-audio-api
- localStorage（MDN）：https://developer.mozilla.org/zh-CN/docs/Web/API/Window/localStorage
- WCAG 2.2 清单：https://www.equalweb.com/guides/wcag-checklist
- Noisli / A Soft Murmur / Ambient Mixer 横向对比：https://www.techbloat.com/the-best-sites-for-background-or-ambient-noise.html
- 环境音工具中文综述（Noisli / Noises Online / Defonic）：https://zh.101-help.com/833b9bbeda-mian-fei-ambient-noise-generator-software-toolssheng-cheng-ambient-sound

---

## 4. 七条结论（原 B 部分）

1. **当前最大短板是不能浏览和主动选择曲目，且这是纯 UI 缺口，不依赖任何新的音源或密钥。** [事实 + 推断] `data/audio-sources.json` 每首已含 `scene / kind / display / attribution / item / license / verified / needsReview`，`config.js` 已有 `FILTER_BLACKLIST` 与 `FILTER_RULES`。补一个清单面板即可解掉最大短板，不必改数据源、不必发新请求、不必引入密钥。

2. [事实] Headspace 用「栏目分组 + 标题 + 类型 + 时长」、噪声按颜色细分；[推断] 比封面墙 / 推荐流更契合低刺激，且可直接映射到现有 `scene` + `kind` + 10 种 `VOICE_LABELS`。

3. [事实] Noisli / A Soft Murmur 的核心范式是「每声一条音量滑块 + 命名保存 + URL 分享 + 渐弱计时」，且 Noisli 明确「单屏、不滚动、不自动播放、设一次就忘掉」；[推断] 本项目已有等价能力（≤3 轨 / 分轨音量 / 渐弱），缺的只是「保存与分享」。

4. [事实] `store.js` 已具备 `readStorage / writeStorage`、`collectPrefs()`（含 `tracks[]`）、`savePrefs / loadPrefs / clearAll`、`storageUsable()` 探测与内存降级；[推断] 收藏与预设几乎零新增存储层，复用即可。

5. [事实] MDN 明确 localStorage 在 `file://` 下 origin 可能非有效元组、可能被拒；[事实] 项目已静默降级到内存；[推断] 新增存储键必须沿用同一降级路径，才能保证「双击打开」不白屏。

6. **低刺激 ≠ 低对比：背景可柔和，但正文 ≥4.5:1、控件/焦点环 ≥3:1、禁自动播放需保持。** [事实] WCAG 2.2：1.4.2 音频控制（禁自动播放）、2.1.1 / 2.4.7 键盘可达与焦点可见、1.4.3 正文 4.5:1、1.4.11 控件与焦点环 3:1、2.2.2 超过 5 秒的动画可暂停、`prefers-reduced-motion` 关闭非必要动效；[事实] `index.html` 已有 skip-link、tablist / tab / tabpanel + `aria-selected` / `tabindex`、`aria-live`、icon-only 按钮的 `aria-label` 等良好基线，新控件沿用即可。

7. [事实] archive.org 两个 API 实测 `ACAO:*` 且无密钥，是唯一「既能扩库又不破坏零密钥」的入口；[推断] 但应只做离线策展、人工审核，绝不运行时自动入播（社区许可与内容质量风险）。

---

## 5. P0 / P1 / P2 路线表

### 5.1 总览

| 编号 | 优先级 | 项目 | 优先级依据 |
|---|---|---|---|
| P0-1 | 立刻 | 声音库：曲目浏览与点选 | 直接补最大短板，纯 UI 改动、零约束风险，本轮已落地 |
| P0-2 | 立刻 | 收藏 + 自定义混音预设保存 | 复用现成 localStorage 层，补齐「可组合」的持久化 |
| P0-3 | 立刻 | URL 分享状态 | 同类产品标配，`location.hash` 零后端、不泄露隐私 |
| P0-4 | 立刻 | 无障碍与低刺激加固 | 新 UI 引入即须满足 WCAG，避免返工 |
| P1-1 | 中期 | 轻量搜索 / 筛选 | 曲库一旦可浏览，筛选是自然延伸；纯前端内存过滤 |
| P1-2 | 中期 | archive.org 离线策展扩库 | 唯一零密钥可扩库入口，但需人工审核，风险中等 |
| P1-3 | 中期 | 克制的分轨静音 / 独奏 | 提升可组合性，但须防止调音台化与爆音 |
| P2-1 | 长期 | 伪自适应合成声景 | 借鉴生成式产品，纯本地、默认关闭，价值待验证 |
| P2-2 | 长期 | 偏好导出 / 导入 | 无后端下替代跨设备同步，需先定义 schema |

### 5.2 P0-1 声音库：曲目浏览与点选

- 改动范围：`index.html`（清单容器与筛选控件）、`styles/app.css`（低刺激列表、默认收起）、`js/ui.js`（渲染 / 点击派发 / aria 同步）；`js/store.js` 仅在需记住上次选择时扩展已有 `tracks[]`；`data/audio-sources.json` 与 `js/sources.js` 基本不动。
- 约束影响：纯静态 / 零密钥 / CORS 零影响，只用内置 L1 清单、不发新请求；首屏仅增少量 DOM 与 CSS，数据在内存；不引入 ES Module 或构建。
- 验收要点：`file://` 可展开清单；选任一曲走「先出声再升级 / 降级到合成层」链路；失效曲仍能降级；键盘可达、焦点可见；`prefers-reduced-motion` 下无展开动效；无自动播放；不干扰既有 30 条许可清单扫描。
- 优先级依据：最大短板、改动最小、零约束风险，故列为最高优先级（本轮已落地，见第 7 节）。

### 5.3 P0-2 收藏 + 自定义混音预设保存

- 改动范围：`js/config.js`（新增 `sw.favorites.v1`、`sw.presets.v1` 两个 `STORAGE_KEYS`）、`js/store.js`（读写与字段校验，复用原子回退）、`js/ui.js` + `index.html` + `styles/app.css`（收藏星标、预设列表与调用）。预设结构建议 `{name, tracks:[{id,kind,voice,volume}], masterVolume}`。
- 约束影响：零网络、零密钥；[事实] `file://` / 隐私模式可能拒 localStorage，项目内存降级正好覆盖，须保证新键走同一路径；[事实] 约 5 MB 配额，几十条预设远低于上限。
- 验收要点：刷新后收藏与预设仍在；受限时自动内存降级且不报错、不白屏；`clearAll()` 一并清除；只存 id 与音量，不存任何可识别个人信息。
- 优先级依据：直接复用 `store.js` 现成存储层，改动小、收益明确。

### 5.4 P0-3 URL 分享状态

- 改动范围：`js/main.js`（启动时解析 hash）、`js/ui.js`（生成 / 复制链接）、`index.html`（分享按钮）。用 `location.hash`（如 `#m=id1,id2&v=.4,.3&s=sleep`）编码混音，并监听 `hashchange`。[事实] A Soft Murmur 与 myNoise 均支持链接分享。
- 约束影响：纯静态；[事实] 片段标识符不随 HTTP 请求发送；仅含 id / 音量 / 场景；须防御性解析（id 白名单、数值钳制 0–1、长度上限、禁止把 hash 内容用 `innerHTML` 注入）以防 XSS。
- 验收要点：他人浏览器可还原同一混音；非法 / 超长 hash 回退默认且不崩溃；复制链接不触发播放。
- 优先级依据：同类产品标配，零后端、零隐私泄露，实现成本低。

### 5.5 P0-4 无障碍与低刺激加固

- 改动范围：`index.html`（role / `aria-label` / `aria-expanded` / `aria-pressed` / `aria-controls`）、`js/ui.js`（焦点管理、`aria-live` 状态播报、`Escape` 关闭）、`styles/tokens.css` + `styles/app.css`（焦点环 ≥3:1、触控目标 ≥24×24 且实践取 44×44、`@media (prefers-reduced-motion: reduce)`）。
- 约束影响：无。
- 验收要点：绝不自动播放（保持 `main.js` 首次手势解锁）；Tab / Enter / Space 全可达、焦点可见不被遮挡；正文 4.5:1、控件 3:1；超过 5 秒的动画可暂停；icon-only 按钮有 `aria-label`。
- 优先级依据：新 UI 一旦引入即须满足 WCAG 2.2，随 P0 一起做可避免返工。

### 5.6 P1-1 轻量搜索 / 筛选

- 改动范围：`js/ui.js` + `index.html` + `styles/app.css`。清单内按场景 / 类型筛选 + 中文名 / 原名搜索，纯前端 `Array.filter` 于内存清单。
- 约束影响：零网络、零密钥、零新增请求；[推断] 注意不要每按键重建整表（节流或 DocumentFragment）。
- 验收要点：30 首到百首量级仍瞬时响应；无自动播放；筛选结果与许可清单扫描互不干扰。
- 优先级依据：曲库可浏览后的自然延伸，纯前端、无外部依赖。

### 5.7 P1-2 archive.org 离线策展扩库

- 改动范围：`data/audio-sources.json`、新增 `tools/` 或 `docs/` 下维护者本地一次性策展脚本与说明（不进页面运行时、不作为必跑构建，以满足「无构建步骤」）、`js/config.js` 过滤规则、`docs/00-audio-sources-research.md`。[事实] advancedsearch 与 metadata 实测 `ACAO:*` 且无密钥，但 [推断] 不做运行时入播：以维护者本地一次性脚本生成候选 JSON，沿用 `needsReview / enabled / health` 字段，人工试听 + CORS + 许可复核后写入 L1 内置清单或 L2 远端清单。
- 约束影响：[文档，未实测] advancedsearch 深度分页受限、查询昂贵，应缓存并保持低 `rows`；只读候选、不自动播放，零密钥 / CORS 风险可控。过滤用官方 `licenseurl:http*by* AND NOT licenseurl:http*by-nc* AND mediatype:(audio)`，再排除人声 collection、叠加标题黑名单与字节 / 扩展名白名单（`config.js` 已有雏形，强化即可）。[文档] IA 音频大类下含 LibriVox、Podcasts、News & Public Affairs、Old Time Radio、Audio Books & Poetry、Spirituality & Religion 等大量人声 collection；社区存在「把整张专辑随便贴个 CC 许可」的情况，标了 CC 不等于上传者有权，故必须人工试听并交叉核对上传者与来源链接。
- 验收要点：每首带来源页 `item`、`license`、`attribution`、实测 `cors:true` / `verified:true` / `needsReview:false`；`file://` 仍可播；不混入人声讲座或播客。
- 优先级依据：唯一零密钥可扩库入口，但涉及内容审核，风险与工作量中等，故列中期。

### 5.8 P1-3 克制的分轨静音 / 独奏

- 改动范围：`js/player.js`（静音用 `setTargetAtTime` 平滑 ramp，勿直接 `gain.value=` 或硬 `connect / disconnect`）、`js/ui.js`、`index.html`。[推断] 只补「分轨静音 / 独奏 + 预设命名保存」，不上 10 段 EQ / 声像 / 精细滤波，以免把冥想站变成调音台。
- 约束影响：零网络；[事实] 直接 `gain.value=` 赋值或硬 `connect / disconnect` 会产生 click / zipper 噪声，应使用 `setTargetAtTime` / `linearRampToValueAtTime` / `exponentialRampToValueAtTime` 平滑（5–20 ms 或 timeConstant 1–5 ms）；`AudioContext` 仍需用户手势后 `resume()`。
- 验收要点：拖动与切换无爆音；`AudioContext` 仍手势后 resume；3 轨叠加长时 CPU 与内存稳定。
- 优先级依据：提升可组合性，但参数暴露须克制，放在声音库与预设稳定之后。

### 5.9 P2-1 伪自适应合成声景

- 改动范围：`js/synth.js` + `js/config.js` + `js/ui.js`。[事实] Endel / Brain.fm 依传感器与神经科学做自适应；[推断] L0 合成层已有程序化雏形，可做「按时段 / 场景缓慢微调合成参数」，但不宣称神经科学功效、默认关闭、纯本地零密钥。
- 约束影响：纯本地、零密钥、可关闭；[推断] 不复制需要心率 / 天气 / 运动输入的专利方案。
- 验收要点：默认关闭且可由用户显式开启；关闭后行为与现状完全一致；不引入新的网络请求。
- 优先级依据：借鉴生成式产品的长期方向，价值待验证，且不改核心播放链路。

### 5.10 P2-2 偏好导出 / 导入

- 改动范围：`js/ui.js` + `js/store.js`。[事实] localStorage 按 origin 隔离、仅本机，无后端无法跨设备同步；[推断] 用「导出 / 导入偏好 JSON 文件」（Blob 下载 + FileReader）作轻量替代，不引入账号或后端。
- 约束影响：纯静态；导入须做 schema 白名单校验与数值钳制，防注入与畸形数据。
- 验收要点：导出文件可在本机重新导入还原；非法 / 超大文件被安全拒绝且不破坏现有偏好；不含任何个人信息。
- 优先级依据：无后端下的折中方案，依赖 P0-2 的预设 schema 先稳定。

---

## 6. 不建议做的方案及逐条理由

1. **运行时接入密钥型 API（Freesound / Jamendo）**：[实测] Freesound 无 token 返回 `401`；[文档，未实测] Jamendo 需有效 `client_id`，非商用额度有限且禁止缓存 / 离线、商用含广告需付费授权。二者直接违反「零密钥 / 无 API key」。现有 21 首 Jamendo 是历史抓取的 archive.org 直链清单，不等于可运行时调用 Jamendo API。

2. **电台流默认开启（radio-browser.info / SomaFM）**：[实测] 目录 API 可跨域、主域部分路径返回 404 且无 ACAO，需走具体镜像；[文档] 社区维护的电台内容不可控，可能含人声、广告、版权音乐；Icecast 流若接 Web Audio 分析节点还需 CORS 且会被 taint。应继续保持 `config.js` 的 `ENABLE_RADIO:false`，仅作实验。

3. **L3 动态发现结果无审核直接入播**：[文档] Internet Archive 社区上传许可与内容质量参差，含大量讲座 / 播客 / 有声书。必须维持现有「L3 只进候选 + `needsReview` 人工审核」纪律。

4. **10 段 EQ / 声像 / 精细滤波全暴露、无上限混音轨数**：[推断] 会把低刺激冥想站变成调音台，增加爆音与相位 / 梳状滤波风险，抬升移动端性能与首屏复杂度。相关信号相位抵消的具体量级未找到权威实测 [未实测]。

5. **自动播放，或把音频接到需要 CORS 的分析节点**：[事实] WCAG 2.2 的 1.4.2 与浏览器 autoplay 策略都要求用户手势；项目 `main.js` 已实现「首次手势解锁 AudioContext」，必须保持。

6. **引入构建步骤 / 框架 / ES Module / 登录 / 后端同步**：[事实] 与「`file://` 双击可开、无构建、`window.SW` 经典 defer 脚本」硬约束冲突；`file://` 下 module script 会被强制 CORS 而白屏。无后端就无法跨设备同步，不应为此引入账号体系。

7. **把 Wikimedia Commons 当作主力曲库**：[文档，未实测] 音频多为 ogg / opus / flac（mp3 少），逐文件 CC BY-SA / GFDL 有 ShareAlike 传染与署名要求，且要求 descriptive User-Agent、串行请求与 `maxlag`。本轮只实测了 `upload.wikimedia.org` 域 CORS，具体音频文件与 API 未复测。成本高于收益，最多作人工策展补充源。

8. **运行时接入 ccMixter / FMA 作为自动曲库**：[文档] ccMixter 无官方公开查询 API（仅手动下载），FMA 逐曲许可混杂需逐条核对。二者适合人工挑曲，不适合自动接入。

9. **照搬音乐播放器 UI**：封面墙、播放列表、进度抢焦、频谱动画、自动播放、推荐流、社交 / 付费墙。[事实] Noisli 的产品哲学是「设一次就忘掉，单屏、不滚动、不自动播放」，A Soft Murmur 亦提示「多轨全开会变成噪音墙」；[推断] 这些做法与低刺激调性冲突。

---

## 7. 本轮已落地项与后续排期

### 7.1 本轮已落地：P0-1 声音库（曲目浏览与点选）

以下实现要点由 team-lead 提供，并经本轮只读核对 `meditation/` 目录源码确认（行号为 `meditation/` 下文件）：

- **数据源只用 `sources.getUiTrackList()` 的白名单 `UiTrack`**：`meditation/js/ui.js` 第 225–233 行注释与代码明确「数据一律来自 `sources.getUiTrackList()` 的 `UiTrack` 白名单投影，展示层拿不到 `url / originalTitle / bytes / health` 等源数据字段（AD-21）」；`meditation/js/sources.js` 第 599 行定义、第 679 行导出 `getUiTrackList`。
- **列表用 `data-lib-name` 而非 `data-track-name`**：`meditation/js/ui.js` 第 227 行注释原文「用 `data-lib-name` 而非 `data-track-name`，避免干扰 A14 对许可清单的 30 条扫描」，第 261 行在 `lib-track` 按钮上使用 `data-lib-name`；`data-track-name` 仍保留给详情面板许可清单（`meditation/js/ui.js` 第 213 行、`meditation/js/main.js` 第 153–155 行）。
- **点选复用 `player.selectTrack()` 的「先合成垫声 → 并行升级在线 MP3」切轨链路**：`meditation/js/ui.js` 第 574 行调用 `player.selectTrack(id)`；`meditation/js/player.js` 第 652–659 行的 `selectTrack` 先经 `sources.getUiTrack(trackId)` 白名单校验，再调用 `switchMainTrack(view.id)`，并注明「已是当前在线主音源时不做无谓重建，避免短暂回到合成层」；`meditation/js/player.js` 第 662–663 行 `onSourceFailure` 注释「保持 L0 垫声、只淡出失败轨」。
- **不引入新构建、不发新请求、不改 `data/audio-sources.*`**：从代码结构看，数据源为内存清单 `getUiTrackList()`、未新增网络请求 [只读核对]；但「是否改动 `data/audio-sources.*`」与「是否绝对没有新增请求」需版本库对比才能确证，本轮未亲自逐项验证 [未实测]，按 team-lead 提供的结论归档。
- **新增独立折叠面板并带场景 / 类型筛选**：`meditation/js/ui.js` 第 230–286 行的 `renderLibraryPanel()` 渲染 `library-panel`，含 `data-lib-scene` 与 `data-lib-kind` 两组筛选按钮（第 243–256 行）、`aria-pressed` 与 `aria-live`（第 247、257、280 行）；第 228、273–285 行注明「结构签名不变时只原地更新『正在播放』高亮，不重建 DOM，保住键盘焦点」。

**目录分叉提示（本轮 Grep 亲自发现）**：上述声音库实现位于 `meditation/` 目录；`stillwave/` 目录目前仅在 `js/sources.js` 第 599 / 679 行有 `getUiTrackList()`，UI 层（`stillwave/js/ui.js`）仍只有 `data-track-name` 的详情面板，未见 `data-lib-name` 与 `selectTrack` 的声音库面板。两份目录近乎同构，后续改动与验收须先明确以哪份为规范仓库，避免分叉。

### 7.2 后续排期

| 顺序 | 项目 | 依赖 | 建议批次 |
|---|---|---|---|
| 1 | P0-4 无障碍与低刺激加固 | 随 P0-1 的新 UI 一起验收 | 与 P0-1 同批 |
| 2 | P0-2 收藏 + 自定义混音预设保存 | 复用 `store.js` 存储层 | 紧接 P0-1 |
| 3 | P0-3 URL 分享状态 | 依赖 P0-2 的稳定曲目 id | 与 P0-2 同批 |
| 4 | P1-1 轻量搜索 / 筛选 | 依赖声音库面板 | P0 稳定后 |
| 5 | P1-2 archive.org 离线策展扩库 | 人工审核流程、过滤规则 | 独立维护批次 |
| 6 | P1-3 克制的分轨静音 / 独奏 | 依赖 P0-2 预设 | P1 后段 |
| 7 | P2-1 伪自适应合成声景 | 默认关闭，价值待验证 | 长期 |
| 8 | P2-2 偏好导出 / 导入 | 依赖 P0-2 预设 schema | 长期 |

### 7.3 统一验收口径

- 纯静态：`file://` 双击可开；无构建步骤、无框架、无 ES Module、无 API key、无后端、无新密钥服务。
- 音源：失效候选自动切换或降级到 L0 合成层，永不静音；30 首许可清单扫描（A14）不受新增 UI 干扰。
- 低刺激与无障碍：无自动播放；键盘全可达、焦点可见；正文 ≥4.5:1、控件与焦点环 ≥3:1；`prefers-reduced-motion` 下无展开动效；超过 5 秒的动画可暂停。
- 偏好：刷新后仍在；`file://` 或隐私模式拒 localStorage 时静默内存降级、不白屏；`clearAll()` 能一并清除。
- 隐私：收藏、预设、URL hash 仅含曲目 id / 音量 / 场景，不含个人信息；hash 内容不得用 `innerHTML` 注入。

### 7.4 本轮调研的验证边界（如实披露）

- **未逐一登录实测产品客户端**：第 3 节功能矩阵来自公开网页检索，标「未核实」的单元格未找到可查证依据；部分计时 / 登录墙细节为间接推断。
- **未实测的 API 条款**：Jamendo 响应体与无效 `client_id` 的业务行为、35,000 次/月与禁缓存 / 离线；Freesound 限流与商用协商；Wikimedia Commons MediaWiki API 的 `origin=*` 与许可细节；SomaFM Icecast 流响应头；archive.org advancedsearch 深度分页上限。以上均按官方文档或检索资料归档，非本轮实测。
- **未复测**：`upload.wikimedia.org` 上具体音频文件的 CORS 与格式占比（本轮只测 `/robots.txt`）。
- **未亲自逐项验证的落地声明**：P0-1 的「不引入新构建、不发新请求、不改 `data/audio-sources.*`」中，「不改数据文件」与「绝对无新增请求」需版本库对比，本轮只读源码未能确证，按 team-lead 提供的结论归档。
- **未实测的工程判断**：多轨相关信号的相位抵消 / 梳状滤波量级未找到权威实测；多个独立噪声源功率叠加通常安全属推断。
- **未实测的目录状态**：`meditation/` 与 `stillwave/` 哪一份为规范仓库，未由本轮确认，需团队拍板。

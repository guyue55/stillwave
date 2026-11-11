# 音频在线资源技术预研（主理人实测）

> 实测时间：2026-11-09 23:4x GMT+8；环境：macOS / curl 经本地代理出站。
> 本文只记录**可复现的客观事实**，作为产品经理与架构师的输入，不是 PRD / 架构设计。

## 1. 实测结论总表

| 候选源 | 端点 | CORS | 实测结果 | 结论 |
|---|---|---|---|---|
| Internet Archive 检索 API | `https://archive.org/advancedsearch.php?q=...&output=json` | ✅ `Access-Control-Allow-Origin: *` | HTTP 200 / JSON，`numFound` 正常 | ✅ 可用于**动态发现**曲目 |
| Internet Archive 元数据 API | `https://archive.org/metadata/{identifier}` | ✅ `*` | HTTP 200 / JSON，`files[]` 含音频文件名 | ✅ 可用于**动态展开**可播放直链 |
| Internet Archive 音频直链 | `https://archive.org/download/{identifier}/{file}.mp3` | ✅ `*`（302 前与重定向后**都**带） | HTTP 206 + `content-type: audio/mpeg` + `content-range` | ✅ **在线音乐主源** |
| Wikimedia 文件直链 | `https://upload.wikimedia.org/wikipedia/commons/.../*.ogg` | ✅ `*` | HTTP 206 + `application/ogg` | ✅ 备用音频源（CDN 极稳） |
| Wikimedia Commons 查询 API | `https://commons.wikimedia.org/w/api.php?...` | ❌ 未返回 ACAO，且高频触发 `403 Too Many Reqs` | 不可前端直调 | ❌ 排除（仅可离线生成清单） |
| jsDelivr GitHub CDN | `https://cdn.jsdelivr.net/gh/{user}/{repo}@{branch}/{path}` | ✅ `*` | HTTP 200 | ✅ **远程资源清单首选 CDN** |
| GitHub Raw | `https://raw.githubusercontent.com/{user}/{repo}/{branch}/{path}` | ✅ `*` | HTTP 200 | ✅ 清单备用 CDN |
| Radio Browser API | `https://de1.api.radio-browser.info/json/stations/search?tag=ambient&hidebroken=true` | ✅ `*` | HTTP 200，返回 `url` 字段 | ✅ 可**动态发现**氛围电台流（质量不可控，仅作增强） |
| SomaFM ICECast 流 | `https://ice1.somafm.com/dronezone-128-mp3` | — | `curl: (52) Empty reply from server`，多域名一致；网页 `somafm.com/dronezone/` 可访问 | ❌ 不作为依赖，最多可选 |
| Mixkit 音效 CDN | `https://assets.mixkit.co/active_storage/sfx/.../...-preview.mp3` | 未返回 ACAO | HTTP 206 + `audio/mpeg` | ⚠️ 仅 `<audio>` 播放可用，不可进 Web Audio 分析链路 |
| Google 声音库 | `https://actions.google.com/sounds/v1/ambiences/rain_heavy_loud.ogg` | ✅ `*` | HTTP 404（该路径已失效） | ❌ 印证「链接会失效」这一核心风险 |
| Web Audio 程序化合成 | 浏览器本地 AudioContext | 不适用 | 100% 可用、零网络 | ✅ **永不失效的底座** |

## 2. 已验证真实可播放的在线音乐直链（抽样，均 206 + audio/mpeg + CORS）

来自 archive.org 的 Jamendo CC 授权氛围音乐合集：

1. `https://archive.org/download/jamendo-122281/01-1038385-Ambient%20Sounddesign-Morning%20Fog.mp3` （7,748,351 B）
2. `https://archive.org/download/jamendo-216617/01-1376227-Audio%20Earth-Beautiful%20Ambient.mp3` （2,425,728 B）
3. `https://archive.org/download/jamendo-253194/01-1801289-MainMusic-Ambient%20Minimal%20Corporate.mp3` （3,015,040 B）
4. `https://archive.org/download/jamendo-130250/01-1092892-Ambient%20Samurai%20-%20Ichiro%20NAKAGAWA-Music%20For%20Senses%20To%20Flow_______.mp3`
5. `https://archive.org/download/jamendo-209889/01-1205489-AudioSphere-Corporate%20Ambient.mp3`

检索方式（可复现）：
`https://archive.org/advancedsearch.php?q=title:(ambient) AND mediatype:audio AND -collection:podcasts&fl[]=identifier&rows=10&output=json`
→ 对每个 identifier 调 `https://archive.org/metadata/{id}` → 过滤 `.mp3/.ogg/.m4a` → 拼 download 直链。

> ⚠️ 注意：archive.org 的检索结果里混有讲座/播客语音（例如 `title:(meditation)` 大量是 Dhamma talk），**不能直接把检索结果当氛围音乐用**，必须人工/规则筛选并固化为已验证清单，在线动态发现只作为「补充与更新」通道。

## 3. 硬约束（用户要求）

- **纯静态前端**：无后端、无构建步骤、无 API key、无服务端渲染；直接放 GitHub Pages 即可运行。
- **在线资源必须可用**：不能只放合成音；要有真实在线音乐/音频接入。
- **抗失效机制**：需要一套能动态获取 + 更新资源、链接挂了自动切换的机制。
- 场景覆盖：学习 / 助眠 / 放空 / 冥想（至少 4 类）。
- 全程联网调研、设计、开发、测试、**真实验证**，直到全部通过。

## 4. 交给架构师的决策提示（非设计结论，最终由架构师定）

1. 建议把音源分层：`合成层（永不失效）` → `本地已验证清单` → `远端动态清单（jsDelivr/GitHub Raw，带版本号与缓存）` → `运行时动态发现（archive.org / radio-browser）`。
2. 每条在线音源需多候选 URL + 播放错误/超时探测 + 自动降级到下一候选/合成层；健康度可持久化。
3. 清单更新机制可考虑一个仓库内脚本（如 GitHub Actions 定时探测 HEAD/Range，剔除失效项并回写 JSON），前端只负责拉取最新版。
4. 浏览器自动播放策略：AudioContext 与 `<audio>.play()` 必须在用户手势后触发/resume。
5. `<audio>` 播放跨域媒体不需要 CORS；但接入 Web Audio 做音量/淡入淡出分析时必须确保资源带 CORS 头 —— 已验证 archive.org / upload.wikimedia.org 满足。
6. 许可合规：Jamendo / CC 曲目需在界面标注来源与许可，并在清单里保留 `source` / `license` / `attribution` 字段。

## 5. 竞品调研方向（交给产品经理，已初步检索）

Calm、Headspace、Insight Timer、BetterSleep(Relax Melodies)、myNoise、Noisli、A Soft Murmur、Endel、Brain.fm、Medito、潮汐 Tide、小睡眠、Forest。
已观察到的共性能力：场景/声景分类、多声轨混音、独立音量、睡眠定时器 + 淡出、深色低刺激界面、呼吸引导、极简一键播放、离线/长时循环避免明显接缝。差异化机会：**免费 + 纯网页无需安装 + 音源自愈不失效 + 中文场景化**。

## 6. 追加实测：真实浏览器播放链路（2026-11-09）

用 Playwright 1.60 驱动本机真实 Google Chrome（headless，`--autoplay-policy=no-user-gesture-required`），以 `<audio crossorigin="anonymous" preload="metadata">` 加载已验证曲目，结果全部成功：

| 曲目 | 事件 | readyState | duration | error |
|---|---|---|---|---|
| `jamendo-002032/04.mp3` | loadstart → loadedmetadata → canplay | 4 | 250.40s | null |
| `jamendo-131817/...Eolian.mp3` | loadstart → loadedmetadata → canplay | 4 | 206.22s | null |
| `jamendo-132196/...Ambient Samurai...mp3` | loadstart → loadedmetadata → canplay | 4 | 59.03s | null |
| `aporee_73542_85947/...FieldAtNight...mp3` | loadstart → loadedmetadata → canplay | 4 | 132.00s | null |

结论：**302 重定向 + CORS `*` 的 archive.org 直链在真实 Chrome 中可被 `<audio>` 正常加载并拿到元数据**，不是只有 curl 能下载。同时验证了 `AudioContext` 在本环境可用。

## 7. 交付给团队的共享数据与环境事实

- `docs/00-verified-tracks.json`：30 首逐条实测可播曲目（21 首 CC 氛围音乐 + 9 首真实自然录音），字段含 `url / bytes / scene / display / originalTitle / license / item / source / kind`，场景分布 focus 6 / sleep 3 / empty 17 / meditation 4。**UI 应使用 `display` 中文名，不要把 `originalTitle` 直接暴露给用户**（原始标题含杂质）。
- 许可：Jamendo / aporee 均为 CC 授权，界面需给出来源与 item 链接署名；`license` 字段保留许可 URL，缺失时标注「CC，详见来源页」。
- 真实验证环境已确认：Playwright 1.60（`/opt/homebrew/opt/python@3.9/bin/python3.9`，`from playwright.sync_api import sync_playwright`，`p.chromium.launch(channel="chrome", headless=True)`），本机 Google Chrome / Firefox / Safari 均存在。QA 可直接用此链路做真实浏览器验证，无需额外安装。
- 前端运行时访问外网 API 需 CORS：已确认 `archive.org/advancedsearch.php`、`archive.org/metadata/*`、`archive.org/download/*`、`de1.api.radio-browser.info`、`cdn.jsdelivr.net`、`raw.githubusercontent.com`、`upload.wikimedia.org` 均返回 `Access-Control-Allow-Origin: *`；`commons.wikimedia.org/w/api.php` 与 SomaFM ICECast 流**不可用**。
- 清单动态更新的落地前提：远程清单地址（GitHub 仓库路径）在用户部署前是未知的，设计上必须允许「未配置远程源」时依然完整可用（本地快照 + 运行时动态发现 + 合成层兜底），并把远程地址做成一处可配置常量 + 提供仓库内更新脚本。

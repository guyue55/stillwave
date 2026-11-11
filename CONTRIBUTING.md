# 贡献指南

欢迎参与。这个项目最重要的约束不是「写得漂亮」，而是**绝不臆造资源、绝不破坏纯静态可用性、绝不打扰用户**。提交前请读完本文。

## 0. 三条不可协商的红线

1. **不引入构建步骤**：没有 `npm install`、没有打包器、没有框架运行时、没有 `node_modules`，`index.html` 必须能直接双击打开。
2. **不引入密钥或后端依赖**：前端不得出现 API key / token / 私有接口；新增资源必须可从浏览器匿名请求。
3. **不破坏低刺激体验**：不弹窗、不自动播放、不闪烁、不改用户音量、不在控制台报错；自愈链路必须静默完成且 ≤3 秒。

同时保持：`file://` 可用、GitHub Pages 子路径可用（本地资源一律 `./` 相对路径）、不使用 ES Modules（`window.SW` 单命名空间 + IIFE + 经典 `defer`）、首屏本地资源 < 300KB。

## 1. 新增一首曲目（最严格的流程）

曲库里的每一条链接都应能回答「你凭什么说它可用」。**禁止凭搜索结果或猜测直接写 URL**。

### 1.1 先做命令行实测

```bash
URL='https://archive.org/download/<identifier>/<file>.mp3'
curl -s -D - -o /dev/null -L --max-time 25 -H "Origin: https://guyue55.github.io" -r 0-1023 "$URL" \
  | grep -iE 'HTTP/|content-type|content-length|access-control-allow-origin|location'
```

必须同时满足：

- 最终响应为 `200` 或 `206`；
- `content-type` 为 `audio/*`（如 `audio/mpeg`）；
- 重定向链与最终响应都带 `Access-Control-Allow-Origin: *`（站点用 `crossOrigin="anonymous"` 把音频接入 Web Audio 增益总线，CORS 缺失会导致无声）；
- 体积合理（当前规则 500KB ~ 20MB）。

### 1.2 再做真实浏览器验证

在 Chrome 里创建 `<audio crossOrigin="anonymous">` 加载该 URL，确认 `readyState >= 1` 且 `duration > 0`。仅 `curl` 通过不足以入库 —— 有些链接会返回 HTML 页面或触发限流。

### 1.3 检查内容是否合适

本项目要的是**氛围音乐 / 自然环境声**，不要人声讲座、播客、导词、开示、新闻。archive.org 的 `title:(meditation)` 类检索会大量混入这些内容，务必人工试听或核对条目描述。`tools/refresh-sources.py` 的 `--discover` 已内置标题黑名单，但**动态发现的结果只进 `candidates[]`，恒定 `needsReview=true / verified=false`，0 条进入播放序列**。

### 1.4 核对许可

到 `item` 原始条目页确认许可。若含 `NC`（非商业）或 `ND`（禁止演绎），依然可以入库供个人聆听，但必须在 [NOTICE.md](./NOTICE.md) 的分布统计中体现。不要把许可不明的资源说成「公共领域」。

### 1.5 写入数据源并重新生成

权威源是 `docs/00-verified-tracks.json`，`data/` 下的两个文件由脚本生成，**不要手工编辑 `data/`**：

```bash
python3 tools/refresh-sources.py --init-from docs/00-verified-tracks.json --apply
python3 tools/refresh-sources.py --offline --dry-run   # 校验 json/js 同源、schema 合法
```

每条曲目必须包含：`id / url / bytes / scene / kind / display / originalTitle / license / item / source`。
`display` 为简体中文展示名（不含地名、编号、繁体、原始英文标题）；`originalTitle` 仅作数据层来源元数据，**UI 一律走 `sanitizeForUI()` 白名单投影**。

新增曲目会改变 `EXPECTED_COUNTS`（`tools/refresh-sources.py`）与 QA 中「四场景 6/3/17/4」「music=21 / nature=9」等断言，请同步更新并在提交说明里写清。

## 2. 修改前端代码

- 装载顺序固定为 `config → data/audio-sources.js → store → sources → synth → player → timer → ui → main`，见 `index.html`；新增脚本要评估插入位置与依赖。
- 状态只通过 `SW.store` 修改；展示层只消费 `UiTrack` 白名单字段。
- 音频要接入四级增益总线 `trackGain → mixBus → fadeGain → masterGain → destination`；定时渐弱只允许操作 `fadeGain`。
- 所有异常在模块内部吞掉，不使用裸 `console.error` / `alert` / `dialog`。
- 保持键盘可达、`aria` 同步、触控区 ≥44px、`prefers-reduced-motion` 动效归零。

## 3. 跑测试

```bash
cd qa
./run_all.sh --phase full --round 2
```

- 环境：Python 3.9+、Playwright 1.60、Google Chrome（`channel="chrome"`）。
- `qa/common.py` 会自动识别站点位于 `meditation/` 子目录还是仓库根。
- 静态契约与刷新脚本套件无需浏览器，可单独跑：

```bash
python3 -c "import test_static_contracts as t; print(t.run('full').summary())"
python3 -c "import test_refresh_script as t; print(t.run('full').summary())"
```

- 测试结果写入 `qa/results/`（已 gitignore）。**不要提交测试产物、截图或 `__pycache__`**。
- 若新增断言，请同时更新 `docs/04-qa-report.md` 的闸门映射；跨浏览器 / 长时验证若本环境无法执行，如实标 `UNVERIFIED`，**不得外推或伪造通过**。

## 4. 提交规范

- Commit message 使用中文或英文均可，简述「改了什么 + 为什么」，例如：`fix: 降级链路钳制单候选超时至剩余预算`。
- 一个 PR 只解决一件事；涉及 `data/` 的变更必须附上实测命令与输出摘要。
- 涉及音频资源的 PR 必须附上 `curl` 响应头与浏览器 `readyState / duration` 证据。
- 提交前确认：`file://` 双击可播、控制台零错误、30 首清单未被清空、`data/*.json` 与 `data/*.js` 同源。

/* ==========================================================================
 * 静澜 Stillwave · js/main.js
 * 职责：引导装配（init 顺序）、首次用户手势解锁 AudioContext、
 *       visibilitychange 前台状态提示、挂载 window.__STILLWAVE__ 测试契约、
 *       ?debug=1 故障注入开关、控制台清洁统计、静默后台清单探测、
 *       v1.1：A14 全站可见文本真实 DOM 扫描与分享文案契约。
 * 约束：原始标题清单只存在于 sources 数据层；契约层只传可见文本、不接触源标题（AD-21）。
 * 装载：第 9 位（最后）。
 * ========================================================================== */
;(function () {
  'use strict';

  var SW = (window.SW = window.SW || {});
  var C = SW.config;
  var E = C.EVENTS;
  var store = SW.store;
  var sources = SW.sources;
  var synth = SW.synth;
  var player = SW.player;
  var timer = SW.timer;
  var ui = SW.ui;

  var firstGestureBound = false;

  /** 统计控制台 error / 未捕获异常（A6 断言 consoleErrorCount === 0）。 */
  function installErrorCounter() {
    var original = null;
    try {
      if (window.console && typeof window.console.error === 'function') {
        original = window.console.error;
        window.console.error = function () {
          SW.RUNTIME.consoleErrorCount += 1;
          try { return original.apply(window.console, arguments); } catch (err) { return undefined; }
        };
      }
    } catch (err) { /* 静默 */ }
    window.addEventListener('error', function () { SW.RUNTIME.consoleErrorCount += 1; });
    window.addEventListener('unhandledrejection', function () { SW.RUNTIME.consoleErrorCount += 1; });
  }

  /**
   * 首次用户手势：仅创建并 resume AudioContext（静默，不发声、不自动播放）。
   * 真正的出声由播放按钮 / 场景 Tab 触发的 player.startFromGesture 完成（F1 / P0-11）。
   */
  function bindFirstGesture() {
    if (firstGestureBound) { return; }
    firstGestureBound = true;
    var handled = false;
    function onGesture(ev) {
      if (handled) { return; }
      /* P0-3：分享是「读配置」动作，不是音频意图。分享按钮与分享面板内的任何操作
         （含在面板输入框里按 Escape 收起）都不解锁 AudioContext，分享路径因此严格
         零 AudioContext（硬边界 3）；监听器保留，下一次真实音频意图
         （点播放 / 切场景 / Tab 进入控件）照常静默解锁。 */
      var target = ev && ev.target;
      if (target && typeof target.closest === 'function'
          && target.closest('#btn-share, #share-panel')) { return; }
      handled = true;
      document.removeEventListener('pointerdown', onGesture, true);
      document.removeEventListener('keydown', onGesture, true);
      document.removeEventListener('touchstart', onGesture, true);
      synth.ensureContext().catch(function () { /* 静默，绝不外抛 */ });
      store.pushLog({ type: 'gesture', action: 'audio-unlocked' });
    }
    document.addEventListener('pointerdown', onGesture, true);
    document.addEventListener('keydown', onGesture, true);
    document.addEventListener('touchstart', onGesture, true);
  }

  /** 标签页回到前台给出明确状态，不伪装成支持系统级后台播放（R-08）。 */
  function bindVisibility() {
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible' && store.getState().playing) {
        ui.toast('已回到前台，声音继续');
      }
    });
  }

  /** 启动后静默后台探测远端清单（file:// 与未配置时连请求都不发起，AD-15）。 */
  function scheduleSilentRefresh() {
    function go() {
      if (!C.resolvedRemotes || !C.resolvedRemotes.length) { return; }
      try { if (window.location.protocol === 'file:') { return; } } catch (err) { return; }
      if (SW.RUNTIME.offline) { return; }
      sources.refresh({ silent: true }).catch(function () { /* 静默 */ });
    }
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(go, { timeout: 5000 });
    } else {
      window.setTimeout(go, 1200);
    }
  }

  /**
   * A14 第四处「分享文案」：只由曲目的 display 组装。
   * 绝不拼入源标题、裸 URL 文本、错误码或任何用户标识（S-10 / P0-09 / AD-25）。
   * @returns {string}
   */
  function getShareText() {
    var state = store.getState();
    var names = [];
    (state.tracks || []).forEach(function (slot) {
      var view = sources.sanitizeForUI(slot);
      if (view.display && names.indexOf(view.display) < 0) { names.push(view.display); }
    });
    if (!names.length) {
      var pool = sources.getTracks();
      if (pool.length) {
        var fallback = sources.sanitizeForUI(pool[0]);
        if (fallback.display) { names.push(fallback.display); }
      }
    }
    if (!names.length) { names.push('本地合成声'); }
    return '正在聆听：' + names.join('、');
  }

  /* —— P0-3 URL 分享状态：编码 / 解析 / 还原 ——————————————————————————————
     格式（冻结）：#sw=1&s=<scene>&mv=<0..100>&tr=<seg>|<seg>|<seg>
       seg = t:<trackId>:<0..100> | v:<voiceId>:<0..100>
     硬边界：
     - 只读配置态，任何路径都不创建 / 恢复 AudioContext、不调 play()（硬边界 3）。
     - 一切外部输入按「白名单 + 逐字段容错」处理，异常整条吞掉，绝不白屏。
     - 解析结果只喂给 player.applyMix()，不自行 patch store；hash 原文绝不进 DOM。 */

  var SHARE_HASH_MAX = 300;    // 超过即整条忽略（防御超长 hash）
  var SHARE_THROTTLE_MS = 150; // 粘贴新链接时的抖动合并窗口（尾部补发，不丢最后一次）

  /** 安全解码：畸形的 % 序列原样返回，绝不抛错。 */
  function safeDecode(value) {
    var text = String(value == null ? '' : value);
    try { return decodeURIComponent(text); } catch (err) { return text; }
  }

  /** 把 hash（可带 #）解析成键值表；重复键取首个，畸形片段跳过。 */
  function splitHashParams(body) {
    var out = {};
    var chunks = String(body == null ? '' : body).split('&');
    for (var i = 0; i < chunks.length; i += 1) {
      if (!chunks[i]) { continue; }
      var eq = chunks[i].indexOf('=');
      var key = safeDecode(eq < 0 ? chunks[i] : chunks[i].slice(0, eq));
      if (!key || Object.prototype.hasOwnProperty.call(out, key)) { continue; }
      out[key] = safeDecode(eq < 0 ? '' : chunks[i].slice(eq + 1));
    }
    return out;
  }

  /** 0..100 百分比 → 0..1；非数字返回 null（由调用方决定「忽略字段」还是「丢弃该段」）。 */
  function parsePercent(text) {
    if (text === null || text === undefined) { return null; }
    var raw = String(text).trim();
    if (!/^\d+(?:\.\d+)?$/.test(raw)) { return null; }
    var num = Number(raw);
    if (!isFinite(num)) { return null; }
    return Math.max(0, Math.min(100, num)) / 100;
  }

  /** 0..1 → 0..100 整数（生成链接用）。 */
  function toPercent(value) {
    var num = Number(value);
    if (!isFinite(num)) { num = 0; }
    return Math.round(Math.max(0, Math.min(1, num)) * 100);
  }

  /** 当前清单白名单：只有清单里真实存在的曲目 id 才允许从 URL 还原。 */
  function trackIdWhitelist() {
    var set = Object.create(null);
    try {
      var manifest = sources.getManifest();
      var list = manifest && manifest.tracks ? manifest.tracks : [];
      for (var i = 0; i < list.length; i += 1) {
        if (list[i] && typeof list[i].id === 'string' && list[i].id) { set[list[i].id] = true; }
      }
    } catch (err) { /* 清单不可用 → 空白名单，全部 t: 段被丢弃 */ }
    return set;
  }

  /**
   * 解析单个 tr 段。任何非法都返回 null，绝不影响其它段。
   * @param {string} seg 形如 t:<trackId>:<0..100> / v:<voiceId>:<0..100>
   * @param {Object} white 曲目 id 白名单
   * @param {number} index 该段在 tr 中的原始下标
   * @returns {Object|null}
   */
  function parseShareSegment(seg, white, index) {
    var parts = String(seg == null ? '' : seg).split(':');
    if (parts.length !== 3) { return null; }
    var volume = parsePercent(parts[2]);
    if (volume === null) { return null; }
    var id = parts[1];
    if (!id) { return null; }
    if (parts[0] === 't') {
      /* 与 player.sanitizeMix 同一口径：只有首段可作在线主音轨，否则会被静默丢弃、
         导致「链接里明明有这首曲子，还原后却不见了」。这里直接判非法并记录丢弃。 */
      if (index > 0) { return null; }
      if (white[id] !== true) { return null; }
      return { kind: 'track', trackId: id, volume: volume };
    }
    if (parts[0] === 'v') {
      if (C.SYNTH_VOICES.indexOf(id) < 0) { return null; }
      return { kind: 'voice', voice: id, volume: volume };
    }
    return null;
  }

  /**
   * 解析分享 hash（只读快照，供还原与 QA 契约共用）。
   *
   * 返回结构（QA 契约）：
   *   ok      —— 是否产出了可用 spec（缺 sw / sw≠1 / 超长 / 空 → false）
   *   reason  —— 'ok' | 'no-hash' | 'too-long' | 'no-flag'
   *   scene   —— 已解析并校验过的场景（非法时回落当前场景，恒为合法值）
   *   spec    —— {scene, masterVolume, tracks}；整条忽略时为 null
   *   dropped —— 被丢弃的原始段文本（逐段容错的可观测证据，绝不进 DOM）
   *
   * 字段级容错：s 非法 → 当前场景；mv 非数字 → 当前主音量；mv/vol 越界 → 钳制；
   * 段非法 → 只丢该段；段数 > MAX_TRACKS → 只取前 3 段；全程不抛错。
   * @param {string} hash location.hash（可带 #）
   * @returns {{ok:boolean, reason:string, scene:(string|null), spec:(Object|null), dropped:string[]}}
   */
  function parseShareHash(hash) {
    var result = { ok: false, reason: 'no-hash', scene: null, spec: null, dropped: [] };
    var body = String(hash == null ? '' : hash);
    if (body.charAt(0) === '#') { body = body.slice(1); }
    if (!body) { return result; }
    if (body.length > SHARE_HASH_MAX) {
      result.reason = 'too-long';
      return result;
    }
    var params = splitHashParams(body);
    if (params.sw !== '1') {
      result.reason = 'no-flag';
      return result;
    }

    var current = store.getState();
    var scene = (params.s && C.SCENE_IDS.indexOf(params.s) >= 0) ? params.s : current.scene;
    if (C.SCENE_IDS.indexOf(scene) < 0) { scene = C.SCENE_IDS[0]; }
    var parsedMaster = parsePercent(params.mv);
    var masterVolume = parsedMaster === null ? current.masterVolume : parsedMaster;

    var tracks = [];
    if (params.tr) {
      var white = trackIdWhitelist();
      var segs = String(params.tr).split('|');
      /* 段数 > MAX_TRACKS 只取前 3 段；单段非法只丢该段 */
      for (var i = 0; i < segs.length && i < C.MAX_TRACKS; i += 1) {
        if (!segs[i]) { continue; }
        var parsed = parseShareSegment(segs[i], white, i);
        if (parsed) { tracks.push(parsed); } else { result.dropped.push(segs[i]); }
      }
    }

    result.ok = true;
    result.reason = 'ok';
    result.scene = scene;
    result.spec = { scene: scene, masterVolume: masterVolume, tracks: tracks };
    return result;
  }

  /**
   * 把 mix spec 编码成分享 hash（严格按冻结格式；全部数值 ×100 取整）。
   * @param {Object} [spec] 默认取 player.getMixSpec()
   * @returns {string} 形如 #sw=1&s=sleep&mv=60&tr=v:rain:33|v:brown:21（失败返回 ''）
   */
  function getShareHash(spec) {
    var mix = null;
    try {
      mix = (spec && typeof spec === 'object') ? spec : player.getMixSpec();
    } catch (err) { return ''; }
    if (!mix || !mix.tracks) { return ''; }
    var scene = C.SCENE_IDS.indexOf(mix.scene) >= 0 ? mix.scene : store.getState().scene;
    var parts = ['sw=1', 's=' + encodeURIComponent(scene), 'mv=' + toPercent(mix.masterVolume)];
    var segs = [];
    var list = mix.tracks || [];
    for (var i = 0; i < list.length && segs.length < C.MAX_TRACKS; i += 1) {
      var t = list[i] || {};
      if (t.kind === 'track' && t.trackId) {
        if (segs.length > 0) { continue; }  // 与解析端同口径：t: 只允许出现在首段
        segs.push('t:' + encodeURIComponent(String(t.trackId)) + ':' + toPercent(t.volume));
      } else if (t.kind === 'voice' && t.voice) {
        segs.push('v:' + encodeURIComponent(String(t.voice)) + ':' + toPercent(t.volume));
      }
    }
    if (segs.length) { parts.push('tr=' + segs.join('|')); }
    return '#' + parts.join('&');
  }

  /**
   * 解析当前地址栏 hash 并还原配置：只改配置态，绝不创建 AudioContext / 绝不播放。
   * @returns {{ok:boolean, mode?:string, scene?:string, reason?:string}}
   */
  function restoreFromHash() {
    var parsed = null;
    try { parsed = parseShareHash(window.location.hash); } catch (err) { parsed = null; }
    if (!parsed || !parsed.ok || !parsed.spec) {
      return { ok: false, reason: (parsed && parsed.reason) || 'ignored' };
    }

    var scene = parsed.spec.scene;
    var masterVolume = parsed.spec.masterVolume;
    var tracks = parsed.spec.tracks;
    var mode = 'mix';

    if (!tracks.length) {
      /* 「全部段都非法 / 链接没带 tr」时不传空 tracks：
         已启动时 applyMix 会走 reconcileLayers，把用户当前的叠加层逐个移除，
         等于一条半残链接把本地混音清空——这是破坏性回退，违反「坏输入只降级不破坏」。
         改为复用当前混音轨，场景与主音量照常还原，本地层原样保留。 */
      mode = 'scene-volume';
      try {
        tracks = player.getMixSpec().tracks.slice(0, C.MAX_TRACKS);
      } catch (err) { tracks = []; }
    }

    var result = null;
    /* 还原全程挂起「偏好回写」：applyMix 内的 applyScene / applySceneConfigOnly /
       setMasterVolume / syncSlots 都会调 store.savePrefs()，若不挂起，
       访问者只是点了别人的链接，本地偏好就被永久改写成对方的配置（审计实证）。
       语义：分享链接只对本次会话生效；访问者此后主动操作产生的写入照常持久化。 */
    try {
      store.holdPrefs();
      result = player.applyMix({ scene: scene, masterVolume: masterVolume, tracks: tracks });
    } catch (err) {
      result = { ok: false, reason: 'exception' };
    } finally {
      store.releasePrefs();
    }
    if (!result || !result.ok) {
      /* 静默回退：不抛错、不弹窗、不修改既有状态，只留一条事件日志（不含 hash 原文） */
      store.pushLog({
        type: 'share', action: 'restore-skipped',
        reason: (result && result.reason) || 'unknown'
      });
      return { ok: false, reason: 'apply' };
    }
    store.pushLog({
      type: 'share', action: 'restored', mode: mode,
      scene: scene, tracks: tracks.length, pending: !!result.pending,
      prefsHeld: store.getPrefsWriteStats().skipped
    });
    return { ok: true, mode: mode, scene: scene };
  }

  /**
   * 同一标签页内粘贴新链接：节流 150ms 后还原，同样不自动播放。
   * 口径：距上次处理已过窗口 → 立即还原；窗口内 → 合并为一次尾部补发，
   * 保证「最后一次 hash」一定被处理，也保证连续 hashchange 不会触发连环渲染。
   */
  function bindHashChange() {
    var hashThrottleTimer = null;
    var lastHashAt = 0;
    window.addEventListener('hashchange', function () {
      var now = Date.now();
      var wait = SHARE_THROTTLE_MS - (now - lastHashAt);
      if (wait <= 0) {
        lastHashAt = now;
        restoreFromHash();
        return;
      }
      if (hashThrottleTimer !== null) { window.clearTimeout(hashThrottleTimer); }
      hashThrottleTimer = window.setTimeout(function () {
        hashThrottleTimer = null;
        lastHashAt = Date.now();
        restoreFromHash();
      }, wait);
    });
  }

  /**
   * A14 真实 DOM 扫描：渲染后可见文本 + 全部元素的 aria-label / title / alt / placeholder
   * + 页面标题。body.innerText 天然排除 script / style / hidden / aria-hidden 节点；
   * 额外扫描属性文本（含折叠区），使「零泄露」判定比可见文本更严格。
   * @returns {string}
   */
  function collectVisibleText() {
    var parts = [];
    var body = document.body;
    if (!body) { return ''; }
    if (typeof body.innerText === 'string') { parts.push(body.innerText); }
    else if (typeof body.textContent === 'string') { parts.push(body.textContent); }
    var attrs = ['aria-label', 'title', 'alt', 'placeholder'];
    var nodes = body.querySelectorAll('*');
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      var tag = node.tagName ? node.tagName.toUpperCase() : '';
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT' ||
          tag === 'TEMPLATE' || tag === 'SVG') { continue; }
      for (var j = 0; j < attrs.length; j += 1) {
        var value = node.getAttribute(attrs[j]);
        if (value && value.trim()) { parts.push(value.trim()); }
      }
    }
    if (document.title) { parts.push(document.title); }
    return parts.join('\n');
  }

  /**
   * A14 四处曲目名的真实 DOM 扫描：
   * player = 播放条 #now-title；mixer = 混音卡片名；details = 详情面板许可清单（data 属性）；
   * share = getShareText()。四处均来自白名单投影的 display。
   * @returns {{player:string, mixer:string[], details:string[], share:string}}
   */
  function collectTrackNames() {
    var now = document.getElementById('now-title');
    var mixerNames = [];
    var mixerNodes = document.querySelectorAll('.mix-card-name');
    for (var i = 0; i < mixerNodes.length; i += 1) {
      var text = (mixerNodes[i].textContent || '').replace('（主音源）', '').trim();
      if (text) { mixerNames.push(text); }
    }
    var detailNames = [];
    var detailNodes = document.querySelectorAll('#details-panel [data-track-name]');
    for (var k = 0; k < detailNodes.length; k += 1) {
      var name = detailNodes[k].getAttribute('data-track-name');
      if (name) { detailNames.push(name); }
    }
    return {
      player: now ? (now.textContent || '').trim() : '',
      mixer: mixerNames,
      details: detailNames,
      share: getShareText()
    };
  }

  /**
   * A14 / P0-18 全站零泄露快照（§4.5）。
   * 本函数真实扫描 DOM；命中检测委托 SW.sources.buildVisibleTextSnapshot()——
   * 原始标题清单只存在于数据层，展示层与契约层在架构上拿不到源标题（AD-21），
   * 由数据层真实遍历 30 条源标题与杂质词表后填充命中数组（非硬编码空数组）。
   * @returns {Object} 快照对象：可见文本、四处曲目名、源标题命中数组、杂质命中数组；
   *          具体键名按架构 §4.5 冻结契约，由数据层审计函数产出（本层不接触源标题）
   */
  function getVisibleTextSnapshot() {
    var visible = collectVisibleText();
    var names = collectTrackNames();
    return sources.buildVisibleTextSnapshot(visible, names);
  }

  /** 把内部状态聚合为 QA 只读快照（§4.5 getState）。 */
  function getDebugState() {
    var s = store.getState();
    var gain = synth.getEffectiveGain();
    var ctx = synth.getContext();
    var audioContext = 'none';
    if (ctx) {
      if (ctx.state === 'running') { audioContext = 'running'; }
      else if (ctx.state === 'suspended' || ctx.state === 'interrupted') { audioContext = 'suspended'; }
      else { audioContext = 'closed'; }
    }
    /* A10 / A14 查证视图：取当前主音源；未就绪时退回清单首条，恒为 AttributionView */
    var attrId = (s.currentSource && s.currentSource.trackId) ||
      (s.tracks.length && s.tracks[0].trackId) || null;
    if (!attrId) {
      var pool = sources.getTracks();
      attrId = pool.length ? pool[0].id : null;
    }
    return {
      playState: s.playState,
      playing: s.playing,
      scene: s.scene,
      masterVolume: s.masterVolume,
      activeTrackCount: player.getActiveTrackCount(),
      tracks: s.tracks.map(function (t) {
        return {
          id: t.id, kind: t.kind, volume: t.volume,
          display: t.display, url: t.url || undefined,
          voice: t.voice || undefined, trackId: t.trackId || undefined
        };
      }),
      sourceTier: s.sourceTier,
      badge: s.badge,
      badgeText: s.badgeText,
      currentSource: {
        trackId: s.currentSource.trackId,
        url: s.currentSource.url,
        tier: s.currentSource.tier,
        status: s.currentSource.status
      },
      attribution: attrId ? sources.getAttribution(attrId) : null,
      audioContext: audioContext,
      manifest: {
        version: s.manifest.version, updatedAt: s.manifest.updatedAt,
        count: s.manifest.count, source: s.manifest.source
      },
      remoteConfigured: C.REMOTE_MANIFEST !== null,
      resolvedRemotes: C.resolvedRemotes.slice(),
      health: sources.getHealth(),
      timer: timer.getState(),
      brightness: s.brightness,
      reducedMotion: s.reducedMotion,
      autoDrift: s.autoDrift,
      breath: s.breath,
      libraryStatus: s.libraryStatus,
      effectiveGain: { master: gain.master, fade: gain.fade },
      lastDegradeDurationMs: SW.RUNTIME.lastDegradeDurationMs,
      degradedEvents: SW.RUNTIME.degradeEvents.slice(),
      consoleErrorCount: SW.RUNTIME.consoleErrorCount,
      storageMode: store.getStorageMode(),
      debugEnabled: C.DEBUG
    };
  }

  /** 受控动作（等价于用户操作，供自动化驱动）。 */
  function buildActions() {
    return {
      start: function () { return player.startFromGesture(); },
      setScene: function (id) { return player.applyScene(id); },
      play: function () { return player.play(); },
      pause: function () { player.pause(); },
      nextTrack: function () {
        if (store.getState().playState === 'idle') {
          return player.startFromGesture().then(function () { player.nextTrack(); });
        }
        player.nextTrack();
        return Promise.resolve();
      },
      selectTrack: function (id) {
        if (store.getState().playState === 'idle') {
          return player.startFromGesture().then(function () { return player.selectTrack(id); });
        }
        return Promise.resolve(player.selectTrack(id));
      },
      setLibraryFilter: function (scene, kind) { ui.setLibraryFilter(scene, kind); },
      setMasterVolume: function (v) { player.setMasterVolume(v); },
      /* P0-2 收藏与混音预设：与用户点击等价，供自动化驱动 */
      toggleFavorite: function (id) { return store.toggleFavorite(id); },
      savePreset: function (name) {
        var mix = player.getMixSpec();
        var spec = {
          name: name, scene: mix.scene, masterVolume: mix.masterVolume,
          tracks: mix.tracks
        };
        return store.savePreset(spec);
      },
      deletePreset: function (index) { return store.deletePreset(index); },
      applyMix: function (spec) { return player.applyMix(spec); },
      addTrack: function (voice) {
        if (store.getState().playState === 'idle') {
          return player.startFromGesture().then(function () { return player.addTrack(voice); });
        }
        return Promise.resolve(player.addTrack(voice));
      },
      removeTrack: function (id) { player.removeTrack(id); },
      setTimer: function (minutes, fadeSeconds) { timer.start(minutes, fadeSeconds); },
      cancelTimer: function () { timer.cancel(); },
      setBrightness: function (b) { ui.setBrightness(b); },
      refreshLibrary: function () { return sources.refresh({ silent: false }); },
      clearStorage: function () {
        store.clearAll();
        sources.resetHealth();
      },
      /* P0-3：与点击 #btn-share 完全等价（写地址栏 + 复制 + 轻提示，绝不播放）。
         返回 Promise<{ok, hash, mode, url}>：剪贴板写入天生异步，用 Promise 表达真实时序，
         Playwright 的 evaluate 会自动 await。 */
      copyShareLink: function () { return ui.copyShareLink(); }
    };
  }

  /** 受控故障注入（仅 ?debug=1 挂载，AD-08）。 */
  function buildInject() {
    return {
      setManifestOverride: function (tracks) {
        var overrides = {};
        (tracks || []).forEach(function (item) {
          if (item && item.id && item.url) { overrides[item.id] = item.url; }
        });
        SW.RUNTIME.manifestOverrides = overrides;
      },
      resetManifestOverride: function () { SW.RUNTIME.manifestOverrides = {}; },
      setLoadTimeout: function (ms) {
        SW.RUNTIME.loadTimeoutMs = Math.max(50, Number(ms) || C.LOAD_TIMEOUT_MS);
      },
      forceTimeoutNext: function (n) {
        SW.RUNTIME.forceTimeoutNext = Math.max(0, Number(n) || 0);
      },
      forceFailureOnce: function (kind) {
        player.debugInjectFailure(kind === '404' ? '404' : (kind === 'network' ? 'network' : 'timeout'));
      },
      setOffline: function (flag) { player.debugForceOffline(!!flag); },
      setStorageUnavailable: function (flag) {
        SW.RUNTIME.storageUnavailable = !!flag;
        store.patch({});
      },
      forceTier: function (tier) { player.debugForceTier(tier === 'online' ? 'online' : 'synth'); },
      resetHealth: function () { sources.resetHealth(); }
    };
  }

  /** 挂载 window.__STILLWAVE__ 契约（只读状态始终可用；inject 仅 debug=1）。 */
  function mountDebugContract() {
    var contract = {
      version: 'stillwave-debug/1',
      debugEnabled: C.DEBUG,
      getState: getDebugState,
      getEventLog: function () { return store.getLog(); },
      getUiSnapshot: function () { return ui.getUiSnapshot(); },
      getLibrarySnapshot: function () { return ui.getLibrarySnapshot(); },
      /* P0-2：收藏与预设的只读快照（白名单投影，不含任何存储内部结构） */
      getFavoritesSnapshot: function () { return ui.getFavoritesSnapshot(); },
      getPresetsSnapshot: function () { return ui.getPresetsSnapshot(); },
      getMixSpec: function () { return player.getMixSpec(); },
      getAttribution: function (trackId) { return sources.getAttribution(trackId); },
      getManifestSummary: function () { return sources.getManifestSummary(); },
      /* v1.1 / A13 / A14 新增四个数据层契约入口 */
      sanitizeForUI: function (trackOrId) { return sources.sanitizeForUI(trackOrId); },
      resolveCandidates: function (trackId) { return sources.resolveCandidates(trackId); },
      getShareText: getShareText,
      getVisibleTextSnapshot: getVisibleTextSnapshot,
      /* P0-3：分享链接的只读快照（纯编码结果，不含任何存储 / 音频内部结构） */
      getShareHash: function () { return getShareHash(player.getMixSpec()); },
      parseShareHash: function (hash) { return parseShareHash(hash); },
      getShareLink: function () {
        return { hash: getShareHash(player.getMixSpec()), scene: store.getState().scene };
      },
      actions: buildActions()
    };
    if (C.DEBUG) { contract.inject = buildInject(); }
    window.__STILLWAVE__ = contract;
    store.pushLog({ type: 'contract', action: 'mounted', debug: C.DEBUG });
  }

  /** 引导装配（顺序即依赖顺序）。 */
  function init() {
    installErrorCounter();
    store.loadPrefs();          // 1. 还原偏好（localStorage 不可用时静默内存降级）
    sources.init();             // 2. 载入内置 30 首快照（零 fetch）+ 健康度 + 缓存清单
    /* 3. P0-3：解析 #sw=... 并还原配置态。必须在 sources.init() 之后（t: 段要查
       曲目白名单）且 ui.init() 之前（UI 首次渲染即反映还原后的 store）；只改配置、
       不建 AudioContext、不播放。 */
    restoreFromHash();
    ui.init();                  // 4. 绑定 DOM / aria / 订阅 store / 呼吸圆环 / 快捷键
    bindHashChange();           // 5. 同标签页粘贴新链接 → 节流 150ms 还原（同样不播放）
    bindFirstGesture();         // 6. 首次手势解锁 AudioContext（静默）
    bindVisibility();           // 7. 前台恢复提示
    mountDebugContract();       // 8. 挂载 QA 契约
    store.pushLog({ type: 'main', action: 'ready', schema: C.MANIFEST_SCHEMA });
    scheduleSilentRefresh();    // 9. 可选后台探测（未配置 / file:// 时完全跳过）
  }

  SW.main = {
    init: init,
    /* P0-3：纯编码 / 解析 / 还原（UI 只调用这里，不自己拼 hash） */
    getShareHash: getShareHash,
    parseShareHash: parseShareHash,
    restoreFromHash: restoreFromHash
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

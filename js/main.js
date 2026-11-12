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
    function onGesture() {
      if (handled) { return; }
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
      }
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
      getAttribution: function (trackId) { return sources.getAttribution(trackId); },
      getManifestSummary: function () { return sources.getManifestSummary(); },
      /* v1.1 / A13 / A14 新增四个数据层契约入口 */
      sanitizeForUI: function (trackOrId) { return sources.sanitizeForUI(trackOrId); },
      resolveCandidates: function (trackId) { return sources.resolveCandidates(trackId); },
      getShareText: getShareText,
      getVisibleTextSnapshot: getVisibleTextSnapshot,
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
    ui.init();                  // 3. 绑定 DOM / aria / 订阅 store / 呼吸圆环 / 快捷键
    bindFirstGesture();         // 4. 首次手势解锁 AudioContext（静默）
    bindVisibility();           // 5. 前台恢复提示
    mountDebugContract();       // 6. 挂载 QA 契约
    store.pushLog({ type: 'main', action: 'ready', schema: C.MANIFEST_SCHEMA });
    scheduleSilentRefresh();    // 7. 可选后台探测（未配置 / file:// 时完全跳过）
  }

  SW.main = { init: init };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

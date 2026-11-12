/* ==========================================================================
 * 静澜 Stillwave · js/player.js
 * 职责：播放引擎。首次手势「先出声、再升级」、≤3 轨混音（audio + synth 统一总线）、
 *       分轨/主音量相乘、≥600ms 场景 crossfade、完整自愈链路（多候选 / 超时 /
 *       error / stalled / 断网 → 合成层兜底）、换一曲、资源释放、自动漂移。
 * 硬约束：整条自愈链路不写 playing、不改 masterGain / trackGain 用户设定值、
 *         不弹窗、不自动暂停、不 console.error（P0-06 / P0-14 / §2.6.4）。
 * 装载：第 6 位。
 * ========================================================================== */
;(function () {
  'use strict';

  var SW = (window.SW = window.SW || {});
  var C = SW.config;
  var E = C.EVENTS;
  var store = SW.store;
  var synth = SW.synth;
  var sources = SW.sources;

  var started = false;
  var graph = null;
  var slots = [];                 // TrackSlot[]（≤3）
  var handles = Object.create(null); // slotId -> VoiceHandle
  var pendingReleases = [];       // 待淡出完成后释放的 handle
  var releaseTimers = [];
  var mainUpgradeToken = 0;
  var currentMainTrackId = null;
  var currentMainUrl = null;
  var activeDegradeStart = null;
  var driftTimer = null;
  var progress = { currentTime: 0, duration: 0 };
  /* 整条自愈链路的总预算：从首次故障起必须 ≤3s 内给出结果（P0-06 / AD-16），
     避免 30 个候选串行超时累加成数十秒静默等待。留 200ms 余量保证断言不越界。 */
  var DEGRADE_BUDGET_MS = Math.max(500, C.LOAD_TIMEOUT_MS - 200);

  /** 复制 slot 供 store（避免外部持有可变引用）。 */
  function copySlot(s) { return Object.assign({}, s); }

  /** 同步混音轨到 store 并持久化（P0-12）。 */
  function syncSlots() {
    store.patch({ tracks: slots.map(copySlot) });
    store.savePrefs();
  }

  /** 按 id 查找 slot。 */
  function findSlot(id) {
    for (var i = 0; i < slots.length; i += 1) { if (slots[i].id === id) { return slots[i]; } }
    return null;
  }

  /** 更新主音源 slot 字段。 */
  function patchMainSlot(partial) {
    var s = findSlot('main');
    if (!s) { return; }
    Object.assign(s, partial);
    syncSlots();
  }

  /** 从清单查询 display（AD-21：只读白名单投影的 display，展示层零源标题）。 */
  function displayOf(trackId) {
    var m = sources.getManifest();
    if (!m) { return '本地合成声'; }
    for (var i = 0; i < m.tracks.length; i += 1) {
      if (m.tracks[i].id === trackId) { return m.tracks[i].display; }
    }
    return '本地合成声';
  }

  /** 默认主音源（晨雾，kind:music，A11）。 */
  function defaultMainTrackId() {
    var preset = C.SCENES[store.getState().scene] || C.SCENES.focus;
    if (preset.mainTrackId) { return preset.mainTrackId; }
    var list = sources.getTracks(preset.id).filter(function (t) { return t.kind === 'music'; });
    return list.length ? list[0].id : 'jamendo-122281';
  }

  /** 按场景处方生成轨道描述（主音源垫声 + 叠加声景层）。 */
  function buildSceneSlots(scene) {
    var p = C.SCENES[scene] || C.SCENES.focus;
    var mainVolume = p.mainTrackId ? 1.0 : 0.06; // 冥想场景「极轻底噪」
    var out = [{
      id: 'main', kind: 'synth', voice: p.padVoice, trackId: p.mainTrackId,
      volume: mainVolume, display: '本地合成声', url: null
    }];
    p.layers.forEach(function (layer, i) {
      out.push({
        id: 'layer-' + i, kind: 'synth', voice: layer.voice, trackId: null,
        volume: layer.volume, display: C.VOICE_LABELS[layer.voice] || layer.voice, url: null
      });
    });
    return out;
  }

  /** 延时释放已淡出的 handle（避免爆音与双声重叠）。 */
  function scheduleRelease(list, delayMs) {
    if (!list || !list.length) { return; }
    list.forEach(function (h) { if (h) { pendingReleases.push(h); } });
    var timer = window.setTimeout(function () {
      list.forEach(function (h) {
        if (!h) { return; }
        var idx = pendingReleases.indexOf(h);
        if (idx >= 0) { pendingReleases.splice(idx, 1); }
        synth.releaseVoice(h);
      });
      var ti = releaseTimers.indexOf(timer);
      if (ti >= 0) { releaseTimers.splice(ti, 1); }
    }, Math.max(0, delayMs || 0));
    releaseTimers.push(timer);
  }

  /** 记录一次降级（口径：故障墙钟时刻 → 新源就绪，AD-16）。 */
  function recordDegrade(reason, fromTier, toTier, startAt) {
    var duration = Math.max(0, Date.now() - (startAt || Date.now()));
    SW.RUNTIME.lastDegradeDurationMs = duration;
    var event = {
      at: new Date().toISOString(), reason: String(reason || 'unknown'),
      fromTier: fromTier || 'bundled', toTier: toTier || 'synth',
      durationMs: duration
    };
    SW.RUNTIME.degradeEvents.push(event);
    if (SW.RUNTIME.degradeEvents.length > C.LOG_LIMIT) { SW.RUNTIME.degradeEvents.shift(); }
    store.pushLog({
      type: 'degrade', reason: event.reason, fromTier: event.fromTier,
      toTier: event.toTier, durationMs: duration
    });
  }

  /** 消费一次性故障注入（404 / timeout / network）。 */
  function consumeInjection() {
    if (SW.RUNTIME.forceFailureOnce) {
      var kind = SW.RUNTIME.forceFailureOnce;
      SW.RUNTIME.forceFailureOnce = null;
      return kind === '404' ? '404' : kind;
    }
    if (SW.RUNTIME.forceTimeoutNext > 0) {
      SW.RUNTIME.forceTimeoutNext -= 1;
      return 'timeout';
    }
    return null;
  }

  /**
   * 把已就绪的在线音源接入统一总线并淡入；合成垫声同步淡出（≥600ms crossfade）。
   * @param {HTMLAudioElement} el
   * @param {string} url
   * @param {Object|null} track
   * @param {Object} ctx 升级上下文
   */
  function attachOnline(el, url, track, ctx) {
    var preset = C.SCENES[store.getState().scene] || C.SCENES.focus;
    var main = findSlot('main');
    var targetVolume = main ? main.volume : 1.0;
    var old = handles['main'];
    if (old) {
      try { synth.rampGain(old.trackGain.gain, 0, C.CROSSFADE_MS); } catch (err) { /* 静默 */ }
      scheduleRelease([old], C.CROSSFADE_MS + 120);
    }
    var mediaHandle = synth.createMediaHandle(el, graph, { lowpassHz: preset.mainLowpassHz });
    mediaHandle.userVolume = targetVolume;
    handles['main'] = mediaHandle;
    synth.rampGain(mediaHandle.trackGain.gain, targetVolume, C.CROSSFADE_MS);

    currentMainUrl = url;
    /* resolveCandidates() 允许「同场景其它已验证曲目」作为真实备选池，因此备用
       URL 可能属于另一首曲目。署名 / 高亮 / 健康度必须跟着「实际在播的 URL」走，
       不能停留在最初请求的 currentMainTrackId 上（A10 / A14 署名正确性）。 */
    var attachedTrackId = track ? track.id : currentMainTrackId;
    var displayName = track ? track.display : displayOf(attachedTrackId);
    patchMainSlot({
      kind: 'audio', voice: null,
      trackId: attachedTrackId,
      url: url, display: displayName
    });
    sources.reportSuccess(attachedTrackId, url);

    var isBackup = !!(ctx && ctx.failedCount > 0);
    store.patch({
      sourceTier: 'bundled',
      badge: isBackup ? 'backup' : 'online',
      badgeText: isBackup ? '备用音源' : '在线可用',
      currentSource: {
        trackId: attachedTrackId, url: url, tier: 'bundled',
        status: isBackup ? 'backup' : 'primary'
      }
    });
    if (ctx && ctx.degradeStartAt) {
      recordDegrade(ctx.lastReason || 'recovered', ctx.fromTier || 'bundled', 'bundled', ctx.degradeStartAt);
      store.emit(E.SOURCE_DEGRADED, {
        reason: ctx.lastReason || 'recovered', toTier: 'bundled',
        message: '已为你切换到备用声源'
      });
    } else {
      store.emit(E.SOURCE_RECOVERED, { url: url, tier: 'bundled' });
    }
    store.pushLog({ type: 'source', action: 'online', url: url, backup: isBackup });
  }

  /**
   * 尝试加载一个候选 URL；成功返回 true，失败返回 false（绝不抛异常）。
   * 监听 playing / error / stalled / waiting，超时 LOAD_TIMEOUT_MS（可注入）。
   */
  function tryLoadAudio(url, ctx) {
    return new Promise(function (resolve) {
      if (!graph || !started) { resolve(false); return; }
      if (ctx && ctx.token !== undefined && ctx.token !== mainUpgradeToken) { resolve(false); return; }

      var track = sources.getTrackByUrl(url);
      /* S-08：清单中显式标记 cors=false 的资源绝不接入 Web Audio 增益链路 */
      if (track && track.cors === false) {
        sources.reportFailure(currentMainTrackId, url, 'cors');
        if (ctx) { ctx.lastReason = 'cors'; }
        resolve(false); return;
      }
      var injected = consumeInjection();
      if (injected) {
        sources.reportFailure(currentMainTrackId, url, injected);
        if (ctx) { ctx.lastReason = injected; }
        resolve(false); return;
      }
      if (SW.RUNTIME.offline) {
        sources.reportFailure(currentMainTrackId, url, 'network');
        if (ctx) { ctx.lastReason = 'network'; }
        resolve(false); return;
      }

      var el = document.createElement('audio');
      el.preload = 'none';
      el.crossOrigin = 'anonymous'; // 仅用于 30 首实测 ACAO=* 的 URL（S-08）
      el.loop = true;
      el.setAttribute('aria-hidden', 'true');
      var timeoutId = null;
      var settled = false;
      /* 降级链路内把单候选超时钳制为「剩余整链预算」：预算检查点在候选间隙，
         若单候选耗满完整配置窗口，recordDegrade 必然越界（默认 3002ms / 注入 2000 时 4004ms）。
         首次在线升级（degradeStartAt=null）保留完整配置窗口，避免弱网误判（P0-06 / AD-16）。 */
      var configuredMs = SW.RUNTIME.loadTimeoutMs || C.LOAD_TIMEOUT_MS;
      var timeoutMs = configuredMs;
      if (ctx && ctx.degradeStartAt) {
        var remainingMs = DEGRADE_BUDGET_MS - (Date.now() - ctx.degradeStartAt);
        timeoutMs = Math.max(50, Math.min(configuredMs, remainingMs));
      }

      function onTime() {
        progress = {
          currentTime: el.currentTime || 0,
          duration: isFinite(el.duration) ? el.duration : 0
        };
      }
      /* 架构 §2.6.2：3s 内到达 canplay / loadedmetadata / playing 即判加载成功。
         用 canplay 而非仅 playing，避免大体积 MP3 缓冲慢被误判为死链。 */
      function onReady() { onTime(); succeed(); }
      function cleanupDecisive() {
        if (timeoutId !== null) { window.clearTimeout(timeoutId); timeoutId = null; }
        el.removeEventListener('playing', onReady);
        el.removeEventListener('canplay', onReady);
        el.removeEventListener('loadedmetadata', onReady);
        el.removeEventListener('error', onError);
        el.removeEventListener('stalled', onStall);
        el.removeEventListener('waiting', onStall);
        el.removeEventListener('ended', onEnded);
        /* 仅保留 timeupdate，用于进度显示 */
      }
      function succeed() {
        if (settled) { return; }
        if (ctx && ctx.token !== undefined && ctx.token !== mainUpgradeToken) {
          settled = true; cleanupDecisive();
          try { el.pause(); } catch (err) { /* 静默 */ }
          resolve(false); return;
        }
        settled = true; cleanupDecisive();
        onTime();
        /* 极端兜底：若浏览器拒绝了 autoplay，仍主动触发自愈，绝不留下静音轨 */
        if (el.paused) {
          try {
            var retry = el.play();
            if (retry && typeof retry.catch === 'function') {
              retry.catch(function () {
                /* 异步触发，避免与本次 attachOnline 竞态 */
                window.setTimeout(function () { onSourceFailure(url, 'autoplay'); }, 0);
              });
            }
          } catch (err) {
            window.setTimeout(function () { onSourceFailure(url, 'autoplay'); }, 0);
          }
        }
        attachOnline(el, url, track, ctx);
        resolve(true);
      }
      function fail(reason) {
        if (settled) { return; }
        settled = true; cleanupDecisive();
        try { el.pause(); el.removeAttribute('src'); } catch (err) { /* 静默 */ }
        sources.reportFailure(currentMainTrackId, url, reason);
        if (ctx) { ctx.lastReason = reason; }
        resolve(false);
      }
      function onError() { fail('404'); }
      function onStall() { /* 主超时统一兜底：stalled/waiting 后 3s 无进展视为失败 */ }
      function onEnded() { try { el.currentTime = 0; el.play().catch(function () {}); } catch (err) { /* 静默 */ } }

      el.addEventListener('playing', onReady);
      el.addEventListener('canplay', onReady);
      el.addEventListener('loadedmetadata', onReady);
      el.addEventListener('error', onError);
      el.addEventListener('stalled', onStall);
      el.addEventListener('waiting', onStall);
      el.addEventListener('timeupdate', onTime);
      el.addEventListener('ended', onEnded);

      timeoutId = window.setTimeout(function () { fail('timeout'); }, timeoutMs);
      try {
        el.src = url;
        /* play() 在用户手势调用链的同步栈内发起，符合 P0-11 / NFR-05 */
        var p = el.play();
        if (p && typeof p.catch === 'function') {
          p.catch(function () { if (!settled) { fail('autoplay'); } });
        }
      } catch (err) {
        fail('network');
      }
    });
  }

  /** 逐个尝试候选（按 health 降序），全部失败返回 false。 */
  function attemptCandidates(trackId, urls, index, ctx) {
    if (ctx && ctx.token !== undefined && ctx.token !== mainUpgradeToken) {
      return Promise.resolve(false);
    }
    /* 整体降级预算耗尽 → 立即交给合成层兜底，保证 lastDegradeDurationMs ≤ 3000 */
    if (ctx && ctx.degradeStartAt && (Date.now() - ctx.degradeStartAt) >= DEGRADE_BUDGET_MS) {
      return Promise.resolve(false);
    }
    if (index >= urls.length) { return Promise.resolve(false); }
    return tryLoadAudio(urls[index], ctx).then(function (ok) {
      if (ok) { return true; }
      if (!ctx.degradeStartAt) { ctx.degradeStartAt = Date.now(); } // 首次故障墙钟时刻
      ctx.failedCount = (ctx.failedCount || 0) + 1;
      if (ctx.token !== undefined && ctx.token !== mainUpgradeToken) { return false; }
      return attemptCandidates(trackId, urls, index + 1, ctx);
    });
  }

  /** 全部候选失败 → 主音源切回永不失效的合成层（不改变 playing / 音量）。 */
  function degradeToSynth(reason, ctx, token) {
    if (token !== undefined && token !== mainUpgradeToken) { return; }
    var startAt = (ctx && ctx.degradeStartAt) || activeDegradeStart || Date.now();
    var fromTier = (ctx && ctx.fromTier) || store.getState().sourceTier;
    var scene = store.getState().scene;
    var preset = C.SCENES[scene] || C.SCENES.focus;
    var old = handles['main'];
    if (old) {
      try { synth.rampGain(old.trackGain.gain, 0, 150); } catch (err) { /* 静默 */ }
      scheduleRelease([old], 220);
    }
    /* old 为 null（自愈入口已摘除）或为 audio 时，重建合成垫声，保证永不静音 */
    if (!old || old.type !== 'synth') {
      var pad = synth.createVoice(preset.padVoice, graph, {});
      var s = findSlot('main');
      var volume = s ? s.volume : 1.0;
      pad.userVolume = volume;
      handles['main'] = pad;
      synth.rampGain(pad.trackGain.gain, volume, 300);
    }
    patchMainSlot({ kind: 'synth', voice: preset.padVoice, trackId: null, url: null, display: '本地合成声' });
    currentMainUrl = null;
    store.patch({
      sourceTier: 'synth', badge: 'synth', badgeText: '本地合成',
      currentSource: { trackId: null, url: null, tier: 'synth', status: 'synth' }
    });
    recordDegrade(reason, fromTier, 'synth', startAt);
    store.emit(E.SOURCE_DEGRADED, {
      reason: reason, toTier: 'synth',
      message: '当前使用本地合成声，随时可刷新曲库'
    });
    activeDegradeStart = null;
  }

  /** 启动在线音源升级（并行于合成垫声，不阻塞首次出声）。 */
  function upgradeMain(trackId, token) {
    currentMainTrackId = trackId;
    var urls = sources.resolveCandidates(trackId);
    var ctx = {
      token: token, degradeStartAt: null,
      fromTier: store.getState().sourceTier,
      failedCount: 0, lastReason: ''
    };
    return attemptCandidates(trackId, urls, 0, ctx).then(function (ok) {
      if (!ok && ctx.token === mainUpgradeToken) {
        /* 递增 token 使所有在途加载失效，避免降级后迟到的 playing 又接回在线 */
        var finalToken = ++mainUpgradeToken;
        degradeToSynth(ctx.lastReason || 'all-candidates-failed', ctx, finalToken);
      }
    });
  }

  /** 自动漂移开关（P1-03：仅操作独立 driftGain，±15%，缓慢无突跳）。 */
  function applyDrift() {
    if (driftTimer !== null) { window.clearInterval(driftTimer); driftTimer = null; }
    var enabled = store.getState().autoDrift;
    if (!enabled) {
      Object.keys(handles).forEach(function (id) { synth.setDriftGain(handles[id], 1); });
      return;
    }
    driftTimer = window.setInterval(function () {
      if (!store.getState().playing) { return; }
      Object.keys(handles).forEach(function (id) {
        synth.setDriftGain(handles[id], 0.85 + Math.random() * 0.30);
      });
    }, 8000);
  }

  /**
   * 首次用户手势：合成层立即出声（≤2s）→ 并行解析 L1 → crossfade 升级在线音乐。
   * 全程不写「无声音」中间态；AudioContext 仅在此链路内创建 / resume。
   */
  function startFromGesture() {
    if (started) { return Promise.resolve(); }
    started = true;
    store.patch({ playState: 'starting' });
    return synth.ensureContext().then(function () {
      graph = synth.createGraph();
      if (!graph) { throw new Error('no-graph'); }
      var scene = store.getState().scene;
      var preset = C.SCENES[scene] || C.SCENES.focus;
      slots = buildSceneSlots(scene);
      handles = Object.create(null);
      slots.forEach(function (s) {
        var h = synth.createVoice(s.voice, graph, {});
        h.userVolume = s.volume;
        handles[s.id] = h;
        synth.rampGain(h.trackGain.gain, s.volume, 400);
      });
      synth.setMaster(preset.masterVolume);
      synth.setFade(1, 80);
      store.patch({
        playing: true, playState: 'playing',
        sourceTier: 'synth', badge: 'synth', badgeText: '本地合成',
        scene: scene, masterVolume: preset.masterVolume,
        brightness: preset.brightness, breath: preset.breath,
        tracks: slots.map(copySlot),
        timerPresetMinutes: preset.timerMinutes,
        timerPresetFade: preset.fadeSeconds,
        currentSource: { trackId: null, url: null, tier: 'synth', status: 'idle' }
      });
      store.emit(E.PLAY_CHANGED, { playing: true });
      store.pushLog({ type: 'play', action: 'start', scene: scene });
      applyDrift();
      if (preset.timerMinutes > 0) { SW.timer.start(preset.timerMinutes, preset.fadeSeconds); }
      else { SW.timer.cancel(); }
      store.savePrefs();
      /* 并行升级：不阻塞「先出声」 */
      upgradeMain(defaultMainTrackId(), ++mainUpgradeToken);
    }).catch(function (err) {
      /* 异常在模块内吞掉；合成层若已建立则保持播放态，绝不出现「点了没反应」 */
      store.pushLog({ type: 'play', action: 'start-degraded', reason: String(err && err.message || 'unknown') });
      if (store.getState().playState !== 'playing') {
        store.patch({ playing: true, playState: 'playing' });
      }
    });
  }

  /** 播放 / 恢复。 */
  function play() {
    if (!started) { return startFromGesture(); }
    var st = store.getState();
    if (st.playing) { return Promise.resolve(); }
    Object.keys(handles).forEach(function (id) {
      var h = handles[id];
      if (!h) { return; }
      synth.rampGain(h.trackGain.gain, h.userVolume, 300);
      if (h.type === 'audio' && h.element) {
        try { var p = h.element.play(); if (p && p.catch) { p.catch(function () {}); } } catch (err) { /* 静默 */ }
      }
    });
    store.patch({ playing: true, playState: 'playing' });
    store.emit(E.PLAY_CHANGED, { playing: true });
    applyDrift();
    return Promise.resolve();
  }

  /** 暂停：所有声轨同步静默，但保留进度与混音配置（P0-02）。 */
  function pause() {
    if (!started) {
      store.patch({ playing: false, playState: 'paused' });
      return;
    }
    Object.keys(handles).forEach(function (id) {
      var h = handles[id];
      if (!h) { return; }
      try { synth.rampGain(h.trackGain.gain, 0, 200); } catch (err) { /* 静默 */ }
      if (h.type === 'audio' && h.element) {
        try { h.element.pause(); } catch (err) { /* 静默 */ }
      }
    });
    store.patch({ playing: false, playState: 'paused' });
    store.emit(E.PLAY_CHANGED, { playing: false });
  }

  /** 播放 / 暂停切换。 */
  function toggle() {
    return store.getState().playing ? (pause(), Promise.resolve()) : play();
  }

  /**
   * 场景切换（P0-01）：保存旧配置 → 载入处方 → ≥600ms crossfade →
   * 更新文案 / 亮度 / 定时器 / 呼吸圆环 → 主音源重新升级。
   */
  function applyScene(scene) {
    var preset = C.SCENES[scene];
    if (!preset) { return Promise.resolve(); }
    if (!started) {
      store.patch({ scene: scene });
      return startFromGesture();
    }
    var audible = store.getState().playing;
    var token = ++mainUpgradeToken; // 中止上一场景尚未完成的在线加载
    var oldHandles = Object.keys(handles).map(function (k) { return handles[k]; });
    oldHandles.forEach(function (h) {
      try { synth.rampGain(h.trackGain.gain, 0, C.CROSSFADE_MS); } catch (err) { /* 静默 */ }
    });
    scheduleRelease(oldHandles, C.CROSSFADE_MS + 120);
    handles = Object.create(null);
    slots = buildSceneSlots(scene);
    slots.forEach(function (s) {
      var h = synth.createVoice(s.voice, graph, {});
      h.userVolume = s.volume;
      handles[s.id] = h;
      synth.rampGain(h.trackGain.gain, audible ? s.volume : 0, C.CROSSFADE_MS);
    });
    synth.setMaster(preset.masterVolume);
    currentMainUrl = null;
    store.patch({
      scene: scene, masterVolume: preset.masterVolume,
      brightness: preset.brightness, breath: preset.breath,
      tracks: slots.map(copySlot),
      timerPresetMinutes: preset.timerMinutes,
      timerPresetFade: preset.fadeSeconds,
      sourceTier: 'synth', badge: 'synth', badgeText: '本地合成',
      currentSource: { trackId: null, url: null, tier: 'synth', status: 'idle' }
    });
    store.emit(E.SCENE_CHANGED, { scene: scene });
    if (audible) {
      if (preset.timerMinutes > 0) { SW.timer.start(preset.timerMinutes, preset.fadeSeconds); }
      else { SW.timer.cancel(); }
      upgradeMain(defaultMainTrackId(), token);
    } else {
      SW.timer.cancel();
    }
    store.savePrefs();
    applyDrift();
    return Promise.resolve();
  }

  /** 主音量（0..1）。 */
  function setMasterVolume(v) {
    var value = Math.max(0, Math.min(1, Number(v) || 0));
    synth.setMaster(value);
    store.patch({ masterVolume: value });
    store.emit(E.VOLUME_CHANGED, { master: value });
    store.savePrefs();
  }

  /** 分轨音量（0..1）。 */
  function setTrackVolume(slotId, v) {
    var s = findSlot(slotId);
    if (!s) { return; }
    var value = Math.max(0, Math.min(1, Number(v) || 0));
    s.volume = value;
    var h = handles[slotId];
    if (h) { synth.setTrackGain(h, value); }
    syncSlots();
    store.emit(E.VOLUME_CHANGED, { slotId: slotId, volume: value });
  }

  /**
   * 添加一条声景（P0-04 上限 3，超限明确提示且不崩溃）。
   * @param {string} voice VoiceId 或 trackId
   * @returns {{ok:boolean, reason?:string}}
   */
  function addTrack(voice) {
    if (slots.length >= C.MAX_TRACKS) {
      store.emit(E.TOAST, { message: '已达 3 条声景上限，先移除一条再添加' });
      return { ok: false, reason: 'limit' };
    }
    var id = 'extra-' + Date.now().toString(36);
    var label = C.VOICE_LABELS[voice] || displayOf(voice);
    var slot = { id: id, kind: 'synth', voice: voice, trackId: null, volume: 0.30, display: label, url: null };
    slots.push(slot);
    if (graph) {
      var h = synth.createVoice(C.SYNTH_VOICES.indexOf(voice) >= 0 ? voice : 'brown', graph, {});
      h.userVolume = slot.volume;
      handles[id] = h;
      synth.rampGain(h.trackGain.gain, store.getState().playing ? slot.volume : 0, C.CROSSFADE_MS);
    }
    syncSlots();
    store.emit(E.TRACK_ADDED, { slot: copySlot(slot) });
    return { ok: true, id: id };
  }

  /** 移除音轨：淡出后 disconnect + 释放引用，无残留声音（P0-04 / NFR-07）。 */
  function removeTrack(slotId) {
    var idx = -1;
    for (var i = 0; i < slots.length; i += 1) { if (slots[i].id === slotId) { idx = i; break; } }
    if (idx < 0) { return; }
    var removed = slots.splice(idx, 1)[0];
    var h = handles[slotId];
    if (h) {
      try { synth.rampGain(h.trackGain.gain, 0, 200); } catch (err) { /* 静默 */ }
      scheduleRelease([h], 260);
      delete handles[slotId];
    }
    syncSlots();
    store.emit(E.TRACK_REMOVED, { slot: copySlot(removed) });
  }

  /**
   * 把主音源切到指定曲目：淡出旧轨 → 先重建合成垫声保证无缝 → 并行升级在线音源。
   * 「换一曲」与「声音库点选」共用此链路，避免两条切换逻辑分叉（P1-09）。
   */
  function switchMainTrack(nextId) {
    if (!started || !graph || !nextId) { return false; }
    var preset = C.SCENES[store.getState().scene] || C.SCENES.focus;
    var token = ++mainUpgradeToken;
    var old = handles['main'];
    if (old) {
      try { synth.rampGain(old.trackGain.gain, 0, C.CROSSFADE_MS); } catch (err) { /* 静默 */ }
      scheduleRelease([old], C.CROSSFADE_MS + 120);
    }
    var pad = synth.createVoice(preset.padVoice, graph, {});
    var s = findSlot('main');
    var volume = s ? s.volume : 1.0;
    pad.userVolume = volume;
    handles['main'] = pad;
    synth.rampGain(pad.trackGain.gain, volume, 300);
    patchMainSlot({ kind: 'synth', voice: preset.padVoice, trackId: nextId, url: null, display: displayOf(nextId) });
    /* 旧在线音源此刻已被摘除。必须同步清空 currentSource，否则在「合成垫声 →
       在线升级」的窗口内，renderInfoPanel / renderLibraryPanel 会优先读到旧
       trackId，把上一首的署名与「正在播放」高亮错配到新点选的曲目上（A10 / A14）。
       升级成功由 attachOnline 写回，全失败由 degradeToSynth 归零，状态闭环。 */
    store.patch({
      sourceTier: 'synth', badge: 'synth', badgeText: '本地合成',
      currentSource: { trackId: null, url: null, tier: 'synth', status: 'synth' }
    });
    upgradeMain(nextId, token);
    return true;
  }

  /** 「换一曲」：优先同场景的下一首氛围音乐。 */
  function nextTrack() {
    if (!started || !graph) { return; }
    var scene = store.getState().scene;
    var list = sources.getTracks(scene).filter(function (t) { return t.kind === 'music'; });
    if (!list.length) { list = sources.getTracks(scene); }
    if (!list.length) { return; }
    var index = 0;
    for (var i = 0; i < list.length; i += 1) {
      if (list[i].id === currentMainTrackId) { index = (i + 1) % list.length; break; }
    }
    switchMainTrack(list[index].id);
  }

  /** 声音库点选：按 id 切换主音源。只接受清单白名单投影里存在的曲目。 */
  function selectTrack(trackId) {
    if (!started || !graph) { return false; }
    var view = sources.getUiTrack(trackId);
    if (!view || !view.id) { return false; }
    /* 已是「实际在播」的曲目时不做无谓重建，避免短暂回到合成层。
       用 currentSource（而非 currentMainTrackId）比对，是因为备用 URL 可能
       已切到同场景的其它曲目；此时用户再点原曲目不应被误判为重复点选。 */
    var st = store.getState();
    var actual = (st.currentSource && st.currentSource.trackId) ||
      (st.tracks.length && st.tracks[0] ? st.tracks[0].trackId : null);
    if (view.id === actual && st.sourceTier === 'bundled') { return true; }
    return switchMainTrack(view.id);
  }

  /**
   * 自愈链路入口（P0-06 / §5.3）：保持 L0 垫声、只淡出失败轨、
   * 上报健康度 → 切下一候选 → 全失败降级合成层。全程不写 playing、不改音量。
   */
  function onSourceFailure(url, reason) {
    var degradeStartAt = Date.now();
    activeDegradeStart = degradeStartAt;
    var fromTier = store.getState().sourceTier;
    var failed = handles['main'];
    if (failed && failed.type === 'audio') {
      try { synth.rampGain(failed.trackGain.gain, 0, 150); } catch (err) { /* 静默 */ }
      scheduleRelease([failed], 220);
      delete handles['main']; // 摘除引用；后续由 attachOnline 或 degradeToSynth 重建
    }
    sources.reportFailure(currentMainTrackId, url, reason);
    var urls = sources.resolveCandidates(currentMainTrackId);
    var idx = urls.indexOf(url);
    var rest = idx >= 0 ? urls.slice(idx + 1) : urls;
    var token = ++mainUpgradeToken;
    var ctx = {
      token: token, degradeStartAt: degradeStartAt, fromTier: fromTier,
      failedCount: 1, lastReason: reason
    };
    return attemptCandidates(currentMainTrackId, rest, 0, ctx).then(function (ok) {
      if (!ok && ctx.token === mainUpgradeToken) {
        var finalToken = ++mainUpgradeToken;
        degradeToSynth(ctx.lastReason || reason, ctx, finalToken);
      }
    });
  }

  /** 当前徽标状态（供契约与 sources 恢复徽标使用）。 */
  function getBadgeState() {
    var s = store.getState();
    return { badge: s.badge, badgeText: s.badgeText, sourceTier: s.sourceTier };
  }

  /** 播放进度（供 ui.js 每秒轮询，避免高频全量渲染）。 */
  function getProgress() { return { currentTime: progress.currentTime, duration: progress.duration }; }

  /** 当前活跃音轨数（契约断言 activeTrackCount ≤3）。 */
  function getActiveTrackCount() { return slots.length; }

  /** 设置自动漂移（P1-03）。 */
  function setAutoDrift(flag) {
    store.patch({ autoDrift: !!flag });
    store.savePrefs();
    applyDrift();
  }

  /* —— 仅 ?debug=1 契约使用的调试面（不参与正常 UI）—— */

  /** 强制切层：'synth' 直接降到底座，'online' 重新尝试在线升级。 */
  function debugForceTier(tier) {
    var token = ++mainUpgradeToken;
    if (tier === 'synth') {
      degradeToSynth('force-tier', {
        degradeStartAt: Date.now(), fromTier: store.getState().sourceTier,
        failedCount: 0, lastReason: 'force-tier'
      }, token);
    } else if (tier === 'online') {
      upgradeMain(currentMainTrackId || defaultMainTrackId(), token);
    }
  }

  /** 断网注入：主动让当前在线轨失败，立即触发自愈且播放连续。 */
  function debugForceOffline(flag) {
    SW.RUNTIME.offline = !!flag;
    if (flag && currentMainUrl) {
      onSourceFailure(currentMainUrl, 'network');
    }
  }

  /** 一次性故障注入：立即让当前在线轨失败，否则留给下次加载消费。 */
  function debugInjectFailure(kind) {
    SW.RUNTIME.forceFailureOnce = kind;
    if (currentMainUrl && handles['main'] && handles['main'].type === 'audio') {
      onSourceFailure(currentMainUrl, kind === '404' ? '404' : kind);
    }
  }

  /** 释放全部资源（dispose：供页面卸载 / 契约清理）。 */
  function dispose() {
    if (driftTimer !== null) { window.clearInterval(driftTimer); driftTimer = null; }
    releaseTimers.forEach(function (t) { window.clearTimeout(t); });
    releaseTimers = [];
    Object.keys(handles).forEach(function (id) { synth.releaseVoice(handles[id]); });
    pendingReleases.forEach(function (h) { synth.releaseVoice(h); });
    pendingReleases = [];
    handles = Object.create(null);
    slots = [];
    graph = null;
    started = false;
  }

  SW.player = {
    startFromGesture: startFromGesture,
    play: play,
    pause: pause,
    toggle: toggle,
    applyScene: applyScene,
    setMasterVolume: setMasterVolume,
    setTrackVolume: setTrackVolume,
    addTrack: addTrack,
    removeTrack: removeTrack,
    nextTrack: nextTrack,
    selectTrack: selectTrack,
    onSourceFailure: onSourceFailure,
    getActiveTrackCount: getActiveTrackCount,
    dispose: dispose,
    /* 契约 / UI 所需的扩展只读与调试面 */
    getProgress: getProgress,
    getBadgeState: getBadgeState,
    setAutoDrift: setAutoDrift,
    debugForceTier: debugForceTier,
    debugForceOffline: debugForceOffline,
    debugInjectFailure: debugInjectFailure
  };
})();

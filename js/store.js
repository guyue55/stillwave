/* ==========================================================================
 * 静澜 Stillwave · js/store.js
 * 职责：唯一状态真源 + 发布订阅事件总线 + localStorage 持久化（静默内存降级）
 *       + 状态机 + 环形事件日志（上限 200，防长时内存增长）。
 * 装载：第 3 位（config → audio-sources.js → store）。
 * ========================================================================== */
;(function () {
  'use strict';

  var SW = (window.SW = window.SW || {});
  var C = SW.config;
  var E = C.EVENTS;
  var K = C.STORAGE_KEYS;

  /** 出厂默认状态（§4.3 AppState + 契约诊断扩展字段）。 */
  function defaultState() {
    return {
      playing: false,
      playState: 'idle',            // idle → starting → playing ⇄ paused → stopped
      scene: 'focus',
      masterVolume: 0.45,
      tracks: [],                   // TrackSlot[] ≤3
      sourceTier: 'synth',          // synth | bundled | remote | discovery | radio
      badge: 'synth',               // online | backup | synth | refreshing
      badgeText: '本地合成',
      currentSource: { trackId: null, url: null, tier: 'synth', status: 'idle' },
      manifest: { version: 1, updatedAt: '', count: 30, source: 'bundled' },
      brightness: 'dark',
      timer: {
        active: false, remainingMs: 0, phase: 'idle',
        fadeSeconds: 0, minutes: 0, endsAt: null
      },
      autoDrift: false,
      breath: 'off',
      reducedMotion: C.REDUCED_MOTION,
      debug: C.DEBUG,
      remoteConfigured: C.REMOTE_MANIFEST !== null,
      resolvedRemotes: C.resolvedRemotes.slice(),
      storageMode: 'localStorage',
      libraryStatus: 'idle',        // idle | refreshing | success | failed
      timerPresetMinutes: 45,
      timerPresetFade: 0
    };
  }

  var state = defaultState();
  var listeners = Object.create(null);
  var log = [];
  var logSeq = 0;
  var memory = Object.create(null);
  var mode = 'localStorage';

  /** 探测 localStorage 可用性（隐私模式 / file:// 部分浏览器会抛错）。 */
  function storageUsable() {
    if (SW.RUNTIME.storageUnavailable) { return false; }
    try {
      var probe = '__sw_probe__';
      window.localStorage.setItem(probe, '1');
      window.localStorage.removeItem(probe);
      return true;
    } catch (err) {
      return false;
    }
  }

  /** 当前存储模式（供 __STILLWAVE__.getState().storageMode 断言）。 */
  function getStorageMode() {
    mode = storageUsable() ? 'localStorage' : 'memory';
    return mode;
  }

  /**
   * 通用存储读取（供 sources.js 读写 health / manifest 键）。
   * @param {string} key
   * @returns {*} 解析后的对象或 null
   */
  function readStorage(key) {
    if (!storageUsable()) { return Object.prototype.hasOwnProperty.call(memory, key) ? memory[key] : null; }
    try {
      var raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (err) {
      return Object.prototype.hasOwnProperty.call(memory, key) ? memory[key] : null;
    }
  }

  /** 通用存储写入（失败静默降级到内存 Map）。 */
  function writeStorage(key, value) {
    if (!storageUsable()) { memory[key] = value; return; }
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (err) {
      memory[key] = value;
    }
  }

  /** 通用存储删除。 */
  function removeStorage(key) {
    delete memory[key];
    if (!storageUsable()) { return; }
    try { window.localStorage.removeItem(key); } catch (err) { /* 静默 */ }
  }

  /** 返回状态快照（浅拷贝 + 关键嵌套对象拷贝，避免外部改写）。 */
  function getState() {
    var snap = Object.assign({}, state);
    snap.tracks = state.tracks.map(function (t) { return Object.assign({}, t); });
    snap.timer = Object.assign({}, state.timer);
    snap.manifest = Object.assign({}, state.manifest);
    snap.currentSource = Object.assign({}, state.currentSource);
    snap.resolvedRemotes = state.resolvedRemotes.slice();
    snap.storageMode = getStorageMode();
    return snap;
  }

  /**
   * 唯一写入口。内部 emit(EVENTS.STATE)。
   * @param {Object} partial 需要合并的字段
   */
  function patch(partial) {
    if (!partial || typeof partial !== 'object') { return; }
    var changed = Object.keys(partial);
    Object.assign(state, partial);
    if (Object.prototype.hasOwnProperty.call(partial, 'storageMode')) {
      /* storageMode 是计算字段，不允许写入覆盖 */
      state.storageMode = getStorageMode();
    }
    emit(E.STATE, { state: getState(), changed: changed });
  }

  /**
   * 订阅事件，返回取消订阅函数。
   * @param {string} event
   * @param {Function} handler
   * @returns {Function} unsubscribe
   */
  function on(event, handler) {
    if (typeof handler !== 'function') { return function () {}; }
    if (!listeners[event]) { listeners[event] = []; }
    listeners[event].push(handler);
    return function () { off(event, handler); };
  }

  /** 取消订阅。 */
  function off(event, handler) {
    var arr = listeners[event];
    if (!arr) { return; }
    var idx = arr.indexOf(handler);
    if (idx >= 0) { arr.splice(idx, 1); }
  }

  /** 发布事件；单个 handler 异常在内部吞掉，绝不中断其它订阅者（§8.4）。 */
  function emit(event, payload) {
    var arr = listeners[event];
    if (!arr || !arr.length) { return; }
    var copy = arr.slice();
    for (var i = 0; i < copy.length; i += 1) {
      try { copy[i](payload); } catch (err) { /* 吞掉，控制台清洁 */ }
    }
  }

  /** 环形事件日志（上限 C.LOG_LIMIT，含时间戳与序号）。 */
  function pushLog(entry) {
    logSeq += 1;
    var record = Object.assign({
      seq: logSeq,
      at: new Date().toISOString(),
      wall: Date.now()
    }, entry || {});
    log.push(record);
    if (log.length > C.LOG_LIMIT) { log.splice(0, log.length - C.LOG_LIMIT); }
  }

  /** 返回日志副本。 */
  function getLog() { return log.slice(); }

  /** 从状态中抽取可持久化的用户偏好（§8.6）。 */
  function collectPrefs() {
    return {
      scene: state.scene,
      masterVolume: state.masterVolume,
      brightness: state.brightness,
      autoDrift: state.autoDrift,
      breath: state.breath,
      timerPresetMinutes: state.timerPresetMinutes,
      timerPresetFade: state.timerPresetFade,
      tracks: state.tracks.map(function (t) {
        return { id: t.id, kind: t.kind, voice: t.voice, trackId: t.trackId, volume: t.volume, display: t.display };
      })
    };
  }

  /** 载入偏好；字段做合法性校验，非法值忽略（原子回退）。 */
  function loadPrefs() {
    var prefs = readStorage(K.prefs);
    getStorageMode();
    if (!prefs || typeof prefs !== 'object') { return; }
    var validScenes = C.SCENE_IDS;
    if (validScenes.indexOf(prefs.scene) >= 0) { state.scene = prefs.scene; }
    if (typeof prefs.masterVolume === 'number' && prefs.masterVolume >= 0 && prefs.masterVolume <= 1) {
      state.masterVolume = prefs.masterVolume;
    }
    if (['normal', 'dark', 'extreme'].indexOf(prefs.brightness) >= 0) { state.brightness = prefs.brightness; }
    if (typeof prefs.autoDrift === 'boolean') { state.autoDrift = prefs.autoDrift; }
    if (['off', '4-4', '4-7-8'].indexOf(prefs.breath) >= 0) { state.breath = prefs.breath; }
    if (typeof prefs.timerPresetMinutes === 'number') { state.timerPresetMinutes = prefs.timerPresetMinutes; }
    if (typeof prefs.timerPresetFade === 'number') { state.timerPresetFade = prefs.timerPresetFade; }
    /* 混音配置仅作展示还原，实际音轨由 player 首次手势时按场景处方重建 */
    emit(E.STATE, { state: getState(), changed: ['prefs'] });
  }

  /** 保存偏好（静默降级到内存）。 */
  function savePrefs() { writeStorage(K.prefs, collectPrefs()); }

  /**
   * 清除本地设置：清三个键并恢复出厂默认（P0-09 / P0-12）。
   * 保留环境相关字段（debug / reducedMotion / resolvedRemotes）。
   */
  function clearAll() {
    removeStorage(K.prefs);
    removeStorage(K.health);
    removeStorage(K.manifest);
    memory = Object.create(null);
    var env = {
      debug: C.DEBUG,
      reducedMotion: C.REDUCED_MOTION,
      remoteConfigured: C.REMOTE_MANIFEST !== null,
      resolvedRemotes: C.resolvedRemotes.slice()
    };
    state = defaultState();
    Object.assign(state, env);
    state.storageMode = getStorageMode();
    pushLog({ type: 'storage', action: 'cleared' });
    emit(E.STATE, { state: getState(), changed: ['all'] });
  }

  SW.store = {
    getState: getState,
    patch: patch,
    on: on,
    off: off,
    emit: emit,
    loadPrefs: loadPrefs,
    savePrefs: savePrefs,
    clearAll: clearAll,
    pushLog: pushLog,
    getLog: getLog,
    /* 以下三个为供 sources.js 复用的持久化底层（契约所必需的扩展） */
    readStorage: readStorage,
    writeStorage: writeStorage,
    removeStorage: removeStorage,
    getStorageMode: getStorageMode
  };
})();

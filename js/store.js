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

  /* —— P0-2 收藏与混音预设：本层只负责持久化，不碰 UI、不调播放器 ———————
     分层约定：store.js 不依赖 sources.js，因此这里只校验「结构 / 类型 / 取值范围」，
     不校验曲目 id 是否仍在曲库白名单内；白名单过滤由 ui.js 在读取时静默完成
     （曲目下线不会让面板报错，也不会误删用户收藏）。
     所有读取均包 try/catch：键缺失、JSON 损坏、顶层非对象、v !== 1 一律视为空集。 */

  var favoritesCache = null;
  var presetsCache = null;

  /** 音量归一：非法值归 0，钳制 0..1，保留两位小数。 */
  function normalizeVolume(value) {
    var n = Number(value);
    if (!isFinite(n)) { return 0; }
    return Math.round(Math.max(0, Math.min(1, n)) * 100) / 100;
  }

  /** 名称归一：去控制字符、去首尾空白、截断至 MAX_PRESET_NAME。 */
  function normalizeName(value) {
    if (typeof value !== 'string') { return ''; }
    return value.replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, C.MAX_PRESET_NAME);
  }

  /** 读取收藏 id 列表（去重、截断至上限，永不抛错）。 */
  function readFavorites() {
    try {
      var raw = readStorage(K.favorites);
      if (!raw || typeof raw !== 'object' || raw.v !== 1 || !Array.isArray(raw.ids)) { return []; }
      var out = [];
      for (var i = 0; i < raw.ids.length; i += 1) {
        var id = raw.ids[i];
        if (typeof id !== 'string') { continue; }
        id = id.trim();
        if (!id || out.indexOf(id) >= 0) { continue; }
        out.push(id);
        if (out.length >= C.MAX_FAVORITES) { break; }
      }
      return out;
    } catch (err) {
      return [];
    }
  }

  /** 收藏 id 列表（永远是数组副本，调用方改写不影响内部状态）。 */
  function getFavorites() {
    if (!favoritesCache) { favoritesCache = readFavorites(); }
    return favoritesCache.slice();
  }

  /** 是否已收藏。 */
  function isFavorite(trackId) {
    if (typeof trackId !== 'string' || !trackId) { return false; }
    return getFavorites().indexOf(trackId) >= 0;
  }

  /** 切换收藏；失败返回 {ok:false, reason}，绝不抛错。 */
  function toggleFavorite(trackId) {
    if (typeof trackId !== 'string' || !trackId.trim()) {
      return { ok: false, favorite: false, reason: 'id' };
    }
    var id = trackId.trim();
    var ids = getFavorites();
    var idx = ids.indexOf(id);
    if (idx >= 0) {
      ids.splice(idx, 1);
    } else {
      if (ids.length >= C.MAX_FAVORITES) {
        return { ok: false, favorite: false, reason: 'limit' };
      }
      ids.push(id);
    }
    writeStorage(K.favorites, { v: 1, ids: ids });
    favoritesCache = ids;
    return { ok: true, favorite: idx < 0 };
  }

  /** 校验并归一单条预设轨道；非法条目返回 null（静默丢弃该条）。 */
  function normalizePresetTrack(entry) {
    if (!entry || typeof entry !== 'object') { return null; }
    var volume = normalizeVolume(entry.volume);
    if (entry.kind === 'track') {
      if (typeof entry.trackId !== 'string' || !entry.trackId.trim()) { return null; }
      return { kind: 'track', trackId: entry.trackId.trim(), volume: volume };
    }
    if (entry.kind === 'voice') {
      if (C.SYNTH_VOICES.indexOf(entry.voice) < 0) { return null; }
      return { kind: 'voice', voice: entry.voice, volume: volume };
    }
    return null;
  }

  /**
   * 校验并归一单条预设（只保留 id / voice / volume / scene / masterVolume）。
   * @param {Object} spec
   * @returns {{ok:boolean, value?:Object, reason?:string}}
   */
  function normalizePreset(spec) {
    if (!spec || typeof spec !== 'object') { return { ok: false, reason: 'spec' }; }
    var name = normalizeName(spec.name);
    if (!name) { return { ok: false, reason: 'name' }; }
    if (C.SCENE_IDS.indexOf(spec.scene) < 0) { return { ok: false, reason: 'scene' }; }
    if (!Array.isArray(spec.tracks)) { return { ok: false, reason: 'tracks' }; }
    var tracks = [];
    for (var i = 0; i < spec.tracks.length && tracks.length < C.MAX_TRACKS; i += 1) {
      var t = normalizePresetTrack(spec.tracks[i]);
      if (t) { tracks.push(t); }
    }
    if (!tracks.length) { return { ok: false, reason: 'tracks' }; }
    return {
      ok: true,
      value: {
        name: name,
        scene: spec.scene,
        masterVolume: normalizeVolume(spec.masterVolume),
        tracks: tracks
      }
    };
  }

  /** 深拷贝单条预设（绝不把内部引用交给调用方）。 */
  function copyPreset(p) {
    var tracks = [];
    var i;
    for (i = 0; i < p.tracks.length; i += 1) {
      if (p.tracks[i].kind === 'track') {
        tracks.push({ kind: 'track', trackId: p.tracks[i].trackId, volume: p.tracks[i].volume });
      } else if (p.tracks[i].kind === 'voice') {
        tracks.push({ kind: 'voice', voice: p.tracks[i].voice, volume: p.tracks[i].volume });
      }
    }
    return { name: p.name, scene: p.scene, masterVolume: p.masterVolume, tracks: tracks };
  }

  /** 读取预设列表（逐条校验，非法条目静默丢弃，永不抛错）。 */
  function readPresets() {
    try {
      var raw = readStorage(K.presets);
      if (!raw || typeof raw !== 'object' || raw.v !== 1 || !Array.isArray(raw.items)) { return []; }
      var out = [];
      for (var i = 0; i < raw.items.length && out.length < C.MAX_PRESETS; i += 1) {
        var res = normalizePreset(raw.items[i]);
        if (res.ok) { out.push(res.value); }
      }
      return out;
    } catch (err) {
      return [];
    }
  }

  /** 预设列表（深拷贝，调用方改写不影响内部状态）。 */
  function getPresets() {
    if (!presetsCache) { presetsCache = readPresets(); }
    var out = [];
    for (var i = 0; i < presetsCache.length; i += 1) { out.push(copyPreset(presetsCache[i])); }
    return out;
  }

  /** 保存预设；数量满、名称非法、场景非法、轨道非法均返回 {ok:false, reason}。 */
  function savePreset(spec) {
    var items = getPresets();
    if (items.length >= C.MAX_PRESETS) {
      return { ok: false, reason: 'limit', count: items.length };
    }
    var res = normalizePreset(spec);
    if (!res.ok) { return { ok: false, reason: res.reason, count: items.length }; }
    items.push(copyPreset(res.value));
    writeStorage(K.presets, { v: 1, items: items });
    presetsCache = items;
    return { ok: true, count: items.length };
  }

  /** 按索引删除预设；索引非法只回报当前数量，不抛错。 */
  function deletePreset(index) {
    var items = getPresets();
    var idx = Number(index);
    if (!isFinite(idx) || idx < 0 || idx >= items.length || Math.floor(idx) !== idx) {
      return { ok: false, count: items.length };
    }
    items.splice(idx, 1);
    writeStorage(K.presets, { v: 1, items: items });
    presetsCache = items;
    return { ok: true, count: items.length };
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
   * 清除本地设置：清全部存储键并恢复出厂默认（P0-09 / P0-12 / P0-2）。
   * 收藏与预设必须一并清除，否则会出现「点了清除但收藏还在」（F-5）。
   * 保留环境相关字段（debug / reducedMotion / resolvedRemotes）。
   */
  function clearAll() {
    removeStorage(K.prefs);
    removeStorage(K.health);
    removeStorage(K.manifest);
    removeStorage(K.favorites);
    removeStorage(K.presets);
    favoritesCache = null;
    presetsCache = null;
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
    /* P0-2 收藏与混音预设（只做持久化；白名单过滤在 ui.js） */
    getFavorites: getFavorites,
    isFavorite: isFavorite,
    toggleFavorite: toggleFavorite,
    getPresets: getPresets,
    savePreset: savePreset,
    deletePreset: deletePreset,
    /* 以下三个为供 sources.js 复用的持久化底层（契约所必需的扩展） */
    readStorage: readStorage,
    writeStorage: writeStorage,
    removeStorage: removeStorage,
    getStorageMode: getStorageMode
  };
})();

/* ==========================================================================
 * 静澜 Stillwave · js/config.js
 * 职责：唯一可配置常量 + 冻结契约（事件名 / 场景处方 / 声景 / 过滤规则 / 存储键）
 * 装载：第 1 位（最先），经典 defer 脚本，IIFE 封装，仅挂 window.SW。
 * 说明：不含 import / export；不产生 window.SW.RUNTIME 之外的隐式全局。
 * ========================================================================== */
;(function () {
  'use strict';

  var SW = (window.SW = window.SW || {});

  /** 场景类型标识。 */
  var SCENE_IDS = ['focus', 'sleep', 'empty', 'meditation'];

  /** 10 种程序化声景（全部 Web Audio 本地合成，零网络依赖）。 */
  var SYNTH_VOICES = [
    'white', 'pink', 'brown', 'rain', 'stream',
    'wind', 'waves', 'bowl', 'fire', 'forest'
  ];

  /** 声景中文名（用户可见，唯一展示名）。 */
  var VOICE_LABELS = {
    white: '白噪', pink: '粉噪', brown: '棕噪', rain: '细雨',
    stream: '溪流', wind: '风', waves: '海浪', bowl: '颂钵',
    fire: '篝火', forest: '林风'
  };

  /**
   * 场景处方表（与 PRD §3.4 / 架构 §4.4 逐项对齐，未改动任何数值）。
   * mainTrackId 为 null 表示主音源关闭，改用极轻合成底噪（冥想场景）。
   * padVoice 为「先出声、再升级」阶段使用的柔和合成垫声（AD-13）。
   */
  var SCENES = {
    focus: {
      id: 'focus', label: '学习', caption: '屏蔽喧嚣，留一处安静',
      mainTrackId: 'jamendo-122281', mainLowpassHz: 0,
      layers: [
        { voice: 'rain', volume: 0.30 },
        { voice: 'brown', volume: 0.15 }
      ],
      masterVolume: 0.45, timerMinutes: 45, fadeSeconds: 0,
      brightness: 'dark', breath: 'off', padVoice: 'brown',
      glow: 'calm'
    },
    sleep: {
      id: 'sleep', label: '助眠', caption: '没注意到什么时候睡着的',
      mainTrackId: 'jamendo-122281', mainLowpassHz: 2200,
      layers: [
        { voice: 'rain', volume: 0.35 }
      ],
      masterVolume: 0.30, timerMinutes: 30, fadeSeconds: 60,
      brightness: 'extreme', breath: 'off', padVoice: 'rain',
      glow: 'night'
    },
    empty: {
      id: 'empty', label: '放空', caption: '肩膀松下来了',
      mainTrackId: 'jamendo-122281', mainLowpassHz: 0,
      layers: [
        { voice: 'forest', volume: 0.40 },
        { voice: 'stream', volume: 0.25 }
      ],
      masterVolume: 0.40, timerMinutes: 0, fadeSeconds: 0,
      brightness: 'normal', breath: 'off', padVoice: 'forest',
      glow: 'soft'
    },
    meditation: {
      id: 'meditation', label: '冥想', caption: '呼吸慢下来了',
      mainTrackId: null, mainLowpassHz: 0,
      layers: [
        { voice: 'bowl', volume: 0.20 }
      ],
      masterVolume: 0.25, timerMinutes: 10, fadeSeconds: 0,
      brightness: 'normal', breath: '4-4', padVoice: 'brown',
      glow: 'focus'
    }
  };

  /** 事件名常量（§8.3，全部 sw:<domain>:<action>）。 */
  var EVENTS = {
    STATE: 'sw:state',
    PLAY_CHANGED: 'sw:play:changed',
    SCENE_CHANGED: 'sw:scene:changed',
    VOLUME_CHANGED: 'sw:volume:changed',
    TRACK_ADDED: 'sw:track:added',
    TRACK_REMOVED: 'sw:track:removed',
    SOURCE_DEGRADED: 'sw:source:degraded',
    SOURCE_RECOVERED: 'sw:source:recovered',
    LIBRARY_UPDATED: 'sw:library:updated',
    LIBRARY_FAILED: 'sw:library:failed',
    LIBRARY_REFRESHING: 'sw:library:refreshing',
    TIMER_TICK: 'sw:timer:tick',
    TIMER_FADING: 'sw:timer:fading',
    TIMER_ENDED: 'sw:timer:ended',
    BRIGHTNESS_CHANGED: 'sw:brightness:changed',
    TOAST: 'sw:toast'
  };

  /** 存储键（§8.6，仅三个，全部 localStorage）。 */
  var STORAGE_KEYS = {
    prefs: 'sw.prefs.v1',
    health: 'sw.health.v1',
    manifest: 'sw.manifest.v1'
  };

  /** L3 动态发现的标题黑名单（S-05 / D6 / AD-10）。 */
  var FILTER_BLACKLIST = [
    /\btalk\b/i, /lecture/i, /dhamma/i, /sermon/i, /podcast/i,
    /speech/i, /guided/i, /interview/i, /radio/i, /news/i,
    /口播|讲座|播客|导词|开示|说法/, /\d{3,}[\s\-]?\d{3,}/
  ];

  /** L3 过滤白名单与阈值。 */
  var FILTER_RULES = {
    identifierPrefixes: ['jamendo-', 'aporee_'],
    extensions: ['.mp3', '.ogg', '.m4a'],
    minBytes: 500000,
    maxBytes: 20000000,
    rows: 50,
    query: 'title:(ambient OR drone OR soundscape) AND mediatype:audio AND -collection:podcasts AND -collection:audio_bookspoetry'
  };

  /**
   * 推导远程清单候选 URL（§2.3 / AD-04）。
   * - 显式 REMOTE_MANIFEST 优先，并派生 GitHub Raw 备用。
   * - 否则仅当 hostname 为 <user>.github.io 且路径首段非空时，生成
   *   main/master × jsDelivr/GitHub Raw 共 4 个候选。
   * - file:// / localhost / 自定义域未配置 → 空数组（完全跳过 L2/L3）。
   * @param {string|null} explicit 部署者填写的唯一常量
   * @returns {string[]}
   */
  function deriveRemotes(explicit) {
    var out = [];
    try {
      var loc = window.location;
      var protocol = loc.protocol || '';
      var host = loc.hostname || '';
      var pathname = loc.pathname || '';
      if (protocol === 'file:') { return out; }

      if (explicit) {
        out.push(explicit);
        var m = /^https:\/\/cdn\.jsdelivr\.net\/gh\/([^/]+)\/([^@]+)@([^/]+)\/(.+)$/.exec(explicit);
        if (m) {
          out.push('https://raw.githubusercontent.com/' + m[1] + '/' + m[2] + '/' + m[3] + '/' + m[4]);
        }
        return out;
      }

      var gm = /^([^.]+)\.github\.io$/i.exec(host);
      if (!gm) { return out; }
      var segments = pathname.split('/').filter(Boolean);
      if (!segments.length) { return out; }
      var user = gm[1];
      var repo = segments[0];
      var branches = ['main', 'master'];
      var manifestPath = 'data/audio-sources.json';
      for (var i = 0; i < branches.length; i += 1) {
        var b = branches[i];
        out.push('https://cdn.jsdelivr.net/gh/' + user + '/' + repo + '@' + b + '/' + manifestPath);
        out.push('https://raw.githubusercontent.com/' + user + '/' + repo + '/' + b + '/' + manifestPath);
      }
    } catch (err) {
      return [];
    }
    return out;
  }

  /** 是否为调试模式（URL 带 ?debug=1）。 */
  function isDebug() {
    try {
      return /(?:^|[?&])debug=1(?:&|$)/.test(window.location.search || '');
    } catch (err) {
      return false;
    }
  }

  /** 是否偏好减少动效。 */
  function prefersReducedMotion() {
    try {
      return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (err) {
      return false;
    }
  }

  var REMOTE_MANIFEST = null; // 唯一可配置常量；null = 未配置且功能 100% 完整
  var resolvedRemotes = deriveRemotes(REMOTE_MANIFEST);

  /** 冻结常量对象（运行时不允许改写任何字段）。 */
  var config = {
    REMOTE_MANIFEST: REMOTE_MANIFEST,
    resolvedRemotes: resolvedRemotes,
    REMOTE_BRANCHES: ['main', 'master'],
    REMOTE_TIMEOUT_MS: 3000,
    REMOTE_TTL_MS: 86400000,
    LOAD_TIMEOUT_MS: 3000,
    RADIO_TIMEOUT_MS: 5000,
    CROSSFADE_MS: 600,
    MAX_TRACKS: 3,
    COOLDOWN_MS: 600000,
    LOG_LIMIT: 200,
    ENABLE_RADIO: false,
    ENABLE_DISCOVERY: true,
    SCENE_IDS: SCENE_IDS,
    SCENES: SCENES,
    SYNTH_VOICES: SYNTH_VOICES,
    VOICE_LABELS: VOICE_LABELS,
    FILTER_BLACKLIST: FILTER_BLACKLIST,
    FILTER_RULES: FILTER_RULES,
    STORAGE_KEYS: STORAGE_KEYS,
    EVENTS: EVENTS,
    DEBUG: isDebug(),
    REDUCED_MOTION: prefersReducedMotion(),
    MANIFEST_SCHEMA: 'stillwave-audio-manifest/v1'
  };
  Object.freeze(config.SCENE_IDS);
  Object.freeze(config.SYNTH_VOICES);
  Object.freeze(config.VOICE_LABELS);
  Object.freeze(config.FILTER_BLACKLIST);
  Object.freeze(config.STORAGE_KEYS);
  Object.freeze(config.EVENTS);
  Object.freeze(config);

  SW.config = config;

  /**
   * 运行时诊断/故障注入槽（可变，与冻结常量分离）。
   * 仅供 ?debug=1 的 __STILLWAVE__.inject.* 写入；各模块只读。
   */
  SW.RUNTIME = {
    loadTimeoutMs: config.LOAD_TIMEOUT_MS,
    forceTimeoutNext: 0,
    forceFailureOnce: null,
    offline: false,
    storageUnavailable: false,
    manifestOverrides: {},
    forceTier: null,
    degradeEvents: [],
    lastDegradeDurationMs: null,
    consoleErrorCount: 0,
    toastText: null
  };
})();

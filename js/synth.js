/* ==========================================================================
 * 静澜 Stillwave · js/synth.js
 * 职责：音频内核。懒创建 AudioContext（仅用户手势后）、四级统一增益总线、
 *       10 种程序化声景（零网络）、共享噪声缓冲 + 双缓冲错相循环消除接缝、
 *       等功率包络 ramp、在线 <audio> 的 MediaElement 接入、资源释放。
 * 约束：不引用 sources / player / ui；页面加载阶段 getContext() === null。
 * 装载：第 5 位。
 * ========================================================================== */
;(function () {
  'use strict';

  var SW = (window.SW = window.SW || {});
  var C = SW.config;

  var ctx = null;                 // 首次手势前恒为 null（P0-11）
  var graph = null;
  var buffers = Object.create(null); // 共享噪声缓冲（white / pink / brown）
  var seq = 0;
  var gainState = { master: 0.45, fade: 1.0 };

  /** 10 种声景的合成参数（全部由共享噪声 + 滤波 + 缓慢 LFO 组合）。 */
  var VOICE_SPEC = {
    white:  { noise: 'white', filters: [], lfoRate: 1 / 14, lfoDepth: 0.10, base: 0.55 },
    pink:   { noise: 'pink',  filters: [], lfoRate: 1 / 16, lfoDepth: 0.10, base: 0.70 },
    brown:  { noise: 'brown', filters: [{ type: 'lowpass', freq: 900, q: 0.7 }], lfoRate: 1 / 18, lfoDepth: 0.10, base: 0.80 },
    rain:   { noise: 'white', filters: [{ type: 'highpass', freq: 420, q: 0.7 }, { type: 'lowpass', freq: 6500, q: 0.7 }], lfoRate: 1 / 11, lfoDepth: 0.16, base: 0.55 },
    stream: { noise: 'pink',  filters: [{ type: 'bandpass', freq: 900, q: 0.7 }], lfoRate: 1 / 9, lfoDepth: 0.20, base: 0.80 },
    wind:   { noise: 'brown', filters: [{ type: 'lowpass', freq: 700, q: 0.7 }], lfoRate: 1 / 12, lfoDepth: 0.30, base: 0.85, filterLfo: 0.35 },
    waves:  { noise: 'brown', filters: [{ type: 'lowpass', freq: 480, q: 0.7 }], lfoRate: 1 / 14, lfoDepth: 0.38, base: 0.85, filterLfo: 0.30 },
    bowl:   { noise: 'pink',  filters: [{ type: 'lowpass', freq: 1200, q: 0.7 }], lfoRate: 1 / 19, lfoDepth: 0.22, base: 0.42, partials: [196, 294, 392, 588] },
    fire:   { noise: 'white', filters: [{ type: 'highpass', freq: 180, q: 0.7 }, { type: 'lowpass', freq: 1100, q: 0.7 }], lfoRate: 1 / 7, lfoDepth: 0.34, base: 0.50 },
    forest: { noise: 'pink',  filters: [{ type: 'bandpass', freq: 1500, q: 0.5 }, { type: 'lowpass', freq: 5000, q: 0.7 }], lfoRate: 1 / 10, lfoDepth: 0.18, base: 0.65 }
  };

  /** 同步创建 AudioContext（仅在用户手势调用链内使用）。 */
  function createContextSync() {
    if (ctx) { return ctx; }
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) { return null; }
    ctx = new AC();
    return ctx;
  }

  /**
   * 确保 AudioContext 存在并 running；仅在首次用户手势后调用。
   * @returns {Promise<AudioContext>}
   */
  function ensureContext() {
    var c = createContextSync();
    if (!c) { return Promise.reject(new Error('no-webaudio')); }
    if (c.state === 'suspended' && typeof c.resume === 'function') {
      return c.resume().then(function () { return c; }, function () { return c; });
    }
    return Promise.resolve(c);
  }

  /** 加载态返回 null（P0-11 断言入口）。 */
  function getContext() { return ctx; }

  /**
   * 构建四级统一增益总线：trackGain_i → mixBus → fadeGain → masterGain → destination。
   * 幂等：重复调用返回同一图，避免重复 disconnect。
   * @returns {{ctx:AudioContext,mixBus:GainNode,fadeGain:GainNode,masterGain:GainNode}}
   */
  function createGraph() {
    var c = createContextSync();
    if (!c) { return null; }
    if (graph && graph.ctx === c) { return graph; }
    var mixBus = c.createGain();
    mixBus.gain.value = 1;
    var fadeGain = c.createGain();
    fadeGain.gain.value = gainState.fade;
    var masterGain = c.createGain();
    masterGain.gain.value = gainState.master;
    mixBus.connect(fadeGain);
    fadeGain.connect(masterGain);
    masterGain.connect(c.destination);
    graph = { ctx: c, mixBus: mixBus, fadeGain: fadeGain, masterGain: masterGain };
    return graph;
  }

  /**
   * 生成共享噪声缓冲（white / pink / brown），带首尾交叉淡化消除循环接缝。
   * 全局复用，不随播放时长重复分配（NFR-07 / A7）。
   */
  function buildNoiseBuffer(kind) {
    if (buffers[kind]) { return buffers[kind]; }
    var seconds = 7;
    var length = Math.floor(ctx.sampleRate * seconds);
    var buffer = ctx.createBuffer(2, length, ctx.sampleRate);
    for (var ch = 0; ch < 2; ch += 1) {
      var data = buffer.getChannelData(ch);
      var b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0, last = 0;
      for (var i = 0; i < length; i += 1) {
        var w = Math.random() * 2 - 1;
        if (kind === 'white') {
          data[i] = w * 0.55;
        } else if (kind === 'pink') {
          /* Paul Kellet 的 1/f 近似，多阶一阶低通叠加 */
          b0 = 0.99886 * b0 + w * 0.0555179;
          b1 = 0.99332 * b1 + w * 0.0750759;
          b2 = 0.96900 * b2 + w * 0.1538520;
          b3 = 0.86650 * b3 + w * 0.3104856;
          b4 = 0.55000 * b4 + w * 0.5329522;
          b5 = -0.7616 * b5 - w * 0.0168980;
          data[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.11 * 0.75;
          b6 = w * 0.115926;
        } else {
          /* 棕噪：带泄漏积分，低频更宜夜间 */
          last = (last + 0.02 * w) / 1.02;
          data[i] = last * 3.5 * 0.5;
        }
      }
      /* 首尾交叉淡化：让最后一个样本平滑逼近第一个样本 */
      var fade = Math.floor(ctx.sampleRate * 0.25);
      for (var j = 0; j < fade; j += 1) {
        var k = j / fade;
        data[length - fade + j] = data[length - fade + j] * (1 - k) + data[j] * k;
      }
    }
    buffers[kind] = buffer;
    return buffer;
  }

  /** 创建滤波器链，返回 {head, nodes}。 */
  function buildFilterChain(spec) {
    var nodes = [];
    var head = null;
    var prev = null;
    for (var i = 0; i < spec.filters.length; i += 1) {
      var f = spec.filters[i];
      var node = ctx.createBiquadFilter();
      node.type = f.type;
      node.frequency.value = f.freq;
      node.Q.value = f.q || 0.7;
      nodes.push(node);
      if (prev) { prev.connect(node); } else { head = node; }
      prev = node;
    }
    return { head: head, tail: prev, nodes: nodes };
  }

  /**
   * 创建一条程序化声景轨（VoiceHandle）。
   * 结构：双错相噪声源 → 滤波器链 → envGain → driftGain → trackGain → mixBus。
   * @param {string} voice VoiceId
   * @param {Object} g AudioGraph
   * @param {{volume?:number, lowpassHz?:number}=} opts
   * @returns {Object} VoiceHandle
   */
  function createVoice(voice, g, opts) {
    var options = opts || {};
    var spec = VOICE_SPEC[voice] || VOICE_SPEC.brown;
    var buffer = buildNoiseBuffer(spec.noise);
    seq += 1;
    var handle = {
      id: 'voice-' + seq, type: 'synth', voice: voice,
      nodes: [], sources: [], element: null, mediaSource: null,
      userVolume: typeof options.volume === 'number' ? options.volume : 1,
      started: false, trackGain: null, driftGain: null, envGain: null
    };

    var trackGain = ctx.createGain();
    trackGain.gain.value = 0;                 // 由 player 在 crossfade 中淡入到目标值
    var driftGain = ctx.createGain();         // P1-03 自动漂移专用，独立于用户音量
    driftGain.gain.value = 1;
    var envGain = ctx.createGain();
    envGain.gain.value = spec.base;
    handle.trackGain = trackGain;
    handle.driftGain = driftGain;
    handle.envGain = envGain;
    handle.nodes.push(trackGain, driftGain, envGain);

    var chain = buildFilterChain(spec);
    chain.nodes.forEach(function (n) { handle.nodes.push(n); });
    if (chain.tail) {
      chain.tail.connect(envGain);
    }
    envGain.connect(driftGain);
    driftGain.connect(trackGain);
    trackGain.connect(g.mixBus);

    /* 缓慢 LFO：周期 7~19s ≥8s，用于音色演化与错相交叠（P1-03 / NFR-09） */
    var lfo = ctx.createOscillator();
    lfo.type = 'sine';
    lfo.frequency.value = spec.lfoRate;
    var lfoAmount = ctx.createGain();
    lfoAmount.gain.value = spec.lfoDepth;
    lfo.connect(lfoAmount);
    lfoAmount.connect(envGain.gain);
    handle.nodes.push(lfoAmount);
    handle.sources.push(lfo);

    /* 双缓冲错相循环：两个源错开半个周期，互补增益让总能量恒定、接缝不可辨 */
    var a = ctx.createBufferSource();
    a.buffer = buffer; a.loop = true;
    var b = ctx.createBufferSource();
    b.buffer = buffer; b.loop = true;
    var ga = ctx.createGain(); ga.gain.value = 0.5;
    var gb = ctx.createGain(); gb.gain.value = 0.5;
    var crossAmount = ctx.createGain(); crossAmount.gain.value = 0.22;
    var invert = ctx.createGain(); invert.gain.value = -1;
    lfo.connect(crossAmount);
    crossAmount.connect(ga.gain);
    crossAmount.connect(invert);
    invert.connect(gb.gain);
    a.connect(ga); b.connect(gb);
    if (chain.head) { ga.connect(chain.head); gb.connect(chain.head); }
    else { ga.connect(envGain); gb.connect(envGain); }
    handle.nodes.push(ga, gb, crossAmount, invert, a, b);
    handle.sources.push(a, b);

    /* 缓慢调制滤波截止频率，模拟风/海浪的自然演化 */
    if (spec.filterLfo && chain.nodes.length) {
      var filterMod = ctx.createGain();
      filterMod.gain.value = chain.nodes[0].frequency.value * spec.filterLfo;
      lfo.connect(filterMod);
      filterMod.connect(chain.nodes[0].frequency);
      handle.nodes.push(filterMod);
    }

    /* 颂钵：叠加多个正弦分音 + 缓慢包络，不刺耳、按呼吸节拍感起伏 */
    if (spec.partials) {
      var partialBus = ctx.createGain();
      partialBus.gain.value = 0.05;
      partialBus.connect(envGain);
      handle.nodes.push(partialBus);
      spec.partials.forEach(function (freq, idx) {
        var osc = ctx.createOscillator();
        osc.type = 'sine';
        osc.frequency.value = freq;
        var og = ctx.createGain();
        og.gain.value = 0.16 / (idx + 1);
        osc.connect(og); og.connect(partialBus);
        handle.nodes.push(og);
        handle.sources.push(osc);
      });
    }

    var now = ctx.currentTime;
    /* LFO / 分音振荡器统一启动；错相循环源单独带 offset 启动，不可重复 start */
    handle.sources.forEach(function (src) {
      if (src === a || src === b) { return; }
      try { src.start(now); } catch (err) { /* 静默 */ }
    });
    try {
      a.start(now, 0);
      b.start(now, buffer.duration / 2);
    } catch (err) { /* 静默 */ }
    handle.started = true;
    return handle;
  }

  /**
   * 把在线 <audio> 元素接入统一总线（MediaElementAudioSourceNode 每元素仅创建一次）。
   * @param {HTMLAudioElement} element
   * @param {Object} g AudioGraph
   * @param {{lowpassHz?:number}=} opts
   * @returns {Object} VoiceHandle
   */
  function createMediaHandle(element, g, opts) {
    var options = opts || {};
    seq += 1;
    var handle = {
      id: 'media-' + seq, type: 'audio', voice: null,
      nodes: [], sources: [], element: element, mediaSource: null,
      userVolume: 1, started: false, trackGain: null, driftGain: null, envGain: null
    };
    var mediaSource = ctx.createMediaElementSource(element);
    var trackGain = ctx.createGain();
    trackGain.gain.value = 0;
    var driftGain = ctx.createGain();
    driftGain.gain.value = 1;
    var filter = null;
    if (options.lowpassHz > 0) {
      filter = ctx.createBiquadFilter();
      filter.type = 'lowpass';
      filter.frequency.value = options.lowpassHz;
      handle.nodes.push(filter);
    }
    mediaSource.connect(filter || driftGain);
    if (filter) { filter.connect(driftGain); }
    driftGain.connect(trackGain);
    trackGain.connect(g.mixBus);
    handle.mediaSource = mediaSource;
    handle.trackGain = trackGain;
    handle.driftGain = driftGain;
    handle.envGain = null;
    handle.nodes.push(mediaSource, driftGain, trackGain);
    return handle;
  }

  /** 用户主音量（masterGain）。记录设定值供契约断言「降级不改音量」。 */
  function setMaster(v) {
    var value = Math.max(0, Math.min(1, Number(v) || 0));
    gainState.master = value;
    if (graph) { rampGain(graph.masterGain.gain, value, 80); }
  }

  /**
   * 定时渐弱专用（fadeGain），取消定时器时由 timer 恢复 1.0。
   * @param {number} v 目标值
   * @param {number=} ms 可选 ramp 时长（定时渐弱传入 fadeSeconds*1000，实现连续下降）
   */
  function setFade(v, ms) {
    var value = Math.max(0, Math.min(1, Number(v) || 0));
    gainState.fade = value;
    if (graph) { rampGain(graph.fadeGain.gain, value, typeof ms === 'number' ? ms : 80); }
  }

  /** 分轨音量（trackGain_i），不改写其它节点。 */
  function setTrackGain(handle, v) {
    if (!handle || !handle.trackGain) { return; }
    var value = Math.max(0, Math.min(1, Number(v) || 0));
    handle.userVolume = value;
    rampGain(handle.trackGain.gain, value, 80);
  }

  /** 自动漂移专用（driftGain），与用户音量完全解耦（P1-03 ±15%）。 */
  function setDriftGain(handle, v) {
    if (!handle || !handle.driftGain) { return; }
    rampGain(handle.driftGain.gain, Math.max(0, Math.min(1.2, Number(v) || 0)), 4000);
  }

  /** 等功率包络 / 渐弱 / crossfade 的统一 ramp。 */
  function rampGain(param, to, ms) {
    if (!param || !ctx) { return; }
    try {
      var now = ctx.currentTime;
      var duration = Math.max(0.001, (Number(ms) || 0) / 1000);
      var current = typeof param.value === 'number' ? param.value : to;
      param.cancelScheduledValues(now);
      param.setValueAtTime(current, now);
      param.linearRampToValueAtTime(to, now + duration);
    } catch (err) { /* 静默，绝不外抛 */ }
  }

  /** 当前有效增益（用户设定值，非 AudioParam 瞬时值，供契约断言）。 */
  function getEffectiveGain() {
    return { master: gainState.master, fade: gainState.fade };
  }

  /** 释放一条声轨：stop + disconnect + 释放引用（防 60 分钟内存泄漏）。 */
  function releaseVoice(handle) {
    if (!handle) { return; }
    var i;
    for (i = 0; i < handle.sources.length; i += 1) {
      try { handle.sources[i].stop(); } catch (err) { /* 已停止 */ }
      try { handle.sources[i].disconnect(); } catch (err) { /* 静默 */ }
    }
    for (i = 0; i < handle.nodes.length; i += 1) {
      try { handle.nodes[i].disconnect(); } catch (err) { /* 静默 */ }
    }
    if (handle.mediaSource) {
      try { handle.mediaSource.disconnect(); } catch (err) { /* 静默 */ }
      handle.mediaSource = null;
    }
    if (handle.element) {
      try {
        handle.element.pause();
        handle.element.removeAttribute('src');
        handle.element.load();
      } catch (err) { /* 静默 */ }
      handle.element = null;
    }
    handle.nodes.length = 0;
    handle.sources.length = 0;
    handle.trackGain = null;
    handle.driftGain = null;
    handle.envGain = null;
    handle.started = false;
  }

  SW.synth = {
    ensureContext: ensureContext,
    getContext: getContext,
    createGraph: createGraph,
    createVoice: createVoice,
    setMaster: setMaster,
    setFade: setFade,
    setTrackGain: setTrackGain,
    setDriftGain: setDriftGain,
    rampGain: rampGain,
    releaseVoice: releaseVoice,
    getEffectiveGain: getEffectiveGain,
    /* 契约所需的扩展：把在线 <audio> 接入同一总线（S-08：仅 cors===true 的实测 URL） */
    createMediaHandle: createMediaHandle,
    getVoiceIds: function () { return C.SYNTH_VOICES.slice(); }
  };
})();

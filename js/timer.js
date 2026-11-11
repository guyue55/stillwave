/* ==========================================================================
 * 静澜 Stillwave · js/timer.js
 * 职责：睡眠定时器（15/30/45/60/90/自定义）+ 渐弱（关/30/60/120s）+
 *       单实例 + 250ms 墙钟校准（误差 ≤1s）+ 只操作 fadeGain +
 *       到时停止 + 取消恢复原音量 + 剩余时间广播。
 * 约束：绝不改写 masterGain 与用户音量设定值（AD-07 / AD-14）。
 * 装载：第 7 位。
 * ========================================================================== */
;(function () {
  'use strict';

  var SW = (window.SW = window.SW || {});
  var C = SW.config;
  var E = C.EVENTS;
  var store = SW.store;

  var handle = null;
  var fadeStarted = false;
  var lastBroadcast = 0;

  /** 定时器状态（§4.3 TimerState）。 */
  var state = {
    active: false, remainingMs: 0, phase: 'idle',
    fadeSeconds: 0, minutes: 0, endsAt: null
  };

  /** 状态快照。 */
  function getState() { return Object.assign({}, state); }

  /** 把状态广播到 store（1 秒一次，避免 250ms 全量渲染造成长任务）。 */
  function broadcast(force) {
    var now = Date.now();
    if (!force && now - lastBroadcast < 1000) { return; }
    lastBroadcast = now;
    store.patch({ timer: getState() });
    store.emit(E.TIMER_TICK, getState());
  }

  /** 单 tick：墙钟校准，处理渐弱进入与到时结束。 */
  function tick() {
    if (!state.active) { return; }
    var now = Date.now();
    var remaining = Math.max(0, state.endsAt - now);
    state.remainingMs = remaining;
    var fadeMs = state.fadeSeconds * 1000;

    if (fadeMs > 0 && remaining <= fadeMs && remaining > 0 && !fadeStarted) {
      fadeStarted = true;
      state.phase = 'fading';
      /* 连续缓动下降：只对 fadeGain 做 ramp，masterGain 与分轨音量完全不动 */
      SW.synth.setFade(0, Math.max(200, remaining));
      store.emit(E.TIMER_FADING, getState());
      broadcast(true);
    } else if (state.phase !== 'fading') {
      state.phase = 'counting';
    }

    if (remaining <= 0) {
      finish();
      return;
    }
    broadcast(false);
  }

  /** 到时：停止全部音轨、保留混音与音量配置、播放态回到待播放。 */
  function finish() {
    stopInterval();
    state.remainingMs = 0;
    state.active = false;
    state.phase = 'ended';
    state.endsAt = null;
    /* 渐弱已完成（或渐弱关闭时到时直接停），恢复 fadeGain 以便下次播放不残留 */
    SW.synth.setFade(1, 300);
    if (SW.player && typeof SW.player.pause === 'function') {
      SW.player.pause();
    }
    store.patch({ timer: getState(), playing: false, playState: 'paused' });
    store.emit(E.TIMER_ENDED, getState());
    store.pushLog({ type: 'timer', action: 'ended', minutes: state.minutes, fadeSeconds: state.fadeSeconds });
  }

  /** 停止内部 interval（单实例保证）。 */
  function stopInterval() {
    if (handle !== null) { window.clearInterval(handle); handle = null; }
  }

  /**
   * 启动定时器（单实例，重复调用会先取消上一次）。
   * @param {number} minutes 时长（>0）
   * @param {0|30|60|120} fadeSeconds 渐弱秒数
   */
  function start(minutes, fadeSeconds) {
    cancel();
    var mins = Math.max(0, Number(minutes) || 0);
    if (mins <= 0) { return; }
    var fade = [0, 30, 60, 120].indexOf(fadeSeconds) >= 0 ? fadeSeconds : 0;
    var durationMs = Math.round(mins * 60000);
    state = {
      active: true,
      remainingMs: durationMs,
      phase: 'counting',
      fadeSeconds: fade,
      minutes: mins,
      endsAt: Date.now() + durationMs
    };
    fadeStarted = false;
    lastBroadcast = 0;
    /* 确保从 1.0 开始（不改写用户音量） */
    SW.synth.setFade(1, 80);
    store.patch({
      timer: getState(),
      timerPresetMinutes: mins,
      timerPresetFade: fade
    });
    store.pushLog({ type: 'timer', action: 'start', minutes: mins, fadeSeconds: fade });
    handle = window.setInterval(tick, 250);
    broadcast(true);
  }

  /**
   * 运行中调整渐弱档位（不重置倒计时、不改写用户音量）。
   * @param {0|30|60|120} fadeSeconds
   */
  function setFadeSeconds(fadeSeconds) {
    var fade = [0, 30, 60, 120].indexOf(fadeSeconds) >= 0 ? fadeSeconds : 0;
    state.fadeSeconds = fade;
    if (state.phase === 'fading') {
      if (fade === 0) {
        fadeStarted = false;
        state.phase = 'counting';
        SW.synth.setFade(1, 300);
      } else {
        SW.synth.setFade(0, Math.max(200, state.remainingMs));
      }
    }
    store.patch({ timer: getState(), timerPresetFade: fade });
  }

  /** 取消定时：fadeGain 平滑恢复 1.0，用户音量设定值不变，播放继续。 */
  function cancel() {
    var wasActive = state.active;
    stopInterval();
    fadeStarted = false;
    var previousFade = state.fadeSeconds;
    var previousMinutes = state.minutes;
    state = {
      active: false, remainingMs: 0, phase: 'idle',
      fadeSeconds: 0, minutes: 0, endsAt: null
    };
    SW.synth.setFade(1, 300);
    store.patch({ timer: getState() });
    if (wasActive) {
      store.pushLog({ type: 'timer', action: 'cancel', minutes: previousMinutes, fadeSeconds: previousFade });
      store.emit(E.TIMER_TICK, getState());
    }
  }

  /** 释放资源。 */
  function dispose() { stopInterval(); }

  SW.timer = {
    start: start,
    cancel: cancel,
    getState: getState,
    dispose: dispose,
    /* 契约 / UI 所需的扩展：运行中调整渐弱而不重置倒计时 */
    setFadeSeconds: setFadeSeconds
  };
})();

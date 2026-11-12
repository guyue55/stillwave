/* ==========================================================================
 * 静澜 Stillwave · js/ui.js
 * 职责：DOM 绑定与渲染（七分区）、全量 aria 同步、徽标四态 + 3.5s 轻提示、
 *       P1-01 呼吸圆环（4-4 / 4-7-8，reduced-motion 降级静态文字）、
 *       P1-03 自动漂移开关、P1-06 快捷键、P1-07 音源详情面板、
 *       音源信息许可展开、亮度三档、混音卡片、定时器三态。
 * 约束：只订阅 store 事件与调用 player/timer/sources 的公开方法；
 *       绝不直接访问 AudioContext / 音频节点（§8.2）。
 * 装载：第 8 位。
 * ========================================================================== */
;(function () {
  'use strict';

  var SW = (window.SW = window.SW || {});
  var C = SW.config;
  var E = C.EVENTS;
  var store = SW.store;
  var player = SW.player;
  var timer = SW.timer;
  var sources = SW.sources;

  var el = {};
  var lastMixSignature = '';
  var lastLibSignature = '';
  var libFilter = { scene: 'all', kind: 'all' };
  var LIB_SCENES = ['all', 'focus', 'sleep', 'empty', 'meditation'];
  var LIB_SCENE_LABELS = { all: '全部', focus: '学习', sleep: '助眠', empty: '放空', meditation: '冥想' };
  var LIB_KINDS = ['all', 'music', 'nature'];
  var LIB_KIND_LABELS = { all: '全部', music: '氛围音乐', nature: '自然录音' };
  var lastBreathKey = '';
  var breathStart = 0;
  var breathTimer = null;
  var progressTimer = null;
  var toastTimer = null;
  var toastHideTimer = null;
  var selectedFade = 0;

  /** HTML 转义（所有动态文本统一走这里）。 */
  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  /** 原始条目链接的固定可见文案兜底（AD-23：href 指向 item，页面不显示裸 URL）。 */
  var ITEM_LINK_LABEL = '查看原始条目页 ↗';

  /** 从绝对 URL 提取来源域名（不暴露技术细节给用户）。 */
  function hostOf(url) {
    try { return new URL(url).hostname; } catch (err) { return 'archive.org'; }
  }

  /** 缓存 DOM 引用。 */
  function cacheDom() {
    [
      'badge', 'badge-text', 'btn-brightness', 'brightness-label', 'btn-refresh',
      'scene-tabs', 'scene-caption', 'scene-panel', 'visual-slogan', 'visual-caption',
      'breath-ring', 'breath-phase', 'breath-controls',
      'now-title', 'btn-info', 'info-panel', 'btn-play', 'play-icon',
      'progress-fill', 'progress-time', 'btn-next',
      'master-volume', 'master-volume-value',
      'mix-count', 'btn-add', 'mix-cards', 'voice-picker', 'mix-empty',
      'custom-minutes', 'btn-custom-timer', 'timer-remaining', 'btn-cancel-timer',
      'lib-status', 'btn-details', 'details-panel', 'btn-library', 'library-panel',
      'btn-drift', 'btn-clear', 'toast'
    ].forEach(function (id) { el[id] = document.getElementById(id); });
    el.ringCircle = el['breath-ring'] ? el['breath-ring'].querySelector('.ring-circle') : null;
    el.tabs = el['scene-tabs'] ? Array.prototype.slice.call(el['scene-tabs'].querySelectorAll('.tab')) : [];
    el.presets = Array.prototype.slice.call(document.querySelectorAll('.preset'));
  }

  /** 一行简体中文轻提示（aria-live=polite，3.5s 自动淡出，绝不弹窗）。 */
  function toast(message) {
    if (!message || !el.toast) { return; }
    var text = String(message);
    SW.RUNTIME.toastText = text;
    el.toast.textContent = text;
    el.toast.hidden = false;
    window.requestAnimationFrame(function () { el.toast.classList.add('is-visible'); });
    if (toastTimer !== null) { window.clearTimeout(toastTimer); }
    if (toastHideTimer !== null) { window.clearTimeout(toastHideTimer); }
    toastTimer = window.setTimeout(function () {
      el.toast.classList.remove('is-visible');
      toastHideTimer = window.setTimeout(function () { el.toast.hidden = true; }, 700);
    }, 3500);
  }

  /** 「刷新曲库」三态（进行中 / 成功 / 失败）。 */
  function onRefresh() {
    if (!sources) { return; }
    toast('正在为你更新曲库…');
    sources.refresh({ silent: false }).then(function (result) {
      if (result.status === 'updated') {
        toast('曲库已更新，现有 ' + result.count + ' 首可用');
      } else if (result.status === 'failed') {
        toast('暂时无法更新，现有声音仍可正常使用');
      } else if (result.status === 'skipped') {
        toast('当前使用内置曲库，声音可正常播放');
      } else {
        toast('曲库已是最新');
      }
      render(store.getState());
    });
  }

  /** 亮度三档循环切换。 */
  var BRIGHTNESS_ORDER = ['normal', 'dark', 'extreme'];
  var BRIGHTNESS_LABELS = { normal: '常规', dark: '暗', extreme: '极暗熄屏' };
  function cycleBrightness() {
    var current = store.getState().brightness;
    var idx = BRIGHTNESS_ORDER.indexOf(current);
    var next = BRIGHTNESS_ORDER[(idx + 1 + BRIGHTNESS_ORDER.length) % BRIGHTNESS_ORDER.length];
    setBrightness(next);
  }
  function setBrightness(value) {
    document.documentElement.setAttribute('data-brightness', value);
    store.patch({ brightness: value });
    store.emit(E.BRIGHTNESS_CHANGED, { brightness: value });
    store.savePrefs();
    toast('亮度已切换为「' + BRIGHTNESS_LABELS[value] + '」');
  }

  /** 打开/关闭折叠面板并同步 aria-expanded。 */
  function togglePanel(button, panel) {
    if (!button || !panel) { return; }
    var open = panel.hidden;
    panel.hidden = !open;
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) { render(store.getState()); }
  }

  /**
   * 音源信息（AD-21 零泄露）：曲目展示数据一律取 SW.sources.sanitizeForUI() 白名单投影后的
   * UiTrack；展示层在架构上拿不到源标题，也不显示任何裸 URL / 错误码。
   * 查证四件套由 getAttribution() 的 AttributionView 提供，署名文案不虚构作者。
   */
  function renderInfoPanel(state) {
    if (!el['info-panel'] || el['info-panel'].hidden) { return; }
    var trackId = null;
    if (state.currentSource && state.currentSource.trackId) {
      trackId = state.currentSource.trackId;
    } else if (state.tracks.length && state.tracks[0].trackId) {
      trackId = state.tracks[0].trackId;
    }
    var attr = trackId ? sources.getAttribution(trackId) : null;
    /* getUiTrack 是 sources 层对 sanitizeForUI() 投影的只读出口；再投影一次做防御性兜底 */
    var projected = trackId ? sources.getUiTrack(trackId) : null;
    var view = projected ? sources.sanitizeForUI(projected) : null;
    if (!attr || !attr.found || !view) {
      el['info-panel'].innerHTML = '<p>当前使用本地合成声，由浏览器实时生成，零网络依赖、永不失效。</p>';
      return;
    }
    el['info-panel'].innerHTML =
      '<dl>' +
      '<dt>曲名</dt><dd>' + esc(view.display) + '</dd>' +
      '<dt>来源</dt><dd>' + esc(view.source) + '</dd>' +
      '<dt>许可</dt><dd>' + esc(view.licenseText) + '</dd>' +
      '<dt>署名</dt><dd>' + esc(attr.attributionText) + '</dd>' +
      '<dt>原始条目</dt><dd><a href="' + esc(attr.item) + '" target="_blank" rel="noopener noreferrer">' +
      esc(view.itemLabel || ITEM_LINK_LABEL) + '</a></dd>' +
      '</dl>';
  }

  /**
   * P1-07 音源详情面板：条目数 / byScene / byKind / 健康状态 / 来源域名 / 上次更新 / 许可 / 候选。
   * AD-21：曲目展示字段一律走 sanitizeForUI() 白名单投影；源数据层的元数据调试区已整块撤销，
   *        不作任何形式的渲染（包括默认折叠区）；item 仅作 href，不作为可见文本。
   * 面板内容常驻 DOM（由 [hidden] 控制显隐），保证 A14 四处曲目名可随时真实扫描断言。
   */
  function renderDetailsPanel() {
    if (!el['details-panel']) { return; }
    var summary = sources.getManifestSummary();
    var manifest = sources.getManifest();
    var health = sources.getHealth();
    var tracks = manifest ? manifest.tracks : [];
    var domains = {};
    var aliveCount = 0;
    tracks.forEach(function (t) {
      domains[hostOf(t.item)] = (domains[hostOf(t.item)] || 0) + 1;
      if (t.health !== 'dead' && t.enabled !== false) { aliveCount += 1; }
    });
    var domainText = Object.keys(domains).map(function (d) { return esc(d) + '（' + domains[d] + ' 首）'; }).join('、');
    var updated = summary.updatedAt ? esc(summary.updatedAt.slice(0, 10)) : '内置快照';
    var byKind = summary.byKind || { music: 0, nature: 0 };

    var html =
      '<h3>曲库概览</h3><ul>' +
      '<li>已验证曲目：<strong>' + summary.count + '</strong> 首（可用 ' + aliveCount + ' 首）</li>' +
      '<li>场景分布：学习 ' + summary.byScene.focus + ' · 助眠 ' + summary.byScene.sleep +
      ' · 放空 ' + summary.byScene.empty + ' · 冥想 ' + summary.byScene.meditation + '</li>' +
      '<li>曲目构成：氛围音乐 ' + byKind.music + ' 首 · 真实自然录音 ' + byKind.nature + ' 首</li>' +
      '<li>来源域名：' + (domainText || 'archive.org') + '</li>' +
      '<li>清单版本：v' + summary.version + ' · 上次更新：' + updated + '</li>' +
      '<li>健康度记录：' + Object.keys(health).length + ' 条（降权跨会话生效）</li>' +
      '<li>隔离区：' + summary.quarantined + ' 条（保留可恢复信息，不清空清单）</li>' +
      '</ul>';

    html += '<h3>发现的候选（待校验，不会播放）</h3>';
    var candidates = sources.getCandidates();
    if (!candidates.length) {
      html += '<p>暂无待校验候选。动态发现的结果只作补充，需人工确认后才会进入曲库。</p>';
    } else {
      html += '<ul>';
      candidates.slice(0, 20).forEach(function (c) {
        html += '<li>' + esc(c.display) + ' · 待审定 · ' + esc(hostOf(c.item)) + '</li>';
      });
      html += '</ul>';
    }

    html += '<details><summary>音源许可与署名清单（' + tracks.length + ' 首，点击展开）</summary><ul>';
    tracks.forEach(function (t) {
      var view = sources.sanitizeForUI(t);
      html += '<li data-track-name="' + esc(view.display) + '">' + esc(view.display) +
        ' · ' + esc(view.source) + ' · ' + esc(view.licenseText) +
        ' · <a href="' + esc(t.item) + '" target="_blank" rel="noopener noreferrer">' +
        esc(view.itemLabel || ITEM_LINK_LABEL) + '</a></li>';
    });
    html += '</ul></details>';

    el['details-panel'].innerHTML = html;
  }

  /**
   * 声音库：可浏览 / 可筛选 / 可点选的曲目清单（P1-09）。
   * 数据一律来自 sources.getUiTrackList() 的 UiTrack 白名单投影，展示层拿不到
   * url / 源标题 / bytes / health 等源数据字段（AD-21）。
   * 用 data-lib-name 而非 data-track-name，避免干扰 A14 对许可清单的 30 条扫描。
   * 结构签名不变时只原地更新「正在播放」高亮，不重建 DOM，保住键盘焦点。
   */
  function renderLibraryPanel() {
    var panel = el['library-panel'];
    if (!panel) { return; }
    var list = sources.getUiTrackList();
    var visible = list.filter(function (t) {
      return (libFilter.scene === 'all' || t.scene === libFilter.scene) &&
        (libFilter.kind === 'all' || t.kind === libFilter.kind);
    });
    var signature = libFilter.scene + '|' + libFilter.kind + '|' + list.length;
    if (signature !== lastLibSignature || !panel.firstChild) {
      var html = '<h3>声音库 · 挑一首</h3>' +
        '<p class="lib-hint">共 ' + list.length + ' 首已验证曲目。点选即作为主音源播放，' +
        '不改变当前场景的定时器、亮度与呼吸设置。</p>';
      html += '<div class="lib-filters" role="group" aria-label="按场景筛选">' +
        '<span class="lib-filter-label">场景</span>';
      LIB_SCENES.forEach(function (key) {
        html += '<button type="button" class="lib-chip" data-lib-scene="' + key + '"' +
          ' aria-pressed="' + (libFilter.scene === key ? 'true' : 'false') + '">' +
          esc(LIB_SCENE_LABELS[key]) + '</button>';
      });
      html += '</div><div class="lib-filters" role="group" aria-label="按类型筛选">' +
        '<span class="lib-filter-label">类型</span>';
      LIB_KINDS.forEach(function (key) {
        html += '<button type="button" class="lib-chip" data-lib-kind="' + key + '"' +
          ' aria-pressed="' + (libFilter.kind === key ? 'true' : 'false') + '">' +
          esc(LIB_KIND_LABELS[key]) + '</button>';
      });
      html += '</div><p class="lib-count" aria-live="polite">显示 ' + visible.length + ' 首</p>';
      html += '<ul class="lib-list">';
      visible.forEach(function (t) {
        html += '<li><button type="button" class="lib-track" data-lib-track="' + esc(t.id) + '"' +
          ' data-lib-name="' + esc(t.display) + '" aria-pressed="false">' +
          '<span class="lib-track-name">' + esc(t.display) + '</span>' +
          '<span class="lib-track-meta">' + esc(LIB_KIND_LABELS[t.kind] || '') +
          ' · ' + esc(LIB_SCENE_LABELS[t.scene] || '') + '</span></button></li>';
      });
      html += '</ul>';
      if (!visible.length) {
        html += '<p class="lib-hint">这个组合下暂无曲目，换个筛选条件看看。</p>';
      }
      panel.innerHTML = html;
      lastLibSignature = signature;
    }
    /* 高亮原地更新：不重建 DOM，键盘焦点与展开状态保持 */
    var st = store.getState();
    var currentId = (st.currentSource && st.currentSource.trackId) ||
      (st.tracks.length && st.tracks[0] ? st.tracks[0].trackId : null);
    var buttons = panel.querySelectorAll('[data-lib-track]');
    for (var i = 0; i < buttons.length; i += 1) {
      var active = buttons[i].getAttribute('data-lib-track') === currentId;
      buttons[i].setAttribute('aria-pressed', active ? 'true' : 'false');
      if (active) { buttons[i].classList.add('is-current'); }
      else { buttons[i].classList.remove('is-current'); }
    }
    var count = panel.querySelector('.lib-count');
    if (count) { count.textContent = '显示 ' + visible.length + ' 首'; }
  }

  /** 供契约只读：当前声音库筛选与可见曲目（不含任何源数据字段）。 */
  function getLibrarySnapshot() {
    var list = sources.getUiTrackList();
    var visible = list.filter(function (t) {
      return (libFilter.scene === 'all' || t.scene === libFilter.scene) &&
        (libFilter.kind === 'all' || t.kind === libFilter.kind);
    }).map(function (t) {
      return { id: t.id, display: t.display, scene: t.scene, kind: t.kind };
    });
    return {
      filter: { scene: libFilter.scene, kind: libFilter.kind },
      visibleCount: visible.length,
      total: list.length,
      tracks: visible
    };
  }

  /** 设置声音库筛选（供契约驱动，等价于点击筛选按钮）。 */
  function setLibraryFilter(scene, kind) {
    if (LIB_SCENES.indexOf(scene) >= 0) { libFilter.scene = scene; }
    if (LIB_KINDS.indexOf(kind) >= 0) { libFilter.kind = kind; }
    lastLibSignature = '';
    renderLibraryPanel();
  }

  /** 混音卡片：仅当结构签名变化才重建 DOM，避免拖动滑块时被重绘打断。 */
  function renderMixCards(state) {
    if (!el['mix-cards']) { return; }
    /* 签名只含结构字段，不含 volume：音量变化走「原地更新」分支 */
    var signature = state.tracks.map(function (t) {
      return t.id + ':' + t.kind + ':' + t.display;
    }).join('|');
    if (signature === lastMixSignature) {
      var inputs = el['mix-cards'].querySelectorAll('input[data-slot]');
      state.tracks.forEach(function (slot) {
        var pct = Math.round(slot.volume * 100);
        for (var j = 0; j < inputs.length; j += 1) {
          if (inputs[j].getAttribute('data-slot') !== slot.id) { continue; }
          if (document.activeElement !== inputs[j]) { inputs[j].value = String(pct); }
          inputs[j].setAttribute('aria-valuenow', String(pct));
          inputs[j].setAttribute('aria-valuetext', pct + '%');
          var valueNode = inputs[j].parentNode.querySelector('.volume-value');
          if (valueNode) { valueNode.textContent = pct + '%'; }
          break;
        }
      });
      if (el['mix-count']) { el['mix-count'].textContent = '(' + state.tracks.length + '/' + C.MAX_TRACKS + ')'; }
      if (el['mix-empty']) { el['mix-empty'].hidden = state.tracks.length > 0; }
      return;
    }
    lastMixSignature = signature;
    el['mix-cards'].innerHTML = '';
    state.tracks.forEach(function (slot) {
      var isMain = slot.id === 'main';
      var card = document.createElement('div');
      card.className = 'mix-card';
      var pct = Math.round(slot.volume * 100);
      var head = '<div class="mix-card-head"><span class="mix-card-name">' +
        esc(slot.display) + (isMain ? '（主音源）' : '') + '</span>' +
        '<span class="mix-card-wave" aria-hidden="true">' + (slot.volume > 0 ? '▁▃▅▃' : '▁▁▁▁') + '</span></div>';
      var row = '<div class="mix-card-row">' +
        '<input type="range" min="0" max="100" step="1" value="' + pct + '" role="slider" ' +
        'aria-label="' + esc(slot.display) + '音量" aria-valuemin="0" aria-valuemax="100" ' +
        'aria-valuenow="' + pct + '" aria-valuetext="' + pct + '%" data-slot="' + esc(slot.id) + '">' +
        '<span class="volume-value">' + pct + '%</span>' +
        (isMain ? '' : '<button type="button" class="remove-btn" data-remove="' + esc(slot.id) +
          '" aria-label="移除' + esc(slot.display) + '">✕</button>') +
        '</div>';
      card.innerHTML = head + row;
      el['mix-cards'].appendChild(card);
    });
    if (el['mix-count']) { el['mix-count'].textContent = '(' + state.tracks.length + '/' + C.MAX_TRACKS + ')'; }
    if (el['mix-empty']) { el['mix-empty'].hidden = state.tracks.length > 0; }
  }

  /** 格式化剩余时间为 mm:ss。 */
  function formatRemaining(ms) {
    var total = Math.max(0, Math.round(ms / 1000));
    var m = Math.floor(total / 60);
    var s = total % 60;
    return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }

  /** 呼吸圆环节拍（P1-01）；reduced-motion 下改静态文字。 */
  function breathTick() {
    var state = store.getState();
    var show = state.scene === 'meditation' && state.breath !== 'off';
    if (el['breath-ring']) { el['breath-ring'].hidden = !show; }
    if (el['breath-phase']) { el['breath-phase'].hidden = !show; }
    if (el['breath-controls']) { el['breath-controls'].hidden = state.scene !== 'meditation'; }
    if (el['visual-slogan']) { el['visual-slogan'].hidden = show; }
    if (!show) { return; }
    if (state.reducedMotion) {
      if (el['breath-phase']) { el['breath-phase'].textContent = '跟随节奏，慢慢呼吸'; }
      return;
    }
    var pattern = state.breath === '4-7-8'
      ? [[4, '吸气'], [7, '屏息'], [8, '呼气']]
      : [[4, '吸气'], [4, '呼气']];
    var total = state.breath === '4-7-8' ? 19 : 8;
    var t = ((Date.now() - breathStart) / 1000) % total;
    var acc = 0;
    var phaseText = '吸气';
    var scale = 0.72;
    for (var i = 0; i < pattern.length; i += 1) {
      var dur = pattern[i][0];
      if (t < acc + dur) {
        var k = (t - acc) / dur;
        phaseText = pattern[i][1];
        if (phaseText === '吸气') { scale = 0.72 + 0.28 * k; }
        else if (phaseText === '呼气') { scale = 1.0 - 0.28 * k; }
        else { scale = 1.0; }
        break;
      }
      acc += dur;
    }
    if (el['breath-phase']) { el['breath-phase'].textContent = phaseText; }
    if (el.ringCircle) { el.ringCircle.style.transform = 'scale(' + scale.toFixed(3) + ')'; }
  }

  /**
   * 全量渲染（由 store 的 sw:state 事件驱动；渲染函数内不做任何音频操作）。
   * @param {Object} state
   */
  function render(state) {
    var i;
    document.documentElement.setAttribute('data-brightness', state.brightness);
    if (el['brightness-label']) { el['brightness-label'].textContent = BRIGHTNESS_LABELS[state.brightness] || '暗'; }
    if (el['btn-brightness']) {
      el['btn-brightness'].setAttribute('aria-label', '切换亮度，当前：' + (BRIGHTNESS_LABELS[state.brightness] || '暗'));
    }

    /* 场景 Tab 与文案 */
    for (i = 0; i < el.tabs.length; i += 1) {
      var tab = el.tabs[i];
      var selected = tab.getAttribute('data-scene') === state.scene;
      tab.setAttribute('aria-selected', selected ? 'true' : 'false');
      tab.setAttribute('tabindex', selected ? '0' : '-1');
    }
    if (el['scene-panel']) { el['scene-panel'].setAttribute('aria-labelledby', 'tab-' + state.scene); }
    var preset = C.SCENES[state.scene] || C.SCENES.focus;
    if (el['scene-caption']) { el['scene-caption'].textContent = preset.caption; }
    if (el['visual-caption']) { el['visual-caption'].textContent = preset.label + ' · ' + preset.caption; }

    /* 徽标四态 */
    if (el.badge) { el.badge.setAttribute('data-state', state.badge); }
    if (el['badge-text']) { el['badge-text'].textContent = state.badgeText; }

    /* 播放按钮 */
    if (el['btn-play']) {
      el['btn-play'].setAttribute('aria-pressed', state.playing ? 'true' : 'false');
      el['btn-play'].setAttribute('aria-label', state.playing ? '暂停' : '播放');
    }
    if (el['play-icon']) { el['play-icon'].textContent = state.playing ? '⏸' : '▶'; }
    var main = state.tracks.length ? state.tracks[0] : null;
    if (el['now-title']) { el['now-title'].textContent = main ? main.display : '本地合成声'; }

    /* 主音量 */
    var pct = Math.round(state.masterVolume * 100);
    if (el['master-volume'] && document.activeElement !== el['master-volume']) {
      el['master-volume'].value = String(pct);
    }
    if (el['master-volume']) {
      el['master-volume'].setAttribute('aria-valuenow', String(pct));
      el['master-volume'].setAttribute('aria-valuetext', pct + '%');
    }
    if (el['master-volume-value']) { el['master-volume-value'].textContent = pct + '%'; }

    renderMixCards(state);

    /* 定时器三态 */
    var tState = state.timer || {};
    for (i = 0; i < el.presets.length; i += 1) {
      var p = el.presets[i];
      var minutesAttr = p.getAttribute('data-minutes');
      var fadeAttr = p.getAttribute('data-fade');
      if (minutesAttr !== null) {
        p.setAttribute('aria-pressed', (tState.active && Number(minutesAttr) === tState.minutes) ? 'true' : 'false');
      } else if (fadeAttr !== null) {
        p.setAttribute('aria-pressed', (Number(fadeAttr) === (tState.active ? tState.fadeSeconds : state.timerPresetFade)) ? 'true' : 'false');
      }
    }
    if (el['timer-remaining']) {
      if (!tState.active && tState.phase === 'ended') {
        el['timer-remaining'].textContent = '定时已结束，配置已保留';
      } else if (tState.active) {
        el['timer-remaining'].textContent = (tState.phase === 'fading' ? '渐弱中 · 剩余 ' : '剩余 ') + formatRemaining(tState.remainingMs);
      } else {
        el['timer-remaining'].textContent = '未设置';
      }
    }

    /* 呼吸圆环节奏切换时重置节拍起点 */
    var breathKey = state.scene + ':' + state.breath + ':' + state.reducedMotion;
    if (breathKey !== lastBreathKey) { lastBreathKey = breathKey; breathStart = Date.now(); }
    if (el['breath-controls']) {
      var buttons = el['breath-controls'].querySelectorAll('button');
      for (i = 0; i < buttons.length; i += 1) {
        buttons[i].setAttribute('aria-pressed', buttons[i].getAttribute('data-breath') === state.breath ? 'true' : 'false');
      }
    }
    breathTick();

    if (el['btn-drift']) {
      el['btn-drift'].setAttribute('aria-pressed', state.autoDrift ? 'true' : 'false');
      el['btn-drift'].textContent = '自动漂移：' + (state.autoDrift ? '开' : '关');
    }

    /* 页脚状态摘要 */
    if (el['lib-status']) {
      var updated = state.manifest.updatedAt ? state.manifest.updatedAt.slice(0, 10) : '内置快照';
      el['lib-status'].textContent = '● ' + state.badgeText + ' · 已验证 ' + state.manifest.count +
        ' 首 · 上次更新 ' + updated;
    }
    renderInfoPanel(state);
    renderDetailsPanel();
    renderLibraryPanel();
  }

  /** 每秒更新播放进度（避免高频全量渲染造成长任务）。 */
  function updateProgress() {
    if (!player || !el['progress-fill'] || !el['progress-time']) { return; }
    var p = player.getProgress();
    var duration = p.duration || 0;
    var current = p.currentTime || 0;
    var percent = duration > 0 ? Math.min(100, (current / duration) * 100) : 0;
    el['progress-fill'].style.width = percent.toFixed(1) + '%';
    el['progress-time'].textContent = formatRemaining(current * 1000) + ' / ' + formatRemaining(duration * 1000);
  }

  /** 渲染声景选择层（10 种本地合成声景，零网络）。 */
  function renderVoicePicker() {
    if (!el['voice-picker']) { return; }
    el['voice-picker'].innerHTML = '';
    C.SYNTH_VOICES.forEach(function (voice) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.setAttribute('data-voice', voice);
      btn.textContent = C.VOICE_LABELS[voice] || voice;
      el['voice-picker'].appendChild(btn);
    });
  }

  /** 确保播放已启动后再执行用户意图（F1：选场景/加声景/换一曲都会出声）。 */
  function ensureStarted(intent) {
    if (store.getState().playState === 'idle') {
      return player.play().then(function () { intent(); });
    }
    intent();
    return Promise.resolve();
  }

  /** 绑定全部 DOM 事件。 */
  function bindEvents() {
    el['btn-play'].addEventListener('click', function () { player.toggle(); });
    el['btn-next'].addEventListener('click', function () {
      ensureStarted(function () { player.nextTrack(); toast('已为你换一曲'); });
    });
    el['master-volume'].addEventListener('input', function (ev) {
      player.setMasterVolume(Number(ev.target.value) / 100);
    });
    el['btn-brightness'].addEventListener('click', cycleBrightness);
    el['btn-refresh'].addEventListener('click', onRefresh);
    el['btn-info'].addEventListener('click', function () { togglePanel(el['btn-info'], el['info-panel']); });
    el['btn-details'].addEventListener('click', function () { togglePanel(el['btn-details'], el['details-panel']); });
    el['btn-library'].addEventListener('click', function () {
      togglePanel(el['btn-library'], el['library-panel']);
    });

    /* 声音库：事件委托（筛选 + 点选曲目），避免逐条绑定 30 个按钮 */
    el['library-panel'].addEventListener('click', function (ev) {
      var closest = function (sel) {
        return ev.target.closest ? ev.target.closest(sel) : null;
      };
      var sceneBtn = closest('[data-lib-scene]');
      if (sceneBtn) {
        setLibraryFilter(sceneBtn.getAttribute('data-lib-scene'), null);
        return;
      }
      var kindBtn = closest('[data-lib-kind]');
      if (kindBtn) {
        setLibraryFilter(null, kindBtn.getAttribute('data-lib-kind'));
        return;
      }
      var trackBtn = closest('[data-lib-track]');
      if (trackBtn) {
        var id = trackBtn.getAttribute('data-lib-track');
        var name = trackBtn.getAttribute('data-lib-name');
        ensureStarted(function () {
          if (player.selectTrack(id)) { toast('已切换到「' + name + '」'); }
        });
      }
    });

    /* 场景 Tab：点击 + 左右方向键（tablist 键盘模式） */
    el['scene-tabs'].addEventListener('click', function (ev) {
      var tab = ev.target.closest ? ev.target.closest('.tab') : null;
      if (!tab) { return; }
      var scene = tab.getAttribute('data-scene');
      player.applyScene(scene);
    });
    el['scene-tabs'].addEventListener('keydown', function (ev) {
      if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') { return; }
      var idx = C.SCENE_IDS.indexOf(store.getState().scene);
      var next = (idx + (ev.key === 'ArrowRight' ? 1 : -1) + C.SCENE_IDS.length) % C.SCENE_IDS.length;
      ev.preventDefault();
      var target = document.getElementById('tab-' + C.SCENE_IDS[next]);
      if (target) { target.focus(); }
      player.applyScene(C.SCENE_IDS[next]);
    });

    /* 混音卡片：事件委托（音量 / 移除） */
    el['mix-cards'].addEventListener('input', function (ev) {
      var t = ev.target;
      if (t && t.getAttribute && t.getAttribute('data-slot')) {
        player.setTrackVolume(t.getAttribute('data-slot'), Number(t.value) / 100);
      }
    });
    el['mix-cards'].addEventListener('click', function (ev) {
      var btn = ev.target.closest ? ev.target.closest('[data-remove]') : null;
      if (btn) { player.removeTrack(btn.getAttribute('data-remove')); }
    });

    /* 添加声景 */
    el['btn-add'].addEventListener('click', function () {
      var picker = el['voice-picker'];
      picker.hidden = !picker.hidden;
      if (!picker.hidden) { renderVoicePicker(); }
    });
    el['voice-picker'].addEventListener('click', function (ev) {
      var btn = ev.target.closest ? ev.target.closest('[data-voice]') : null;
      if (!btn) { return; }
      var voice = btn.getAttribute('data-voice');
      ensureStarted(function () {
        var result = player.addTrack(voice);
        if (!result.ok && result.reason === 'limit') {
          toast('已达 3 条声景上限，先移除一条再添加');
        } else if (result.ok) {
          toast('已添加「' + (C.VOICE_LABELS[voice] || voice) + '」');
        }
      });
      el['voice-picker'].hidden = true;
    });

    /* 呼吸节奏切换 */
    el['breath-controls'].addEventListener('click', function (ev) {
      var btn = ev.target.closest ? ev.target.closest('[data-breath]') : null;
      if (!btn) { return; }
      var mode = btn.getAttribute('data-breath');
      store.patch({ breath: mode });
      store.savePrefs();
    });

    /* 定时器：时长 / 自定义 / 渐弱 / 取消 */
    document.querySelectorAll('.preset[data-minutes]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var minutes = Number(btn.getAttribute('data-minutes'));
        timer.start(minutes, selectedFade);
        toast('已设置 ' + minutes + ' 分钟定时');
      });
    });
    document.querySelectorAll('.preset[data-fade]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        selectedFade = Number(btn.getAttribute('data-fade'));
        if (timer.getState().active) { timer.setFadeSeconds(selectedFade); }
        else { store.patch({ timerPresetFade: selectedFade }); }
        toast(selectedFade === 0 ? '渐弱已关闭' : '渐弱设为 ' + selectedFade + ' 秒');
      });
    });
    el['btn-custom-timer'].addEventListener('click', function () {
      var minutes = Math.max(1, Math.min(720, Number(el['custom-minutes'].value) || 30));
      timer.start(minutes, selectedFade);
      toast('已设置 ' + minutes + ' 分钟定时');
    });
    el['btn-cancel-timer'].addEventListener('click', function () {
      timer.cancel();
      toast('已取消定时，音量已恢复');
    });

    /* 自动漂移 / 清除本地设置 */
    el['btn-drift'].addEventListener('click', function () {
      var next = !store.getState().autoDrift;
      player.setAutoDrift(next);
      toast(next ? '自动漂移已开启，音量会缓慢起伏' : '自动漂移已关闭');
    });
    el['btn-clear'].addEventListener('click', function () {
      store.clearAll();
      sources.resetHealth();
      toast('本地设置已清除，已恢复默认');
      render(store.getState());
    });

    /* P1-06 快捷键 */
    document.addEventListener('keydown', function (ev) {
      var t = ev.target;
      var tag = t && t.tagName ? t.tagName.toUpperCase() : '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) { return; }
      if (ev.altKey || ev.ctrlKey || ev.metaKey) { return; }
      if (ev.key === ' ') {
        if (tag === 'BUTTON' || tag === 'A' || tag === 'SUMMARY') { return; } // 交给控件默认行为
        ev.preventDefault();
        player.toggle();
        return;
      }
      if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') {
        if (tag === 'BUTTON') { return; }
        ev.preventDefault();
        var delta = ev.key === 'ArrowRight' ? 0.05 : -0.05;
        player.setMasterVolume(Math.max(0, Math.min(1, store.getState().masterVolume + delta)));
        return;
      }
      if (/^[1-4]$/.test(ev.key)) {
        ev.preventDefault();
        player.applyScene(C.SCENE_IDS[Number(ev.key) - 1]);
      }
    });

    /* 订阅 store 与领域事件 */
    store.on(E.STATE, function () { render(store.getState()); });
    store.on(E.TOAST, function (payload) { if (payload && payload.message) { toast(payload.message); } });
    store.on(E.SOURCE_DEGRADED, function (payload) {
      toast(payload && payload.message ? payload.message : '已为你切换到备用声源');
    });
    store.on(E.LIBRARY_FAILED, function () { /* UI 三态由 onRefresh 统一处理 */ });
    store.on(E.TIMER_ENDED, function () { toast('定时结束，声音已轻轻停下'); });
    store.on(E.TRACK_REMOVED, function () { /* 卡片重绘由 sw:state 完成 */ });

    /* 系统减少动效偏好变化 */
    if (window.matchMedia) {
      var mq = window.matchMedia('(prefers-reduced-motion: reduce)');
      var onChange = function (e) { store.patch({ reducedMotion: !!e.matches }); };
      if (mq.addEventListener) { mq.addEventListener('change', onChange); }
      else if (mq.addListener) { mq.addListener(onChange); }
    }
  }

  /** 初始化界面层。 */
  function init() {
    cacheDom();
    renderVoicePicker();
    bindEvents();
    breathStart = Date.now();
    render(store.getState());
    breathTimer = window.setInterval(breathTick, 120);
    progressTimer = window.setInterval(updateProgress, 1000);
  }

  /**
   * QA 契约：UI 快照（断言 P0-14 不弹窗 / 不闪烁 / aria-live=polite）。
   * @returns {Object}
   */
  function getUiSnapshot() {
    var toastEl = el.toast;
    return {
      badgeText: el['badge-text'] ? el['badge-text'].textContent.trim() : '',
      toastText: SW.RUNTIME.toastText || (toastEl && !toastEl.hidden ? toastEl.textContent.trim() : null),
      hasDialog: !!document.querySelector('dialog[open], [role="dialog"], [role="alertdialog"]'),
      hasModal: !!document.querySelector('[aria-modal="true"], .modal.is-open'),
      ariaLive: toastEl ? toastEl.getAttribute('aria-live') : null,
      flashingElements: document.querySelectorAll('[data-flashing="true"], .flash').length
    };
  }

  SW.ui = {
    init: init,
    render: render,
    toast: toast,
    /* 契约所需的扩展 */
    getUiSnapshot: getUiSnapshot,
    setBrightness: setBrightness,
    getLibrarySnapshot: getLibrarySnapshot,
    setLibraryFilter: setLibraryFilter
  };
})();

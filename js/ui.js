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
  var lastPresetSignature = '';
  var onlyFavorites = false;      // P0-2「只看收藏」开关（独立按钮，不并入筛选 chip 组）
  var presetInputHold = false;    // 保存预设后需要强制重建时，临时关闭「输入聚焦保护」
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
      'btn-presets', 'preset-panel',
      'btn-drift', 'btn-clear', 'btn-share', 'share-panel', 'toast'
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
   * 声音库：可浏览 / 可筛选 / 可点选 / 可收藏的曲目清单（P1-09 + P0-2）。
   * 数据一律来自 sources.getUiTrackList() 的 UiTrack 白名单投影，展示层拿不到
   * url / 源标题 / bytes / health 等源数据字段（AD-21）。
   * 用 data-lib-name / data-fav-id 而非 data-track-name，避免干扰 A14 对许可清单的 30 条扫描。
   * 收藏白名单过滤在本层完成：store 只存 id，清单里已不存在的收藏静默不显示。
   * 结构签名不变时只原地更新「正在播放」高亮，不重建 DOM，保住键盘焦点。
   */
  function renderLibraryPanel() {
    var panel = el['library-panel'];
    if (!panel) { return; }
    var list = sources.getUiTrackList();
    var favIds = store.getFavorites();
    var favMap = {};
    var i;
    for (i = 0; i < favIds.length; i += 1) { favMap[favIds[i]] = true; }
    var visible = list.filter(function (t) {
      var hitFilter = (libFilter.scene === 'all' || t.scene === libFilter.scene) &&
        (libFilter.kind === 'all' || t.kind === libFilter.kind);
      if (!hitFilter) { return false; }
      if (onlyFavorites && !favMap[t.id]) { return false; }
      return true;
    });
    var signature = libFilter.scene + '|' + libFilter.kind + '|' +
      (onlyFavorites ? '1' : '0') + '|' + favIds.join(',') + '|' + list.length;
    if (signature !== lastLibSignature || !panel.firstChild) {
      var html = '<h3>声音库 · 挑一首</h3>' +
        '<p class="lib-hint">共 ' + list.length + ' 首已验证曲目。点选即作为主音源播放，' +
        '不改变当前场景的定时器、亮度与呼吸设置。点右侧 ☆ 可收藏常听的曲目。</p>';
      /* 独立开关：不属于 .lib-filters 两个 chip 组，避免打乱既有的场景/类型计数断言 */
      html += '<p class="lib-flag-row"><button type="button" id="btn-fav-only"' +
        ' class="lib-chip lib-chip-standalone" aria-pressed="' +
        (onlyFavorites ? 'true' : 'false') + '">只看收藏</button></p>';
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
        var fav = !!favMap[t.id];
        /* 星标是 .lib-track 的兄弟节点而非子节点：交互元素不允许嵌套 */
        html += '<li class="lib-row">' +
          '<button type="button" class="lib-track" data-lib-track="' + esc(t.id) + '"' +
          ' data-lib-name="' + esc(t.display) + '" aria-pressed="false">' +
          '<span class="lib-track-name">' + esc(t.display) + '</span>' +
          '<span class="lib-track-meta">' + esc(LIB_KIND_LABELS[t.kind] || '') +
          ' · ' + esc(LIB_SCENE_LABELS[t.scene] || '') + '</span></button>' +
          '<button type="button" class="lib-fav" data-fav-id="' + esc(t.id) + '"' +
          ' aria-pressed="' + (fav ? 'true' : 'false') + '"' +
          ' aria-label="收藏 ' + esc(t.display) + '">' + (fav ? '★' : '☆') + '</button></li>';
      });
      html += '</ul>';
      if (!visible.length) {
        html += '<p class="lib-hint">' + (onlyFavorites
          ? '还没有收藏的曲目。点曲目右侧的 ☆ 就能收藏，刷新后依然保留。'
          : '这个组合下暂无曲目，换个筛选条件看看。') + '</p>';
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

  /** 供契约只读：收藏快照（只列仍在曲库白名单内的 id，不含任何内部引用）。 */
  function getFavoritesSnapshot() {
    var list = sources.getUiTrackList();
    var present = {};
    var ids = [];
    var fav = store.getFavorites();
    var i;
    for (i = 0; i < list.length; i += 1) { present[list[i].id] = true; }
    for (i = 0; i < fav.length; i += 1) {
      if (present[fav[i]]) { ids.push(fav[i]); }
    }
    return { count: ids.length, ids: ids, onlyFavorites: onlyFavorites };
  }

  /** 供契约只读：预设快照（只给数量与名称，不给内部对象引用）。 */
  function getPresetsSnapshot() {
    var items = store.getPresets();
    var names = [];
    for (var i = 0; i < items.length; i += 1) { names.push(items[i].name); }
    return { count: items.length, names: names };
  }

  /**
   * 预设面板：名称 + 「应用 / 删除」+ 内联保存行（ST-23 禁止 prompt / alert / dialog）。
   * 结构签名不变时不重建 DOM；输入框聚焦期间绝不重建，避免打断输入与丢焦点。
   */
  function renderPresetPanel() {
    var panel = el['preset-panel'];
    if (!panel) { return; }
    var active = document.activeElement;
    if (!presetInputHold && active && active.id === 'preset-name-input') { return; }
    var items = store.getPresets();
    var signature = items.map(function (p) {
      return p.name + '|' + p.scene + '|' + p.masterVolume + '|' + p.tracks.length;
    }).join('~');
    if (signature === lastPresetSignature && panel.firstChild) { return; }
    lastPresetSignature = signature;
    var html = '<h3>我的预设</h3>' +
      '<p class="lib-hint">保存当前场景、主音量与混音轨，下次一键还原。</p>';
    if (items.length) {
      html += '<ul class="preset-list">';
      items.forEach(function (p, index) {
        html += '<li class="preset-item">' +
          '<span class="preset-name">' + esc(p.name) + '</span>' +
          '<button type="button" class="preset-apply" data-preset-idx="' + index + '"' +
          ' aria-label="应用预设 ' + esc(p.name) + '">应用</button>' +
          '<button type="button" class="preset-delete" data-preset-idx="' + index + '"' +
          ' aria-label="删除预设 ' + esc(p.name) + '">删除</button></li>';
      });
      html += '</ul>';
    } else {
      html += '<p class="lib-hint">还没有预设。调好混音后，给它起个名字保存下来。</p>';
    }
    html += '<div class="preset-save-row">' +
      '<input id="preset-name-input" class="preset-input" type="text" maxlength="' +
      C.MAX_PRESET_NAME + '" placeholder="给这个混音起个名字" aria-label="预设名称">' +
      '<button id="btn-preset-save" type="button" class="ghost-btn">保存当前混音</button>' +
      '</div>';
    panel.innerHTML = html;
  }

  /** 保存当前混音（供按钮与输入框回车共用）。 */
  function saveCurrentMix() {
    var panel = el['preset-panel'];
    if (!panel) { return; }
    var input = panel.querySelector('#preset-name-input');
    var raw = input ? input.value : '';
    var mix = player.getMixSpec();
    var result = store.savePreset({
      name: raw, scene: mix.scene,
      masterVolume: mix.masterVolume, tracks: mix.tracks
    });
    if (!result.ok) {
      if (result.reason === 'limit') { toast('预设已满（' + C.MAX_PRESETS + '）'); }
      else if (result.reason === 'name') { toast('请先给预设起个名字'); }
      else if (result.reason === 'tracks') { toast('还没有正在播放的混音，先点播放再保存'); }
      else { toast('当前混音暂时无法保存'); }
      return;
    }
    var saved = String(raw).replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, C.MAX_PRESET_NAME);
    if (input) { input.value = ''; }
    lastPresetSignature = '';
    /* 输入框里回车保存时焦点仍在输入框内：强制重建后把焦点还给新输入框，键盘流程不断 */
    presetInputHold = true;
    renderPresetPanel();
    presetInputHold = false;
    var next = panel.querySelector('#preset-name-input');
    if (next && document.activeElement === document.body) { next.focus(); }
    toast('已保存预设「' + saved + '」');
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
    renderPresetPanel();
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

  /* —— P0-3 分享链接：编码 → 写地址栏 → 复制（三级回退）———————————————
     硬边界：整条流程只读 player.getMixSpec()，绝不调 play()/start()，
     也不创建 AudioContext（#btn-share 已在 main.js 的首次手势钩子里排除）。
     复制三级：clipboard.writeText → execCommand('copy') → 展开 #share-panel，
     把只读输入框留在页面上并选中（用户按 Ctrl/⌘+C 即可）。
     面板只承载「手动复制兜底」，因此 aria-expanded 恒等于面板真实显隐，绝不说谎。 */

  /** 分享链接的绝对地址：http(s) 用 origin + pathname；file:// 用 href 去掉 hash 段。 */
  function shareUrlOf(hash) {
    try {
      var loc = window.location;
      if (loc.protocol === 'file:') { return String(loc.href).split('#')[0] + hash; }
      return String(loc.origin) + String(loc.pathname) + hash;
    } catch (err) {
      return hash;
    }
  }

  /** 生成当前配置的分享 hash（编码逻辑只在 main.js 一处，避免两端格式漂移）。 */
  function currentShareHash() {
    try {
      if (SW.main && typeof SW.main.getShareHash === 'function') {
        return SW.main.getShareHash(player.getMixSpec());
      }
    } catch (err) { /* 静默：编码失败按复制失败处理 */ }
    return '';
  }

  /** 写地址栏：replaceState 不新增历史记录（不污染后退按钮）；受限环境静默跳过。 */
  function writeShareHash(hash) {
    try {
      if (!window.history || typeof window.history.replaceState !== 'function') { return false; }
      var loc = window.location;
      window.history.replaceState(null, '', String(loc.pathname) + String(loc.search) + hash);
      return true;
    } catch (err) {
      return false;
    }
  }

  /** 收起手动复制面板并同步 aria-expanded（面板不存在时静默）。 */
  function closeSharePanel() {
    if (!el['share-panel']) { return; }
    el['share-panel'].hidden = true;
    if (el['btn-share']) { el['btn-share'].setAttribute('aria-expanded', 'false'); }
  }

  /**
   * 展开手动复制面板并渲染链接：只用 createElement / textContent（绝不拼 innerHTML），
   * 只读输入框写入 value 属性、选中并聚焦。返回输入框（面板缺失时返回 null）。
   * @param {string} url
   * @returns {HTMLInputElement|null}
   */
  function selectShareText(url) {
    var panel = el['share-panel'];
    if (!panel) { return null; }
    while (panel.firstChild) { panel.removeChild(panel.firstChild); }

    var hint = document.createElement('p');
    hint.className = 'share-hint';
    hint.textContent = '链接只包含场景、主音量与混音轨，不含任何个人信息。打开即还原配置，不会自动播放。';
    panel.appendChild(hint);

    var input = document.createElement('input');
    input.id = 'share-fallback-input';
    input.type = 'text';
    input.className = 'share-fallback';
    input.readOnly = true;
    input.value = url;
    input.setAttribute('aria-label', '分享链接，可手动复制');
    panel.appendChild(input);

    var close = document.createElement('button');
    close.id = 'btn-share-close';
    close.type = 'button';
    close.className = 'ghost-btn';
    close.textContent = '收起';
    panel.appendChild(close);

    panel.hidden = false;
    if (el['btn-share']) { el['btn-share'].setAttribute('aria-expanded', 'true'); }
    try {
      input.focus();
      if (typeof input.setSelectionRange === 'function') { input.setSelectionRange(0, url.length); }
      input.select();
    } catch (err) { /* 静默 */ }
    return input;
  }

  /**
   * 回退复制：临时只读输入框 + execCommand('copy')。
   * 成功也保留选中态——execCommand 的返回值在 file:// / 沙箱下不能当作「已写入剪贴板」的证据，
   * 保留选中让「按 Ctrl/⌘+C」这句提示永远可执行。
   * @returns {'exec'|'manual'}
   */
  function legacyCopyShare(url) {
    var input = selectShareText(url);
    if (!input) { return 'manual'; }
    if (typeof document.execCommand !== 'function') { return 'manual'; }
    var copied = false;
    try { copied = document.execCommand('copy'); } catch (err) { copied = false; }
    return copied ? 'exec' : 'manual';
  }

  /**
   * 写剪贴板（三级回退），返回实际使用的方式。
   * @param {string} url
   * @returns {Promise<'clipboard'|'exec'|'manual'>}
   */
  function writeShareClipboard(url) {
    var nav = window.navigator;
    var clipboard = (nav && nav.clipboard && typeof nav.clipboard.writeText === 'function')
      ? nav.clipboard : null;
    if (!clipboard) { return Promise.resolve(legacyCopyShare(url)); }
    return clipboard.writeText(url).then(function () {
      closeSharePanel();
      return 'clipboard';
    }, function () {
      /* 权限被拒 / 非安全上下文 / headless 沙箱：降级到 execCommand，绝不外抛 */
      return legacyCopyShare(url);
    });
  }

  /**
   * 分享当前配置（与点击 #btn-share 等价，供按钮与 QA 契约共用；绝不触发播放）。
   * @returns {Promise<{ok:boolean, hash:string, url:string, mode:string}>}
   */
  function copyShareLink() {
    var hash = currentShareHash();
    if (!hash) {
      toast('复制失败，请手动复制地址栏链接');
      return Promise.resolve({ ok: false, hash: '', url: '', mode: 'error' });
    }
    var url = shareUrlOf(hash);
    writeShareHash(hash);
    return writeShareClipboard(url).then(function (mode) {
      if (mode === 'clipboard') {
        toast('已复制分享链接，打开即还原当前配置');
        return { ok: true, hash: hash, url: url, mode: mode };
      }
      if (mode === 'exec') {
        toast('已选中链接，按 Ctrl/⌘+C 复制');
        return { ok: true, hash: hash, url: url, mode: mode };
      }
      toast('复制失败，请手动复制地址栏链接');
      return { ok: false, hash: hash, url: url, mode: mode };
    });
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
    if (el['btn-presets']) {
      el['btn-presets'].addEventListener('click', function () {
        togglePanel(el['btn-presets'], el['preset-panel']);
      });
    }

    /* 我的预设：事件委托（应用 / 删除 / 保存 / 回车保存） */
    if (el['preset-panel']) {
      el['preset-panel'].addEventListener('click', function (ev) {
        var closest = function (sel) {
          return ev.target.closest ? ev.target.closest(sel) : null;
        };
        var applyBtn = closest('.preset-apply');
        if (applyBtn) {
          var items = store.getPresets();
          var spec = items[Number(applyBtn.getAttribute('data-preset-idx'))];
          if (!spec) { return; }
          var applied = player.applyMix(spec);
          if (!applied.ok) { toast('这个预设暂时无法应用'); }
          else if (applied.pending) { toast('已载入预设，点击播放生效'); }
          else { toast('已应用「' + spec.name + '」'); }
          return;
        }
        var delBtn = closest('.preset-delete');
        if (delBtn) {
          var delIdx = Number(delBtn.getAttribute('data-preset-idx'));
          var list0 = store.getPresets();
          var delName = list0[delIdx] ? list0[delIdx].name : '';
          var deleted = store.deletePreset(delIdx);
          lastPresetSignature = '';
          renderPresetPanel();
          if (deleted.ok) { toast('已删除预设「' + delName + '」'); }
          return;
        }
        if (closest('#btn-preset-save')) { saveCurrentMix(); }
      });
      el['preset-panel'].addEventListener('keydown', function (ev) {
        if (ev.key !== 'Enter') { return; }
        if (!ev.target || ev.target.id !== 'preset-name-input') { return; }
        ev.preventDefault();
        saveCurrentMix();
      });
    }

    /* 声音库：事件委托（筛选 + 点选曲目），避免逐条绑定 30 个按钮 */
    el['library-panel'].addEventListener('click', function (ev) {
      var closest = function (sel) {
        return ev.target.closest ? ev.target.closest(sel) : null;
      };
      /* 只看收藏：独立开关，不属于场景/类型 chip 组 */
      if (closest('#btn-fav-only')) {
        onlyFavorites = !onlyFavorites;
        lastLibSignature = '';
        renderLibraryPanel();
        toast(onlyFavorites ? '只看收藏' : '显示全部曲目');
        return;
      }
      /* 星标：收藏 / 取消收藏（与点选曲目互不干扰，星标不在 .lib-track 内） */
      var favBtn = closest('[data-fav-id]');
      if (favBtn) {
        var favId = favBtn.getAttribute('data-fav-id');
        var row = favBtn.parentNode;
        var rowTrack = row ? row.querySelector('[data-lib-track]') : null;
        var favName = rowTrack ? rowTrack.getAttribute('data-lib-name') : '';
        var favRes = store.toggleFavorite(favId);
        if (favRes.ok) {
          lastLibSignature = '';
          renderLibraryPanel();
          toast(favRes.favorite ? '已收藏「' + favName + '」' : '已取消收藏「' + favName + '」');
          /* 重建后把焦点还给同一颗星，键盘操作不丢位（逐项比对，不拼选择器） */
          var stars = el['library-panel'].querySelectorAll('[data-fav-id]');
          for (var si = 0; si < stars.length; si += 1) {
            if (stars[si].getAttribute('data-fav-id') === favId) { stars[si].focus(); break; }
          }
        } else if (favRes.reason === 'limit') {
          toast('收藏已达上限（' + C.MAX_FAVORITES + '）');
        }
        return;
      }
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
      /* P0-4b：展开态同步到触发按钮，读屏才拿得到「已展开/已收起」 */
      el['btn-add'].setAttribute('aria-expanded', picker.hidden ? 'false' : 'true');
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
      el['btn-add'].setAttribute('aria-expanded', 'false');
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
    if (el['btn-share']) {
      el['btn-share'].addEventListener('click', function () { copyShareLink(); });
    }
    /* 分享面板的「收起」：关面板并把焦点还给触发按钮（键盘流程不断） */
    if (el['share-panel']) {
      el['share-panel'].addEventListener('click', function (ev) {
        var closer = ev.target && ev.target.closest ? ev.target.closest('#btn-share-close') : null;
        if (!closer) { return; }
        closeSharePanel();
        if (el['btn-share']) { el['btn-share'].focus(); }
      });
    }
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

    /**
     * P0-4b 键盘收口：Escape 关掉「当前最上层那个展开的面板」并把焦点还给触发按钮。
     * - 只关一个：从最上层往下找第一个展开的，避免一次 Escape 关掉全部面板，
     *   也避免用户在输入框里按 Escape 时把整个界面收掉。
     * - 焦点归还对象就是 aria-controls 指向本面板的那个按钮，符合「从哪来回哪去」。
     * - 与 P1-06 快捷键独立监听：上面那个 keydown 对 INPUT/TEXTAREA 直接 return，
     *   Escape 属于「退出」语义，必须连输入框里也生效。
     */
    var PANEL_TRIGGERS = [
      ['share-panel', 'btn-share'],
      ['voice-picker', 'btn-add'],
      ['preset-panel', 'btn-presets'],
      ['library-panel', 'btn-library'],
      ['details-panel', 'btn-details'],
      ['info-panel', 'btn-info']
    ];
    function closeTopPanel() {
      var i;
      for (i = 0; i < PANEL_TRIGGERS.length; i += 1) {
        var panelId = PANEL_TRIGGERS[i][0];
        var panel = el[panelId];
        if (!panel || panel.hidden) { continue; }
        var trigger = el[PANEL_TRIGGERS[i][1]];
        if (panelId === 'share-panel') {
          closeSharePanel();
        } else {
          panel.hidden = true;
        }
        if (trigger) {
          trigger.setAttribute('aria-expanded', 'false');
          try { trigger.focus(); } catch (err) { /* 静默 */ }
        }
        return true;
      }
      return false;
    }
    document.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape' && ev.key !== 'Esc') { return; }
      if (ev.altKey || ev.ctrlKey || ev.metaKey) { return; }
      if (closeTopPanel()) { ev.preventDefault(); }
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
    setLibraryFilter: setLibraryFilter,
    /* P0-2 收藏与预设只读快照（白名单过滤后，不含内部引用） */
    getFavoritesSnapshot: getFavoritesSnapshot,
    getPresetsSnapshot: getPresetsSnapshot,
    /* P0-3 分享链接：与点击 #btn-share 完全等价（不触发播放） */
    copyShareLink: copyShareLink
  };
})();

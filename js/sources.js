/* ==========================================================================
 * 静澜 Stillwave · js/sources.js
 * 职责：音源目录五层分级（L0~L4）、多候选解析、健康度降权持久化、
 *       远端清单双 CDN + ETag + 超时 + 缓存 + 原子回退、动态发现与规则过滤、
 *       许可元数据查询、refresh() 编排。
 * 约束：不引用 player / ui；不 fetch 本地清单（只读 SW.BUNDLED_MANIFEST）；
 *       file:// 下静默跳过 L2/L3；所有异常内部吞掉，不 console.error。
 * 装载：第 4 位。
 * ========================================================================== */
;(function () {
  'use strict';

  var SW = (window.SW = window.SW || {});
  var C = SW.config;
  var E = C.EVENTS;
  var K = C.STORAGE_KEYS;
  var store = SW.store;

  var manifest = null;          // 当前生效清单（内存）
  var health = Object.create(null); // id -> HealthEntry
  var discovered = [];          // L3 候选（永不进播放序列）
  var refreshing = false;
  var remoteETag = null;

  /** 深拷贝普通对象（清单规模 30 条，单次 O(n)）。 */
  function clone(value) { return JSON.parse(JSON.stringify(value)); }

  /** 判断当前是否为 http(s) 环境（file:// 下静默跳过 L2/L3，AD-15）。 */
  function isHttp() {
    try { return /^https?:$/.test(window.location.protocol || ''); }
    catch (err) { return false; }
  }

  /** 校验清单 schema（原子回退：任何一项不通过都整体拒绝替换）。 */
  function validateManifest(m) {
    if (!m || typeof m !== 'object') { return false; }
    if (m.schema !== C.MANIFEST_SCHEMA) { return false; }
    if (!Array.isArray(m.tracks) || m.tracks.length === 0) { return false; }
    if (typeof m.version !== 'number') { return false; }
    for (var i = 0; i < m.tracks.length; i += 1) {
      var t = m.tracks[i];
      if (!t || typeof t.id !== 'string' || typeof t.url !== 'string' ||
          typeof t.display !== 'string' || !Array.isArray(t.candidates) ||
          typeof t.source !== 'string' || typeof t.license !== 'string' ||
          typeof t.attribution !== 'string' || typeof t.item !== 'string') {
        return false;
      }
      if (t.needsReview === true || t.verified === false) { return false; }
    }
    if (!Array.isArray(m.candidates) || !Array.isArray(m.quarantine)) { return false; }
    return true;
  }

  /** 从 sw.health.v1 载入健康度（localStorage 不可用时由 store 内部降级）。 */
  function loadHealth() {
    var saved = store.readStorage(K.health);
    health = Object.create(null);
    if (saved && typeof saved === 'object') {
      Object.keys(saved).forEach(function (id) {
        var h = saved[id];
        if (h && typeof h === 'object' && typeof h.score === 'number') {
          health[id] = normalizeHealth(h);
        }
      });
    }
  }

  /** 归一化健康度条目（§2.6.3）。 */
  function normalizeHealth(h) {
    return {
      score: Math.max(0, Math.min(100, typeof h.score === 'number' ? h.score : 100)),
      ok: typeof h.ok === 'number' ? h.ok : 0,
      fail: typeof h.fail === 'number' ? h.fail : 0,
      lastOkAt: h.lastOkAt || null,
      lastFailAt: h.lastFailAt || null,
      consecutiveFail: typeof h.consecutiveFail === 'number' ? h.consecutiveFail : 0,
      cooldownUntil: typeof h.cooldownUntil === 'number' ? h.cooldownUntil : null
    };
  }

  /** 持久化健康度。 */
  function persistHealth() {
    var plain = Object.create(null);
    Object.keys(health).forEach(function (id) { plain[id] = health[id]; });
    store.writeStorage(K.health, plain);
  }

  /** 取得（或初始化）某条目的健康度。 */
  function entryFor(id) {
    if (!health[id]) {
      health[id] = {
        score: 100, ok: 0, fail: 0, lastOkAt: null, lastFailAt: null,
        consecutiveFail: 0, cooldownUntil: null
      };
    }
    return health[id];
  }

  /** 目录初始化：载入内置快照（零 fetch）→ 应用 health → 尝试缓存清单。 */
  function init() {
    var bundled = SW.BUNDLED_MANIFEST;
    if (!bundled || !validateManifest(bundled)) {
      /* 极端兜底：构造最小可用清单，绝不空清单 */
      manifest = {
        schema: C.MANIFEST_SCHEMA, version: 1, updatedAt: '', verifiedAt: '',
        count: 0, scenes: { focus: 0, sleep: 0, empty: 0, meditation: 0 },
        tracks: [], candidates: [], quarantine: []
      };
    } else {
      manifest = clone(bundled);
    }
    loadHealth();
    applyCachedManifest();
    store.patch({
      manifest: {
        version: manifest.version,
        updatedAt: manifest.updatedAt || '',
        count: manifest.tracks.length,
        source: manifest.__source || 'bundled'
      }
    });
    store.pushLog({ type: 'library', action: 'init', version: manifest.version, count: manifest.tracks.length });
  }

  /** 缓存清单也是一层兜底：校验通过且 version 更高才整体替换。 */
  function applyCachedManifest() {
    var cached = store.readStorage(K.manifest);
    if (!cached || !cached.payload) { return; }
    if (!validateManifest(cached.payload)) { return; }
    if (cached.payload.version <= manifest.version) { return; }
    var payload = clone(cached.payload);
    payload.__source = 'cache';
    manifest = payload;
    remoteETag = cached.etag || null;
  }

  /** 当前清单（只读语义）。 */
  function getManifest() { return manifest; }

  /** 取得 id 对应的曲目（也支持传 URL）。 */
  function findTrack(trackId) {
    if (!manifest) { return null; }
    for (var i = 0; i < manifest.tracks.length; i += 1) {
      var t = manifest.tracks[i];
      if (t.id === trackId || t.url === trackId) { return t; }
    }
    return null;
  }

  /** 取得 URL 对应的曲目（供 player 上报健康度与展示名）。 */
  function getTrackByUrl(url) {
    if (!manifest) { return null; }
    for (var i = 0; i < manifest.tracks.length; i += 1) {
      if (manifest.tracks[i].url === url || effectiveUrl(manifest.tracks[i]) === url) {
        return manifest.tracks[i];
      }
    }
    return null;
  }

  /** 应用 ?debug=1 的 manifestOverride（只改内存读取口径，不改磁盘文件）。 */
  function effectiveUrl(track) {
    var overrides = SW.RUNTIME.manifestOverrides || {};
    return Object.prototype.hasOwnProperty.call(overrides, track.id) ? overrides[track.id] : track.url;
  }

  /** 按 health 分数降序（cooldown 未到期者排最后，同分按清单稳定顺序）。 */
  function sortedTracks(list) {
    var now = Date.now();
    return list.map(function (t, idx) {
      var h = entryFor(t.id);
      var cooling = h.cooldownUntil && h.cooldownUntil > now ? 1 : 0;
      return { t: t, idx: idx, score: h.score, cooling: cooling };
    }).sort(function (a, b) {
      if (a.cooling !== b.cooling) { return a.cooling - b.cooling; }
      if (a.score !== b.score) { return b.score - a.score; }
      return a.idx - b.idx;
    }).map(function (x) { return x.t; });
  }

  /**
   * 取得可播放曲目（enabled && !needsReview && health!=="dead"）。
   * @param {string=} scene 可选场景过滤
   */
  function getTracks(scene) {
    if (!manifest) { return []; }
    var list = manifest.tracks.filter(function (t) {
      return t.enabled !== false && t.needsReview !== true && t.health !== 'dead';
    });
    if (scene) { list = list.filter(function (t) { return t.scene === scene; }); }
    return sortedTracks(list);
  }

  /**
   * 多候选解析（AD-05，全部由已实测 URL 构成，绝不臆造）：
   *   主 URL → 同 id 其它已验证文件 → 同 scene 其它已验证曲目（health 降序）→ 合成层由 player 兜底。
   * @param {string} trackId
   * @returns {string[]} URL 列表（去重）
   */
  function resolveCandidates(trackId) {
    var out = [];
    var seen = Object.create(null);
    function push(url) {
      if (typeof url === 'string' && url && !seen[url]) { seen[url] = 1; out.push(url); }
    }
    var primary = findTrack(trackId);
    if (!primary) { return out; }
    push(effectiveUrl(primary));
    (primary.candidates || []).forEach(push);
    /* 同 item / 同 identifier 的其它已验证文件 */
    var siblings = manifest.tracks.filter(function (t) {
      return t.item === primary.item && t.id !== primary.id;
    });
    sortedTracks(siblings).forEach(function (t) { push(effectiveUrl(t)); });
    /* 同 scene 其它已验证曲目（按 health 降序），最稳的真实备选池 */
    var sameScene = getTracks(primary.scene).filter(function (t) { return t.id !== primary.id; });
    sameScene.forEach(function (t) { push(effectiveUrl(t)); });
    return out;
  }

  /** 上报播放失败：score -25、cooldown、持久化（不改变播放态）。 */
  function reportFailure(trackId, url, reason) {
    var track = getTrackByUrl(url) || findTrack(trackId);
    var id = track ? track.id : trackId;
    var h = entryFor(id);
    h.score = Math.max(0, h.score - 25);
    h.fail += 1;
    h.consecutiveFail += 1;
    h.lastFailAt = new Date().toISOString();
    if (h.consecutiveFail >= 2) { h.cooldownUntil = Date.now() + C.COOLDOWN_MS; }
    persistHealth();
    store.pushLog({ type: 'health', action: 'fail', trackId: id, reason: reason || 'unknown', score: h.score });
  }

  /** 上报播放成功：score +5、清冷却、持久化。 */
  function reportSuccess(trackId, url) {
    var track = getTrackByUrl(url) || findTrack(trackId);
    var id = track ? track.id : trackId;
    var h = entryFor(id);
    h.score = Math.min(100, h.score + 5);
    h.ok += 1;
    h.consecutiveFail = 0;
    h.cooldownUntil = null;
    h.lastOkAt = new Date().toISOString();
    persistHealth();
    store.pushLog({ type: 'health', action: 'ok', trackId: id, score: h.score });
  }

  /** 健康度快照。 */
  function getHealth() {
    var out = Object.create(null);
    Object.keys(health).forEach(function (id) { out[id] = Object.assign({}, health[id]); });
    return out;
  }

  /** 清空健康度（「清除本地设置」与 inject.resetHealth 共用）。 */
  function resetHealth() {
    health = Object.create(null);
    store.removeStorage(K.health);
    store.pushLog({ type: 'health', action: 'reset' });
  }

  /**
   * 许可署名查证视图 AttributionView（A10 / AD-21 / AD-22 / AD-23）。
   * 结构固定为 display / source / license / licenseText / item / itemLabel /
   * attributionText / kind；查证视图同样不含源数据层的原始标题字段。
   * attributionText 由 display + source + licenseText 运行时组装，绝不虚构作者（AD-22）。
   * @param {string} trackId
   * @returns {Object} AttributionView（额外保留 found 兼容既有调用方）
   */
  function getAttribution(trackId) {
    var t = findTrack(trackId);
    if (!t) {
      return {
        display: '', source: '', license: '', licenseText: '',
        item: '', itemLabel: ITEM_LABEL, attributionText: '',
        kind: '', found: false
      };
    }
    var view = sanitizeForUI(t);
    var licenseText = view.licenseText;
    return {
      display: view.display,
      source: view.source,
      license: String(t.license || ''),
      licenseText: licenseText,
      item: String(t.item || ''),
      itemLabel: view.itemLabel,
      attributionText: view.display + ' · ' + view.source + ' · ' + licenseText,
      kind: view.kind,
      found: true
    };
  }

  /** 带超时的 fetch（仅 http(s) 调用；offline 注入时直接失败）。 */
  function fetchWithTimeout(url, options, timeoutMs) {
    if (SW.RUNTIME.offline) { return Promise.reject(new Error('offline')); }
    if (typeof window.fetch !== 'function') { return Promise.reject(new Error('no-fetch')); }
    var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var opts = Object.assign({}, options || {});
    if (controller) { opts.signal = controller.signal; }
    var timer = null;
    return new Promise(function (resolve, reject) {
      timer = window.setTimeout(function () {
        if (controller) { try { controller.abort(); } catch (err) { /* 静默 */ } }
        reject(new Error('timeout'));
      }, timeoutMs || C.REMOTE_TIMEOUT_MS);
      window.fetch(url, opts).then(function (resp) {
        window.clearTimeout(timer);
        resolve(resp);
      }, function (err) {
        window.clearTimeout(timer);
        reject(err);
      });
    });
  }

  /** 拉取并解析单个远端清单，返回 payload 或 null（任何失败都不抛）。 */
  function fetchRemote(url) {
    var headers = {};
    if (remoteETag) { headers['If-None-Match'] = remoteETag; }
    return fetchWithTimeout(url, { method: 'GET', headers: headers, cache: 'no-store' }, C.REMOTE_TIMEOUT_MS)
      .then(function (resp) {
        if (!resp || resp.status === 304) { return null; }
        if (resp.status < 200 || resp.status >= 300) { return null; }
        var etag = '';
        try { etag = resp.headers.get('etag') || ''; } catch (err) { etag = ''; }
        return resp.json().then(function (data) { return { data: data, etag: etag }; });
      })
      .catch(function () { return null; });
  }

  /** 标题黑名单过滤（S-05 / D6）。 */
  function blacklisted(text) {
    var value = String(text || '');
    for (var i = 0; i < C.FILTER_BLACKLIST.length; i += 1) {
      if (C.FILTER_BLACKLIST[i].test(value)) { return true; }
    }
    return false;
  }

  /**
   * L3 运行时动态发现（仅在 http(s) 且 ENABLE_DISCOVERY）：
   * advancedsearch → metadata → 规则过滤 → 候选（verified:false / needsReview:true）。
   * 结果只进 discovered[] / manifest.candidates，永不进入播放序列（AD-10）。
   */
  function discover() {
    discovered = [];
    if (!isHttp() || !C.ENABLE_DISCOVERY || SW.RUNTIME.offline) { return Promise.resolve([]); }
    var rules = C.FILTER_RULES;
    var query = encodeURIComponent(rules.query);
    var searchUrl = 'https://archive.org/advancedsearch.php?q=' + query +
      '&fl%5B%5D=identifier&rows=' + rules.rows + '&output=json';
    return fetchWithTimeout(searchUrl, { method: 'GET' }, C.REMOTE_TIMEOUT_MS)
      .then(function (resp) { return resp && resp.ok ? resp.json() : null; })
      .then(function (data) {
        var docs = data && data.response && Array.isArray(data.response.docs) ? data.response.docs : [];
        var ids = [];
        for (var i = 0; i < docs.length && ids.length < 8; i += 1) {
          var identifier = String(docs[i].identifier || '');
          var prefixOk = rules.identifierPrefixes.some(function (p) { return identifier.indexOf(p) === 0; });
          if (prefixOk && !blacklisted(identifier)) { ids.push(identifier); }
        }
        return Promise.all(ids.map(function (id) {
          var metaUrl = 'https://archive.org/metadata/' + encodeURIComponent(id);
          return fetchWithTimeout(metaUrl, { method: 'GET' }, C.REMOTE_TIMEOUT_MS)
            .then(function (r) { return r && r.ok ? r.json() : null; })
            .then(function (meta) { return { id: id, meta: meta }; })
            .catch(function () { return { id: id, meta: null }; });
        }));
      })
      .then(function (pairs) {
        var out = [];
        pairs.forEach(function (pair) {
          if (!pair.meta || !Array.isArray(pair.meta.files)) { return; }
          for (var i = 0; i < pair.meta.files.length && out.length < 20; i += 1) {
            var f = pair.meta.files[i];
            var name = String(f.name || '');
            var lower = name.toLowerCase();
            var extOk = rules.extensions.some(function (ext) { return lower.slice(-ext.length) === ext; });
            if (!extOk) { continue; }
            var size = parseInt(f.size, 10);
            if (!isNaN(size) && (size < rules.minBytes || size > rules.maxBytes)) { continue; }
            var title = String(f.title || name);
            if (blacklisted(title)) { continue; }
            var url = 'https://archive.org/download/' + encodeURIComponent(pair.id) + '/' +
              encodeURIComponent(name);
            out.push({
              id: pair.id, url: url, display: '待审定', originalTitle: title,
              bytes: isNaN(size) ? 0 : size, scene: 'empty', kind: 'music',
              license: 'CC，详见来源页',
              attribution: 'Internet Archive (动态发现) · CC，详见来源页 · 待校验',
              item: 'https://archive.org/details/' + encodeURIComponent(pair.id),
              source: 'Internet Archive (动态发现)',
              verified: false, needsReview: true, enabled: false,
              health: 'unknown', cors: false, discoveredAt: new Date().toISOString()
            });
          }
        });
        discovered = out;
        if (manifest) {
          manifest.candidates = out.slice();
          manifest.quarantine = Array.isArray(manifest.quarantine) ? manifest.quarantine : [];
        }
        store.pushLog({ type: 'discovery', action: 'done', count: out.length, promotedToTracks: 0 });
        return out;
      })
      .catch(function () {
        discovered = [];
        return [];
      });
  }

  /** 当前 L3 候选（供 P1-07 详情面板展示「发现的候选（待校验）」）。 */
  function getCandidates() { return (manifest && manifest.candidates ? manifest.candidates : discovered).slice(); }

  /**
   * 刷新曲库编排（§5.4 / P0-13 / F6）。
   * 未配置远程 → skipped（功能仍 100% 完整）；失败保留现有清单、不清空、不打断播放。
   * @param {{silent:boolean}} opts
   * @returns {Promise<{status:string,version:number,count:number,reason?:string}>}
   */
  function refresh(opts) {
    var silent = !!(opts && opts.silent);
    if (refreshing) {
      return Promise.resolve({ status: 'unchanged', version: manifest.version, count: manifest.tracks.length, reason: 'in-progress' });
    }
    var remotes = C.resolvedRemotes || [];
    if (SW.RUNTIME.offline) {
      store.emit(silent ? E.STATE : E.LIBRARY_FAILED, { reason: 'offline' });
      if (!silent) { store.pushLog({ type: 'library', action: 'failed', reason: 'offline' }); }
      return Promise.resolve({ status: 'failed', version: manifest.version, count: manifest.tracks.length, reason: 'offline' });
    }
    if (!isHttp() || remotes.length === 0) {
      var skipped = { status: 'skipped', version: manifest.version, count: manifest.tracks.length, reason: 'remote-not-configured' };
      store.pushLog({ type: 'library', action: 'skipped', reason: skipped.reason });
      return Promise.resolve(skipped);
    }

    refreshing = true;
    if (!silent) {
      store.patch({ badge: 'refreshing', badgeText: '正在刷新', libraryStatus: 'refreshing' });
      store.emit(E.LIBRARY_REFRESHING, {});
    }

    var chain = Promise.resolve(null);
    remotes.forEach(function (url) {
      chain = chain.then(function (found) {
        if (found) { return found; }
        return fetchRemote(url);
      });
    });

    return chain.then(function (found) {
      if (!found || !found.data || !validateManifest(found.data)) {
        throw new Error('no-valid-manifest');
      }
      if (found.data.version <= manifest.version) {
        throw new Error('version-not-newer');
      }
      /* 原子替换：全链路校验通过才整体替换 */
      var next = clone(found.data);
      next.__source = 'remote';
      manifest = next;
      remoteETag = found.etag || remoteETag;
      store.writeStorage(K.manifest, {
        etag: remoteETag, version: next.version,
        fetchedAt: new Date().toISOString(), payload: next
      });
      store.patch({
        manifest: {
          version: next.version, updatedAt: next.updatedAt || '',
          count: next.tracks.length, source: 'remote'
        },
        libraryStatus: 'success'
      });
      store.emit(E.LIBRARY_UPDATED, { version: next.version, count: next.tracks.length, updatedAt: next.updatedAt || '' });
      store.pushLog({ type: 'library', action: 'updated', version: next.version, count: next.tracks.length });
      return { status: 'updated', version: next.version, count: next.tracks.length };
    }).catch(function (err) {
      store.patch({ libraryStatus: 'failed' });
      store.emit(E.LIBRARY_FAILED, { reason: String(err && err.message || 'unknown') });
      store.pushLog({ type: 'library', action: 'failed', reason: String(err && err.message || 'unknown') });
      return {
        status: 'failed', version: manifest.version,
        count: manifest.tracks.length, reason: String(err && err.message || 'unknown')
      };
    }).then(function (result) {
      refreshing = false;
      if (!silent) {
        /* 徽标回到当前真实音源层，由 player 提供 */
        restoreBadge();
      }
      return result;
    });
  }

  /** 刷新结束后按当前音源层恢复徽标（只读 store，不引用 player，§8.2）。 */
  function restoreBadge() {
    var s = store.getState();
    var badge = 'synth';
    var text = '本地合成';
    if (s.sourceTier === 'bundled' || s.sourceTier === 'remote') {
      badge = s.currentSource && s.currentSource.status === 'backup' ? 'backup' : 'online';
      text = badge === 'backup' ? '备用音源' : '在线可用';
    }
    store.patch({ badge: badge, badgeText: text });
  }

  /**
   * 清单摘要（P1-07 / A13 / __STILLWAVE__.getManifestSummary）。
   * byScene 覆盖四场景，byKind 给出 music/nature 构成（A13 断言 nature===9）。
   */
  function getManifestSummary() {
    var byScene = { focus: 0, sleep: 0, empty: 0, meditation: 0 };
    var byKind = { music: 0, nature: 0 };
    (manifest ? manifest.tracks : []).forEach(function (t) {
      if (Object.prototype.hasOwnProperty.call(byScene, t.scene)) { byScene[t.scene] += 1; }
      if (Object.prototype.hasOwnProperty.call(byKind, t.kind)) { byKind[t.kind] += 1; }
    });
    return {
      version: manifest ? manifest.version : 0,
      count: manifest ? manifest.tracks.length : 0,
      byScene: byScene,
      byKind: byKind,
      updatedAt: manifest ? (manifest.updatedAt || '') : '',
      candidates: getCandidates().length,
      quarantined: manifest && manifest.quarantine ? manifest.quarantine.length : 0
    };
  }

  /* ===== AD-21 / AD-22 / AD-23：三层字段隔离、许可本地化与 A14 文本审计 ===== */

  /** AD-23：item 链接唯一可见文字（href 指向 item，页面绝不显示裸 URL / 错误码 / 堆栈）。 */
  var ITEM_LABEL = '查看原始条目页 ↗';

  /** A14 杂质词表（与 QA 静态口径一致：地区名 / 地名 / 编号 / 繁体独有字）。 */
  var IMPURITY_WORDS = [
    'Kaluga', 'GHENT', 'BRUSSELS', 'Municipal District', 'Yamanashi',
    'Fujikawaguchiko', 'Taoyuan', 'Taichung', 'Taitung', 'L 50',
    'Zhukovsky', 'Thungabadra', '東眼山', '草嶺', '鹿野'
  ];
  var TRADITIONAL_CHARS = '東臺遊樂區導線雙嶺縣龍禱來崑';
  /* 电话 / 长编号杂质：+<11 位以上>、独立 9 位以上数字串、成组电话号码 */
  var IMPURITY_PATTERNS = [
    /\+\d{11,}/,
    /\b\d{9,}\b/,
    /\d{3,}[\s\-]?\d{3,}/
  ];

  /**
   * AD-23 / P0-16：把多种 CC 许可值本地化为简体中文展示文案。
   * 展示层只使用本函数结果，绝不显示原始许可 URL。
   * @param {string} license
   * @returns {string}
   */
  function localizeLicense(license) {
    var raw = String(license || '').toLowerCase();
    if (!raw || raw.indexOf('see item page') >= 0 || raw === 'cc，详见来源页') {
      return 'CC 授权，详见来源页';
    }
    if (raw.indexOf('by-nc-nd') >= 0) { return 'CC 署名-非商业-禁止演绎 3.0'; }
    if (raw.indexOf('by-nc-sa') >= 0) { return 'CC 署名-非商业-相同方式共享 3.0'; }
    if (raw.indexOf('by-sa') >= 0) { return 'CC 署名-相同方式共享 3.0'; }
    if (raw.indexOf('licenses/by') >= 0 || raw.indexOf('/by/') >= 0) { return 'CC 署名 3.0'; }
    return 'CC 授权，详见来源页';
  }

  /**
   * AD-21 白名单投影：把源数据层 Track 投影为 UI 唯一可及的 UiTrack。
   * 只保留 id / display / scene / kind / source / licenseText / itemLabel 七个字段；
   * 明确不含 url、原始标题、bytes、health、candidates 及任何原始 URL 文本（S-10）。
   * 对已投影的 UiTrack 幂等，也支持直接传清单 id 字符串，便于契约断言。
   * @param {Object|string} track
   * @returns {{id:string,display:string,scene:string,kind:string,source:string,licenseText:string,itemLabel:string}}
   */
  function sanitizeForUI(track) {
    var t = track;
    if (typeof t === 'string') { t = findTrack(t); }
    if (!t || typeof t !== 'object') { t = {}; }
    return {
      id: String(t.id || ''),
      display: String(t.display || ''),
      scene: String(t.scene || 'empty'),
      kind: t.kind === 'nature' ? 'nature' : 'music',
      source: String(t.source || ''),
      licenseText: String(t.licenseText || localizeLicense(t.license)),
      itemLabel: ITEM_LABEL
    };
  }

  /** 按 id 取得白名单投影后的 UiTrack（UI 层只读出口，AD-21）。 */
  function getUiTrack(trackId) {
    var t = findTrack(trackId);
    return t ? sanitizeForUI(t) : null;
  }

  /** 全量曲目的白名单投影列表（详情面板 / 契约只读）。 */
  function getUiTrackList() {
    return (manifest ? manifest.tracks : []).map(function (t) { return sanitizeForUI(t); });
  }

  /** 归一化（大小写 / 连续空白）后做子串命中，供 A14 源标题检索。 */
  function normalizedIncludes(haystack, needle) {
    var n = String(needle || '').toLowerCase().replace(/\s+/g, ' ').trim();
    if (!n) { return false; }
    var h = String(haystack || '').toLowerCase().replace(/\s+/g, ' ');
    return h.indexOf(n) >= 0;
  }

  /**
   * A14 / P0-18 全站文本审计（由 __STILLWAVE__.getVisibleTextSnapshot 传入真实 DOM 扫描结果）。
   * 命中检测真实遍历清单 30 条源标题、杂质词表、繁体独有字与长编号模式；
   * 两个命中数组均由检测结果填充，禁止硬编码空数组。
   * 原始标题清单只存在于本数据层，展示层 / 契约层在架构上拿不到（AD-21）。
   * @param {string} allVisibleText
   * @param {{player:string,mixer:string[],details:string[],share:string}} trackNames
   * @returns {{allVisibleText:string,trackNames:Object,originalTitleHits:string[],impurityHits:string[]}}
   */
  function buildVisibleTextSnapshot(allVisibleText, trackNames) {
    var names = trackNames || {};
    var searchable = [
      String(allVisibleText || ''),
      String(names.player || ''),
      (names.mixer || []).join('\n'),
      (names.details || []).join('\n'),
      String(names.share || '')
    ].join('\n');

    var titleHits = [];
    (manifest ? manifest.tracks : []).forEach(function (t) {
      var sourceTitle = String(t.originalTitle || '').trim();
      if (sourceTitle && normalizedIncludes(searchable, sourceTitle) &&
          titleHits.indexOf(sourceTitle) < 0) {
        titleHits.push(sourceTitle);
      }
    });

    var impurityHits = [];
    IMPURITY_WORDS.forEach(function (word) {
      if (searchable.indexOf(word) >= 0 && impurityHits.indexOf(word) < 0) {
        impurityHits.push(word);
      }
    });
    for (var i = 0; i < TRADITIONAL_CHARS.length; i += 1) {
      var ch = TRADITIONAL_CHARS.charAt(i);
      if (searchable.indexOf(ch) >= 0 && impurityHits.indexOf(ch) < 0) {
        impurityHits.push(ch);
      }
    }
    IMPURITY_PATTERNS.forEach(function (re) {
      var m = re.exec(searchable);
      if (m && impurityHits.indexOf(m[0]) < 0) { impurityHits.push(m[0]); }
    });

    return {
      allVisibleText: String(allVisibleText || ''),
      trackNames: {
        player: String(names.player || ''),
        mixer: (names.mixer || []).slice(),
        details: (names.details || []).slice(),
        share: String(names.share || '')
      },
      originalTitleHits: titleHits,
      impurityHits: impurityHits
    };
  }

  /** 电台（L4）：默认关闭，仅预留 provider 与标注，不发起任何请求（AD-12）。 */
  var radio = { enabled: C.ENABLE_RADIO, label: '电台（质量不可控）', provider: null, url: null };

  SW.sources = {
    init: init,
    getManifest: getManifest,
    getTracks: getTracks,
    resolveCandidates: resolveCandidates,
    sanitizeForUI: sanitizeForUI,
    getUiTrack: getUiTrack,
    getUiTrackList: getUiTrackList,
    localizeLicense: localizeLicense,
    buildVisibleTextSnapshot: buildVisibleTextSnapshot,
    refresh: refresh,
    discover: discover,
    reportFailure: reportFailure,
    reportSuccess: reportSuccess,
    getHealth: getHealth,
    getAttribution: getAttribution,
    resetHealth: resetHealth,
    /* 契约所需的扩展只读面 */
    getTrackByUrl: getTrackByUrl,
    getCandidates: getCandidates,
    getManifestSummary: getManifestSummary,
    getRadio: function () { return Object.assign({}, radio); },
    validateManifest: validateManifest
  };
})();

// Digital Canvas control panel. No framework, no build step: state arrives
// over Server-Sent Events and the DOM is updated in place.
(() => {
  'use strict';

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const svg = (name, cls = '') => `<svg class="ico ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;

  const THEMES = [
    ['dark-theme', 'Midnight', '#0c0c11', '#a78bfa', '#ededf2'],
    ['light-theme', 'Daylight', '#f4f4f8', '#5b47f0', '#15151d'],
    ['darcula-theme', 'Darcula', '#1e1f22', '#ffcb6b', '#dfe1e5'],
    ['warm-sunset-theme', 'Warm Sunset', '#1a1011', '#ff8a4c', '#fbebe6'],
    ['ocean-breeze-theme', 'Ocean Breeze', '#071619', '#3ecfb2', '#e0f6f2'],
    ['autumn-leaves-theme', 'Autumn Leaves', '#1a120d', '#f59e0b', '#f8e8d4'],
    ['winter-wonderland-theme', 'Winter Wonderland', '#0b131c', '#7dd3fc', '#e8f4fb'],
    ['spring-blossom-theme', 'Spring Blossom', '#1a0f15', '#f9a8d4', '#fde8f1'],
  ];

  const state = {
    config: {}, slide: null, playback: {}, status: {}, power: true,
    media: new Map(), info: null, playbackAt: 0,
  };
  const ui = { selecting: false, selected: new Set(), tab: 'slideshow', tiles: new Map(), menuFor: null };

  // ---------------------------------------------------------------- api

  async function request(method, path, body) {
    const opt = { method, headers: { Accept: 'application/json' } };
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    const res = await fetch(path, opt);
    let data = {};
    try { data = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) {
      const errs = data.errors && Object.entries(data.errors).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`).join('; ');
      const err = new Error(errs || data.error || res.statusText || 'Request failed');
      err.data = data;
      throw err;
    }
    return data;
  }
  const api = {
    get: (p) => request('GET', p),
    post: (p, b) => request('POST', p, b === undefined ? {} : b),
    patch: (p, b) => request('PATCH', p, b),
  };

  // ------------------------------------------------------------ helpers

  function toast(msg, kind) {
    const el = document.createElement('div');
    el.className = 'toast' + (kind ? ' ' + kind : '');
    el.textContent = msg;
    $('#toasts').append(el);
    setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 300); }, kind === 'error' ? 5000 : 2600);
  }

  function fmtDuration(sec) {
    sec = Math.max(0, Math.round(sec));
    if (sec < 60) return sec + ' s';
    if (sec < 3600) {
      const m = Math.floor(sec / 60), s = sec % 60;
      return m + ' min' + (s ? ' ' + s + ' s' : '');
    }
    const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
    return h + ' h' + (m ? ' ' + m + ' min' : '');
  }

  function fmtClock(sec) {
    sec = Math.max(0, Math.ceil(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0');
  }

  function fmtBytes(n) {
    if (!n) return '–';
    const u = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return n.toFixed(n < 10 && i ? 1 : 0) + ' ' + u[i];
  }

  function fmtDate(ms) {
    if (!ms) return '';
    const d = new Date(ms);
    const sameYear = d.getFullYear() === new Date().getFullYear();
    return d.toLocaleDateString(undefined, sameYear ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function kindLabel(kind) {
    return kind === 'video' ? 'Video' : kind === 'gif' ? 'Animation' : 'Photo';
  }

  function itemTitle(it) {
    if (!it) return '';
    return it.title || `${kindLabel(it.kind)} added ${fmtDate(it.added)}`;
  }

  function sanitizeName(v) {
    return v.replace(/\s+/g, '-').replace(/[^a-z0-9-]/gi, '');
  }

  function confirmBox(title, text, okLabel) {
    const dlg = $('#confirmDialog');
    $('#confirmTitle').textContent = title;
    $('#confirmText').textContent = text;
    $('#confirmOk').textContent = okLabel || 'Confirm';
    dlg.returnValue = '';
    dlg.showModal();
    return new Promise((res) => dlg.addEventListener('close', () => res(dlg.returnValue === 'ok'), { once: true }));
  }

  // ------------------------------------------------------------- config

  let pending = {};
  let patchTimer = 0;

  function setConfig(values, delay) {
    Object.assign(state.config, values);
    Object.assign(pending, values);
    renderConfig();
    clearTimeout(patchTimer);
    patchTimer = setTimeout(flushConfig, delay || 0);
  }

  async function flushConfig() {
    const body = pending;
    pending = {};
    if (!Object.keys(body).length) return;
    try {
      const r = await api.patch('/api/config', body);
      state.config = Object.assign(r.config, pending);
      if (r.restart_required && r.restart_required.length) toast('Restart the app to apply this change');
    } catch (e) {
      toast(e.message, 'error');
      if (e.data && e.data.config) state.config = Object.assign(e.data.config, pending);
    }
    renderConfig();
  }

  function bindSettings() {
    for (const group of $$('[data-setting]:not(input)')) {
      group.addEventListener('click', (e) => {
        const b = e.target.closest('button[data-value]');
        if (!b || !group.contains(b)) return;
        let v = b.dataset.value;
        if (group.dataset.type === 'int') v = parseInt(v, 10);
        setConfig(Object.assign({ [group.dataset.setting]: v }, group.dataset.extra ? JSON.parse(group.dataset.extra) : {}));
      });
    }
    for (const inp of $$('input[data-setting]')) {
      const key = inp.dataset.setting;
      const read = () => {
        if (inp.type === 'checkbox') return inp.checked;
        if (inp.type === 'number' || inp.type === 'range') {
          const n = parseFloat(inp.value);
          return Number.isFinite(n) ? n : undefined;
        }
        return inp.value;
      };
      if (inp.type === 'checkbox' || inp.type === 'time') {
        inp.addEventListener('change', () => setConfig({ [key]: read() }));
      } else {
        inp.addEventListener('input', () => {
          const v = read();
          if (v === undefined || v === '') return;
          if (inp.type === 'range') syncTwins(inp, v);
          setConfig({ [key]: v }, inp.type === 'range' ? 250 : 700);
        });
      }
    }
  }

  // keep a range and its number twin in sync while dragging
  function syncTwins(src, v) {
    for (const other of $$(`input[data-setting="${src.dataset.setting}"]`)) if (other !== src) other.value = v;
  }

  // ------------------------------------------------------------- render

  function renderConfig() {
    const c = state.config;
    const root = document.documentElement;
    root.dataset.theme = c.theme || 'dark-theme';
    const theme = THEMES.find((t) => t[0] === root.dataset.theme);
    if (theme) $('meta[name="theme-color"]').content = theme[2];

    for (const group of $$('[data-setting]:not(input)')) {
      const v = String(c[group.dataset.setting]);
      for (const b of $$('button[data-value]', group)) b.setAttribute('aria-pressed', String(b.dataset.value === v));
    }
    for (const inp of $$('input[data-setting]')) {
      if (inp === document.activeElement) continue;
      const v = c[inp.dataset.setting];
      if (v === undefined) continue;
      if (inp.type === 'checkbox') inp.checked = !!v;
      else inp.value = v;
    }

    $('#deviceNameText').textContent = c.device_name || 'Digital Canvas';
    document.title = (c.device_name ? c.device_name + ' · ' : '') + 'Digital Canvas';
    if ($('#deviceNameField') !== document.activeElement) $('#deviceNameField').value = c.device_name || '';
    $('#rotLabel').textContent = (c.rotation || 0) + '°';
    $('#activeSwitch').checked = !!state.playback.active;

    const iv = Number(c.frame_interval) || 0;
    $('#intervalDesc').textContent = iv ? fmtDuration(iv) + ' per photo · videos play to the end' : '';
    for (const p of $$('#intervalPresets [data-preset]')) p.setAttribute('aria-pressed', String(Number(p.dataset.preset) === iv));

    $('.schedule').classList.toggle('disabled', !c.schedule_enabled);
    for (const t of $$('.schedule input')) t.disabled = !c.schedule_enabled;
    $('#brightness').disabled = !!c.auto_brightness;

    renderThemes();
    renderMqttForm();
    renderStatus();
    renderPreview();
    applyFilter();
  }

  function renderThemes() {
    const box = $('#themes');
    if (!box.children.length) {
      for (const [key, name, bg, accent, text] of THEMES) {
        const b = document.createElement('button');
        b.className = 'theme-btn';
        b.dataset.value = key;
        b.innerHTML = `<span class="theme-sw"><i style="background:${bg}"></i><i style="background:${accent}"></i><i style="background:${text}"></i></span>${name}`;
        b.addEventListener('click', () => setConfig({ theme: key }));
        box.append(b);
      }
    }
    for (const b of box.children) b.setAttribute('aria-pressed', String(b.dataset.value === state.config.theme));
  }

  function renderMqttForm() {
    const f = $('#mqttForm');
    const c = state.config;
    if (f.contains(document.activeElement) || f.dataset.dirty) return;
    f.mqtt_broker.value = c.mqtt_broker || '';
    f.mqtt_port.value = c.mqtt_port || 1883;
    f.mqtt_topic.value = c.mqtt_topic || '';
    f.mqtt_username.value = c.mqtt_username || '';
    f.mqtt_password.value = '';
    f.mqtt_password.placeholder = c.mqtt_password ? 'Saved – leave empty to keep' : '';
    const t = c.mqtt_topic || 'topic';
    const rows = [
      ['slideshow', 'next · previous · pause · resume · quit'], ['select', '<file name>'],
      ['rotation', '0 · 90 · 180 · 270'], ['scale_mode', 'fit · fill'], ['display_mode', 'fullscreen · windowed'],
      ['brightness', '0–100 · auto'], ['power', 'on · off'], ['frame_interval', 'seconds'],
      ['transition_duration', 'seconds'], ['media_orientation_filter', 'both · landscape · portrait'],
      ['playback_mode', 'sequential · random'], ['auto_brightness', 'on · off'], ['auto_rotation', 'on · off'],
      ['theme', 'dark-theme · …'], ['plex', 'on · off'], ['display_now', 'image URL or base64'],
    ];
    $('#mqttTopics').innerHTML =
      '<div><b>Commands</b> (append <code>/set</code> optionally)</div>' +
      rows.map(([k, v]) => `<div><code>${t}/${k}</code> ${v}</div>`).join('') +
      '<div style="margin-top:.4rem"><b>Published</b></div>' +
      ['current_image', 'available_images (retained)', 'config', 'light_sensor', 'screen_brightness', 'status (online/offline)']
        .map((k) => `<div><code>${t}/${k.split(' ')[0]}</code> ${k.includes(' ') ? k.slice(k.indexOf(' ') + 1) : ''}</div>`).join('');
  }

  function setPill(el, cls, text, title) {
    el.className = 'pill' + (cls ? ' ' + cls : '');
    el.lastElementChild.textContent = text;
    el.title = title || text;
  }

  function renderStatus() {
    const s = state.status;
    if (!s.mqtt) return;
    const c = state.config;
    const n = s.displays || 0;
    setPill($('#pillDisplay'), n ? 'ok' : 'warn', n ? (n > 1 ? n + ' displays' : 'Display') : 'No display',
      n ? `${n} display${n > 1 ? 's' : ''} connected` : 'No display is connected');
    const mq = s.mqtt;
    setPill($('#pillMqtt'), mq.connected ? 'ok' : mq.error ? 'bad' : 'warn', 'MQTT',
      mq.connected ? 'Connected to ' + mq.broker : 'Not connected to ' + mq.broker + (mq.error ? ': ' + mq.error : ''));
    setPill($('#mqttStatus'), mq.connected ? 'ok' : mq.error ? 'bad' : 'warn', mq.connected ? 'Connected' : 'Disconnected');
    $('#mqttError').textContent = !mq.connected && mq.error ? mq.error : '';
    const on = s.monitor.power;
    setPill($('#pillScreen'), on ? 'ok' : '', on ? 'Screen on' : 'Screen off');

    for (const b of $$('#powerSeg button')) b.setAttribute('aria-pressed', String((b.dataset.power === 'on') === on));
    $('#powerDesc').textContent = s.monitor.ddc ? `DDC/CI · ${s.monitor.name || 'monitor'}` : 'Blanks the display (no DDC/CI monitor found)';

    const br = $('#brightness');
    if (br !== document.activeElement && s.monitor.brightness >= 0) {
      br.value = s.monitor.brightness;
      $('#brightnessOut').textContent = s.monitor.brightness + '%';
    } else if (s.monitor.brightness < 0 && br !== document.activeElement) {
      $('#brightnessOut').textContent = '–';
    }
    $('#brightnessDesc').textContent = !s.monitor.ddc ? 'Needs a monitor with DDC/CI'
      : c.auto_brightness ? 'Controlled by the light sensor' : 'Manual';
    br.disabled = !!c.auto_brightness || (!s.monitor.ddc && !s.simulated);
    const ab = $('#autoBrightDesc');
    ab.textContent = s.sensors.light ? `Light sensor · ${Math.round(s.sensors.lux)} lux now` : 'No light sensor detected';
    ab.classList.toggle('warn', !s.sensors.light && !!c.auto_brightness);
    const ar = $('#autoRotDesc');
    ar.textContent = s.sensors.accel ? 'Uses the accelerometer' : 'No accelerometer detected';
    ar.classList.toggle('warn', !s.sensors.accel && !!c.auto_rotation);

    const k = s.kiosk;
    $('#kioskDesc').textContent = (k.enabled ? `${k.browser || 'Browser'} · ${k.running ? 'running' : 'starting'}` : 'Kiosk browser disabled')
      + (s.screen ? ` · ${s.screen.width}×${s.screen.height}` : '');
    const pv = $('#preview');
    pv.classList.toggle('off', !on);
    if (s.screen && s.screen.width && s.screen.height) {
      let w = s.screen.width, h = s.screen.height;
      pv.style.setProperty('--ar', `${w} / ${h}`);
      pv.classList.toggle('tall', h > w);
    }
  }

  // The preview mirrors the display: same layer structure, rotation and
  // scaling, rendered with container query units.
  let previewKey = '';
  function renderPreview() {
    const s = state.slide;
    const c = state.config;
    const pv = $('#preview');
    if (!s) return;
    const key = [s.seq, s.src, c.rotation, c.scale_mode].join('|');
    if (key === previewKey) return;
    previewKey = key;
    const layer = document.createElement('div');
    layer.className = `pl r${c.rotation || 0}${c.scale_mode === 'fill' && s.kind !== 'idle' ? ' fill' : ''}`;
    const add = (cls, src) => {
      const img = new Image();
      img.className = cls;
      img.alt = '';
      img.decoding = 'async';
      img.src = src;
      layer.append(img);
      return img;
    };
    let main;
    if (s.kind === 'idle') {
      main = add('bg', s.bg || '/assets/background.jpg');
      const hint = document.createElement('div');
      hint.className = 'idle-hint';
      hint.textContent = 'Nothing to show yet · add photos below';
      layer.append(hint);
    } else {
      if (s.bg) add('bg', s.bg);
      main = add('fg', s.kind === 'video' ? s.thumb : s.src);
      if (s.kind === 'video') {
        const b = document.createElement('span');
        b.className = 'badge-video';
        b.innerHTML = svg('play');
        layer.append(b);
      }
    }
    pv.append(layer);
    const reveal = () => {
      requestAnimationFrame(() => layer.classList.add('on'));
      setTimeout(() => { for (const el of $$('.pl', pv)) if (el !== layer && el.compareDocumentPosition(layer) & Node.DOCUMENT_POSITION_FOLLOWING) el.remove(); }, 500);
    };
    main.decode ? main.decode().then(reveal, reveal) : (main.onload = reveal);
    setAmbient(s.kind === 'idle' ? s.bg : s.bg || s.thumb);
  }

  let ambientIdx = 0;
  function setAmbient(src) {
    if (!src) return;
    const imgs = $$('#ambient img');
    const cur = imgs[ambientIdx];
    if (cur.dataset.src === src) return;
    ambientIdx = 1 - ambientIdx;
    const next = imgs[ambientIdx];
    next.onload = () => { next.classList.add('on'); cur.classList.remove('on'); };
    next.dataset.src = src;
    next.src = src;
  }

  function renderSlide() {
    const s = state.slide;
    if (!s) return;
    const it = state.media.get(s.name);
    let eyebrow = 'Now showing', title, meta = [];
    if (s.kind === 'idle') {
      eyebrow = 'Ready';
      title = 'Add something to show';
    } else if (s.transient) {
      eyebrow = s.source === 'plex' ? 'Plex · now playing' : 'Sent to the canvas';
      title = s.source === 'plex' ? (s.title || 'Plex') : 'Shared image';
      if (s.width) meta.push(`${s.width} × ${s.height}`);
    } else {
      title = itemTitle(it) || kindLabel(s.kind);
      meta.push(`${svg(s.kind === 'video' ? 'film' : 'image', 'xs')}${kindLabel(s.kind)}`);
      if (s.width) meta.push(`${s.width} × ${s.height}`);
      if (s.duration && s.kind !== 'image') meta.push(fmtClock(s.duration));
      if (it && it.title) meta.push('Added ' + fmtDate(it.added));
    }
    $('#nowEyebrow').textContent = eyebrow;
    $('#nowTitle').textContent = title;
    $('#nowMeta').innerHTML = meta.map((m) => `<span>${m}</span>`).join('');
    for (const [name, el] of ui.tiles) el.classList.toggle('playing', name === s.name && !s.transient);
    renderPreview();
  }

  function renderPlayback() {
    const p = state.playback;
    const active = !!p.active;
    for (const b of [$('#playBtn'), $('#dockPlay')]) {
      b.innerHTML = svg(active ? 'pause' : 'play');
      b.setAttribute('aria-label', active ? 'Pause' : 'Play');
    }
    $('#activeSwitch').checked = active;
    const bar = $('#progressBar');
    const right = $('#progressRight');
    right.textContent = p.position ? `${p.position} of ${p.count}` : p.count ? `${p.count} in rotation` : '';
    const counting = active && p.remaining_ms >= 0 && p.total_ms > 0;
    const frac = counting ? Math.min(1, Math.max(0, 1 - p.remaining_ms / p.total_ms)) : 0;
    bar.style.transition = 'none';
    bar.style.transform = `scaleX(${frac})`;
    if (counting) {
      bar.getBoundingClientRect();
      bar.style.transition = `transform ${p.remaining_ms}ms linear`;
      bar.style.transform = 'scaleX(1)';
    }
    tickLabel();
  }

  function tickLabel() {
    const p = state.playback;
    const left = $('#progressLeft');
    if (!p.active) {
      left.textContent = p.paused_by === 'schedule' ? 'Paused · outside screen hours'
        : p.paused_by === 'plex' ? 'Paused · Plex is playing' : 'Paused';
      return;
    }
    if (p.remaining_ms >= 0) {
      const remain = (p.remaining_ms - (Date.now() - state.playbackAt)) / 1000;
      left.textContent = (p.until_end ? 'Video · ' : 'Next in ') + fmtClock(Math.max(0, remain));
    } else {
      left.textContent = p.until_end ? 'Playing video' : (state.slide && state.slide.kind === 'idle' ? 'Waiting for media' : '');
    }
  }
  setInterval(tickLabel, 1000);

  // --------------------------------------------------------------- grid

  function sortedMedia() {
    return Array.from(state.media.values()).sort((a, b) => (b.added - a.added) || (a.name < b.name ? 1 : -1));
  }

  function tileHTML(it) {
    const v = it.v || 0;
    const name = encodeURIComponent(it.name);
    return `
      <span class="ph">${svg(it.kind === 'video' ? 'film' : 'image')}</span>
      ${it.has_thumb ? `<img loading="lazy" decoding="async" alt="" src="/thumbnails/${name}?v=${v}">` : '<img alt="">'}
      <span class="tick">${svg('check')}</span>
      <span class="now-tag">Showing</span>
      <div class="tile-actions">
        <button data-act="show" aria-label="Show now" title="Show now">${svg('play')}</button>
        <a data-act="open" href="/media/${name}" target="_blank" rel="noopener" aria-label="Open original" title="Open original">${svg('external')}</a>
        <button class="del" data-act="delete" aria-label="Delete" title="Delete">${svg('trash')}</button>
        <button class="more-btn" data-act="menu" aria-label="More actions">${svg('more')}</button>
      </div>`;
  }

  function badges(el, it) {
    for (const b of $$('.tbadge', el)) b.remove();
    let has = false;
    if (it.kind === 'video' || it.kind === 'gif') {
      const b = document.createElement('span');
      b.className = 'tbadge kind';
      b.innerHTML = it.kind === 'video' ? `${svg('play')}${it.duration ? fmtClock(it.duration) : 'Video'}` : 'GIF';
      el.append(b);
      has = true;
    }
    if (it.status === 'processing' || it.error) {
      const b = document.createElement('span');
      b.className = 'tbadge state' + (it.error ? ' error' : '');
      b.textContent = it.error ? 'Unsupported' : it.kind === 'video' && it.has_thumb ? 'Optimising…' : 'Processing…';
      b.title = it.error || '';
      el.append(b);
      has = true;
    }
    el.classList.toggle('has-badge', has);
    el.classList.toggle('processing', it.status === 'processing' && !it.has_thumb);
  }

  function makeTile(it) {
    const el = document.createElement('div');
    el.className = 'tile';
    el.tabIndex = 0;
    el.setAttribute('role', 'listitem');
    el.dataset.name = it.name;
    el.dataset.orientation = it.orientation;
    el.dataset.v = String(it.v) + (it.has_thumb ? 't' : '');
    el.title = itemTitle(it);
    el.innerHTML = tileHTML(it);
    badges(el, it);
    const img = $('img', el);
    img.addEventListener('error', () => img.classList.add('broken'));
    if (state.slide && state.slide.name === it.name) el.classList.add('playing');
    if (ui.selected.has(it.name)) el.classList.add('selected');
    ui.tiles.set(it.name, el);
    return el;
  }

  function updateTile(el, it) {
    const key = String(it.v) + (it.has_thumb ? 't' : '');
    if (el.dataset.v !== key) {
      el.dataset.v = key;
      const sel = el.classList.contains('selected');
      const playing = el.classList.contains('playing');
      el.innerHTML = tileHTML(it);
      el.classList.toggle('selected', sel);
      el.classList.toggle('playing', playing);
    }
    el.dataset.orientation = it.orientation;
    el.title = itemTitle(it);
    badges(el, it);
  }

  function renderGrid() {
    const grid = $('#grid');
    ui.tiles.clear();
    grid.replaceChildren(...sortedMedia().map(makeTile));
    applyFilter();
  }

  function upsert(it) {
    const isNew = !state.media.has(it.name);
    state.media.set(it.name, it);
    const el = ui.tiles.get(it.name);
    if (el) updateTile(el, it);
    else {
      const tile = makeTile(it);
      const grid = $('#grid');
      const before = sortedMedia().find((x) => x.added < it.added || (x.added === it.added && x.name < it.name));
      const ref = before && ui.tiles.get(before.name);
      if (ref && ref !== tile && ref.parentNode === grid) grid.insertBefore(tile, ref); else grid.append(tile);
    }
    if (isNew || (state.slide && state.slide.name === it.name)) renderSlide();
    applyFilter();
  }

  function removeItem(name) {
    state.media.delete(name);
    ui.selected.delete(name);
    const el = ui.tiles.get(name);
    if (el) el.remove();
    ui.tiles.delete(name);
    applyFilter();
    renderSelection();
  }

  function applyFilter() {
    const f = state.config.media_orientation_filter || 'both';
    let shown = 0;
    for (const el of ui.tiles.values()) {
      const hide = f !== 'both' && el.dataset.orientation !== f;
      el.hidden = hide;
      if (!hide) shown++;
    }
    const total = state.media.size;
    $('#libCount').textContent = total ? (shown === total ? `${total} item${total === 1 ? '' : 's'}` : `${shown} of ${total}`) : '';
    $('#empty').hidden = total > 0;
    $('#grid').hidden = total === 0;
  }

  // -------------------------------------------------------- interaction

  async function showItem(name, el) {
    if (el) { el.classList.remove('pulse'); void el.offsetWidth; el.classList.add('pulse'); }
    try { await api.post(`/api/media/${encodeURIComponent(name)}/show`); } catch (e) { toast(e.message, 'error'); }
  }

  async function deleteItems(names) {
    if (!names.length) return;
    const one = names.length === 1;
    const ok = await confirmBox(one ? 'Delete this item?' : `Delete ${names.length} items?`,
      'The original file is removed from the canvas. This can’t be undone.', 'Delete');
    if (!ok) return;
    try {
      const r = await api.post('/api/media/delete', { names });
      toast(r.deleted === 1 ? 'Deleted' : `Deleted ${r.deleted} items`);
      if (ui.selecting) setSelecting(false);
    } catch (e) { toast(e.message, 'error'); }
  }

  function setSelecting(on) {
    ui.selecting = on;
    if (!on) {
      ui.selected.clear();
      for (const el of ui.tiles.values()) el.classList.remove('selected');
    }
    $('#grid').classList.toggle('selecting', on);
    $('#selectBtn').textContent = on ? 'Cancel' : 'Select';
    renderSelection();
  }

  function toggleSelected(name) {
    const el = ui.tiles.get(name);
    if (ui.selected.has(name)) ui.selected.delete(name); else ui.selected.add(name);
    if (el) el.classList.toggle('selected', ui.selected.has(name));
    renderSelection();
  }

  function renderSelection() {
    $('#selectionBar').hidden = !ui.selecting;
    $('#selCount').textContent = `${ui.selected.size} selected`;
    $('#selDelete').disabled = ui.selected.size === 0;
  }

  function openMenu(name) {
    const it = state.media.get(name);
    if (!it) return;
    ui.menuFor = name;
    $('#tileMenuImg').src = it.has_thumb ? `/thumbnails/${encodeURIComponent(name)}?v=${it.v}` : '';
    const dlg = $('#tileMenu');
    dlg.returnValue = '';
    dlg.showModal();
  }

  function bindGrid() {
    const grid = $('#grid');
    let pressTimer = 0, pressed = null, longPressed = false;
    grid.addEventListener('click', (e) => {
      const tile = e.target.closest('.tile');
      if (!tile) return;
      if (longPressed) { longPressed = false; e.preventDefault(); return; }
      const name = tile.dataset.name;
      const act = e.target.closest('[data-act]');
      if (ui.selecting) { e.preventDefault(); toggleSelected(name); return; }
      if (act) {
        const a = act.dataset.act;
        if (a === 'open') return; // let the link work
        e.preventDefault();
        if (a === 'delete') deleteItems([name]);
        else if (a === 'menu') openMenu(name);
        else showItem(name, tile);
        return;
      }
      showItem(name, tile);
    });
    grid.addEventListener('keydown', (e) => {
      const tile = e.target.closest('.tile');
      if (!tile || e.target !== tile) return;
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); ui.selecting ? toggleSelected(tile.dataset.name) : showItem(tile.dataset.name, tile); }
      if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteItems([tile.dataset.name]); }
    });
    // Long press (touch) starts selecting.
    grid.addEventListener('pointerdown', (e) => {
      const tile = e.target.closest('.tile');
      if (!tile || e.pointerType === 'mouse') return;
      pressed = tile;
      pressTimer = setTimeout(() => {
        longPressed = true;
        if (navigator.vibrate) navigator.vibrate(15);
        if (!ui.selecting) setSelecting(true);
        toggleSelected(tile.dataset.name);
      }, 480);
    });
    const cancel = () => { clearTimeout(pressTimer); pressed = null; };
    grid.addEventListener('pointerup', cancel);
    grid.addEventListener('pointercancel', cancel);
    grid.addEventListener('pointermove', (e) => { if (pressed && (Math.abs(e.movementX) + Math.abs(e.movementY) > 6)) cancel(); });
    grid.addEventListener('contextmenu', (e) => { if (e.target.closest('.tile') && matchMedia('(hover: none)').matches) e.preventDefault(); });

    $('#tileMenu').addEventListener('close', () => {
      const v = $('#tileMenu').returnValue;
      const name = ui.menuFor;
      if (!name) return;
      if (v === 'show') showItem(name, ui.tiles.get(name));
      else if (v === 'open') window.open('/media/' + encodeURIComponent(name), '_blank', 'noopener');
      else if (v === 'select') { if (!ui.selecting) setSelecting(true); toggleSelected(name); }
      else if (v === 'delete') deleteItems([name]);
    });

    $('#selectBtn').addEventListener('click', () => setSelecting(!ui.selecting));
    $('#selDone').addEventListener('click', () => setSelecting(false));
    $('#selAll').addEventListener('click', () => {
      for (const [name, el] of ui.tiles) if (!el.hidden) { ui.selected.add(name); el.classList.add('selected'); }
      renderSelection();
    });
    $('#selDelete').addEventListener('click', () => deleteItems(Array.from(ui.selected)));
  }

  async function command(action, value) {
    try {
      const r = await api.post('/api/command', { action, value });
      if (r.playback) { state.playback = r.playback; state.playbackAt = Date.now(); renderPlayback(); }
    } catch (e) { toast(e.message, 'error'); }
  }

  function bindControls() {
    for (const b of $$('[data-cmd]')) b.addEventListener('click', () => command(b.dataset.cmd));
    for (const b of [$('#playBtn'), $('#dockPlay')]) b.addEventListener('click', () => command('toggle'));
    $('#activeSwitch').addEventListener('change', (e) => command(e.target.checked ? 'resume' : 'pause'));
    $('#rotateBtn').addEventListener('click', () => setConfig({ rotation: ((state.config.rotation || 0) + 90) % 360, auto_rotation: false }));
    for (const p of $$('#intervalPresets [data-preset]')) p.addEventListener('click', () => setConfig({ frame_interval: Number(p.dataset.preset) }));
    $('#reloadDisplay').addEventListener('click', () => { command('reload_display'); toast('Display reloading'); });

    for (const b of $$('#powerSeg button')) {
      b.addEventListener('click', async () => {
        const on = b.dataset.power === 'on';
        try { const r = await api.post('/api/monitor', { power: on }); state.status = r.status; renderStatus(); } catch (e) { toast(e.message, 'error'); }
      });
    }
    let brTimer = 0;
    $('#brightness').addEventListener('input', (e) => {
      const v = Number(e.target.value);
      $('#brightnessOut').textContent = v + '%';
      clearTimeout(brTimer);
      brTimer = setTimeout(() => {
        api.post('/api/monitor', { brightness: v }).catch((err) => toast(err.message, 'error'));
      }, 200);
    });

    // Device name: inline in the top bar and in System settings.
    const nameBtn = $('#deviceName'), nameInput = $('#deviceNameInput');
    const commitName = (v) => {
      v = sanitizeName(v.trim());
      if (v && v !== state.config.device_name) setConfig({ device_name: v });
    };
    nameBtn.addEventListener('click', () => {
      nameInput.value = state.config.device_name || '';
      nameBtn.hidden = true;
      nameInput.hidden = false;
      nameInput.focus();
      nameInput.select();
    });
    nameInput.addEventListener('input', () => { nameInput.value = sanitizeName(nameInput.value); });
    nameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') nameInput.blur();
      if (e.key === 'Escape') { nameInput.value = state.config.device_name || ''; nameInput.blur(); }
    });
    nameInput.addEventListener('blur', () => { commitName(nameInput.value); nameInput.hidden = true; nameBtn.hidden = false; });
    const field = $('#deviceNameField');
    field.addEventListener('input', () => { field.value = sanitizeName(field.value); });
    field.addEventListener('change', () => commitName(field.value));

    // MQTT form.
    const f = $('#mqttForm');
    f.addEventListener('input', () => { f.dataset.dirty = '1'; });
    f.addEventListener('submit', (e) => {
      e.preventDefault();
      const values = {
        mqtt_broker: f.mqtt_broker.value.trim(), mqtt_port: Number(f.mqtt_port.value),
        mqtt_topic: f.mqtt_topic.value.trim(), mqtt_username: f.mqtt_username.value.trim(),
      };
      if (f.mqtt_password.value) values.mqtt_password = f.mqtt_password.value;
      else if (!values.mqtt_username) values.mqtt_password = '';
      delete f.dataset.dirty;
      setConfig(values);
      toast('Connecting to ' + values.mqtt_broker + '…');
    });

    $('#copyPlex').addEventListener('click', async () => {
      const text = $('#plexUrl').textContent;
      try { await navigator.clipboard.writeText(text); toast('Copied'); } catch (_) {
        const r = document.createRange(); r.selectNodeContents($('#plexUrl'));
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
        toast('Press Ctrl+C to copy');
      }
    });

    for (const b of $$('[data-system]')) {
      b.addEventListener('click', async () => {
        const a = b.dataset.system;
        const labels = { restart: ['Restart the app?', 'The display goes dark for a few seconds.', 'Restart'],
          reboot: ['Reboot the Raspberry Pi?', 'The canvas will be back in a minute or two.', 'Reboot'],
          shutdown: ['Shut down the Raspberry Pi?', 'You will need to power-cycle it to turn it back on.', 'Shut down'] };
        if (!(await confirmBox(...labels[a]))) return;
        try { await api.post('/api/system', { action: a }); toast(a === 'restart' ? 'Restarting…' : a === 'reboot' ? 'Rebooting…' : 'Shutting down…'); } catch (e) { toast(e.message, 'error'); }
      });
    }
  }

  // -------------------------------------------------------------- drawer

  function openDrawer(tab) {
    const d = $('#drawer');
    d.classList.add('open');
    d.setAttribute('aria-hidden', 'false');
    const scrim = $('#scrim');
    scrim.hidden = false;
    requestAnimationFrame(() => scrim.classList.add('show'));
    selectTab(tab || ui.tab);
    setTimeout(() => $('#drawerClose').focus(), 50);
  }

  function closeDrawer() {
    const d = $('#drawer');
    d.classList.remove('open');
    d.setAttribute('aria-hidden', 'true');
    const scrim = $('#scrim');
    scrim.classList.remove('show');
    setTimeout(() => { scrim.hidden = true; }, 250);
    $('#settingsBtn').focus();
  }

  function selectTab(tab) {
    ui.tab = tab;
    for (const b of $$('.tabs [data-tab]')) b.setAttribute('aria-selected', String(b.dataset.tab === tab));
    for (const p of $$('.panel')) p.hidden = p.dataset.panel !== tab;
    if (tab === 'system' || tab === 'integrations') refreshInfo();
  }

  async function refreshInfo() {
    try { state.info = await api.get('/api/info'); } catch (_) { return; }
    renderInfo();
  }

  function renderInfo() {
    const i = state.info;
    const s = state.status;
    if (!i) return;
    const ip = (i.ips && i.ips[0]) || location.hostname;
    $('#plexUrl').textContent = `http://${ip}:${i.port}/plex_hook`;
    const up = i.uptime_sec;
    const rows = [
      ['Version', i.version], ['Platform', i.platform], ['Address', (i.ips || []).map((x) => `${x}:${i.port}`).join(', ') || '–'],
      ['Uptime', fmtDuration(up)], ['App memory', fmtBytes(i.memory_bytes)],
    ];
    if (i.cpu_temp) rows.push(['CPU temperature', i.cpu_temp.toFixed(1) + ' °C']);
    rows.push(['Media', `${i.media_count} item${i.media_count === 1 ? '' : 's'}`]);
    if (s.screen) rows.push(['Screen', `${s.screen.width} × ${s.screen.height}`]);
    rows.push(['Monitor control', s.monitor && s.monitor.ddc ? 'DDC/CI · ' + (s.monitor.name || 'yes') : 'Not available']);
    rows.push(['Sensors', [s.sensors && s.sensors.light && 'light', s.sensors && s.sensors.accel && 'accelerometer'].filter(Boolean).join(', ') || 'None detected']);
    rows.push(['Video tools', s.ffmpeg ? 'ffmpeg' : 'ffmpeg not installed']);
    if (s.simulated) rows.push(['Mode', 'Simulation (hardware disabled)']);
    $('#facts').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${String(v).replace(/</g, '&lt;')}</dd>`).join('');
    $('#powerCtlDesc').textContent = i.power_control ? 'Reboot or power off the device' : 'Only available on a Raspberry Pi';
    for (const b of $$('[data-system="reboot"],[data-system="shutdown"]')) b.disabled = !i.power_control;
  }
  setInterval(() => { if ($('#drawer').classList.contains('open') && ui.tab === 'system') refreshInfo(); }, 10000);

  function bindDrawer() {
    $('#settingsBtn').addEventListener('click', () => openDrawer());
    $('#drawerClose').addEventListener('click', closeDrawer);
    $('#scrim').addEventListener('click', closeDrawer);
    addEventListener('keydown', (e) => { if (e.key === 'Escape' && $('#drawer').classList.contains('open')) closeDrawer(); });
    for (const b of $$('.tabs [data-tab]')) b.addEventListener('click', () => selectTab(b.dataset.tab));
  }

  // ------------------------------------------------------------- uploads

  const MEDIA_RE = /\.(jpe?g|png|gif|webp|bmp|mp4|mov|m4v|webm|mkv|avi)$/i;
  const jobs = [];
  let running = 0;

  function addFiles(list) {
    const files = Array.from(list || []);
    let skipped = 0;
    for (const file of files) {
      if (!/^(image|video)\//.test(file.type) && !MEDIA_RE.test(file.name)) { skipped++; continue; }
      const job = { file, name: file.name, progress: 0, state: 'queued', el: null };
      jobs.push(job);
      renderJob(job);
    }
    if (skipped) toast(`${skipped} file${skipped > 1 ? 's' : ''} skipped (not a photo or video)`, 'error');
    if (files.length - skipped > 0) {
      $('#uploads').hidden = false;
      $('#addDialog').close();
    }
    pump();
  }

  function pump() {
    while (running < 2) {
      const job = jobs.find((j) => j.state === 'queued');
      if (!job) break;
      running++;
      run(job).finally(() => { running--; pump(); updateUploadsTitle(); });
    }
    updateUploadsTitle();
  }

  function updateUploadsTitle() {
    const done = jobs.filter((j) => j.state === 'done' || j.state === 'error').length;
    const active = jobs.length - done;
    $('#uploadsTitle').textContent = active ? `Uploading ${done + 1} of ${jobs.length}` : `${jobs.filter((j) => j.state === 'done').length} added`;
    if (!active && jobs.length && jobs.every((j) => j.state === 'done')) {
      setTimeout(() => { if (jobs.every((j) => j.state === 'done')) clearUploads(); }, 4000);
    }
  }

  function clearUploads() {
    jobs.length = 0;
    $('#uploadList').replaceChildren();
    $('#uploads').hidden = true;
  }

  function renderJob(job) {
    if (!job.el) {
      job.el = document.createElement('li');
      job.el.innerHTML = `<span class="up-thumb">${svg(job.file.type.startsWith('video') ? 'film' : 'image', 'xs')}</span>
        <div style="min-width:0"><div class="up-name"></div><div class="up-bar"><i></i></div><div class="up-sub"></div></div>
        <span class="up-state"></span>`;
      $('.up-name', job.el).textContent = job.name;
      if (job.file.type.startsWith('image/') && job.file.size < 30e6) {
        const url = URL.createObjectURL(job.file);
        const t = $('.up-thumb', job.el);
        t.style.backgroundImage = `url("${url}")`;
        t.innerHTML = '';
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      }
      $('#uploadList').append(job.el);
    }
    job.el.className = job.state;
    $('.up-bar i', job.el).style.width = Math.round(job.progress * 100) + '%';
    const sub = { queued: 'Waiting…', preparing: 'Preparing…', uploading: `${Math.round(job.progress * 100)}%`, processing: 'Processing…', done: 'Added', error: job.error || 'Failed' }[job.state];
    $('.up-sub', job.el).textContent = sub;
    $('.up-state', job.el).innerHTML = job.state === 'done' ? svg('check', 'xs') : job.state === 'error' ? svg('x', 'xs') : '';
  }

  // Downscale large photos in the browser before uploading: phones do this
  // far faster than a Pi, and uploads shrink from megabytes to kilobytes.
  async function shrink(file) {
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return { blob: file, name: file.name };
    const sc = state.status.screen || {};
    const limit = Math.max(sc.width || 1920, sc.height || 1080);
    const url = URL.createObjectURL(file);
    try {
      const img = new Image();
      img.decoding = 'async';
      img.src = url;
      await img.decode();
      const w = img.naturalWidth, h = img.naturalHeight;
      if (Math.min(w, h) <= limit * 1.05 && Math.max(w, h) <= 8192) return { blob: file, name: file.name };
      const r = limit / Math.min(w, h);
      const tw = Math.round(w * r), th = Math.round(h * r);
      const canvas = document.createElement('canvas');
      canvas.width = tw;
      canvas.height = th;
      const ctx = canvas.getContext('2d');
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(img, 0, 0, tw, th); // honours EXIF orientation
      const type = file.type === 'image/png' ? 'image/png' : 'image/jpeg';
      const blob = await new Promise((res) => canvas.toBlob(res, type, 0.9));
      if (!blob || blob.size >= file.size) return { blob: file, name: file.name };
      return { blob, name: type === 'image/jpeg' ? file.name.replace(/\.(jpe?g|png|webp)$/i, '') + '.jpg' : file.name };
    } catch (_) {
      return { blob: file, name: file.name };
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  async function run(job) {
    job.state = 'preparing';
    renderJob(job);
    const { blob, name } = await shrink(job.file);
    job.state = 'uploading';
    renderJob(job);
    try {
      const res = await new Promise((resolve, reject) => {
        const fd = new FormData();
        fd.append('file', blob, name);
        const x = new XMLHttpRequest();
        x.open('POST', '/api/media');
        x.setRequestHeader('Accept', 'application/json');
        x.upload.onprogress = (e) => {
          if (!e.lengthComputable) return;
          job.progress = e.loaded / e.total;
          if (job.progress >= 1) job.state = 'processing';
          renderJob(job);
        };
        x.onload = () => {
          let d = {};
          try { d = JSON.parse(x.responseText); } catch (_) { /* ignore */ }
          if (x.status >= 200 && x.status < 300 && d.added && d.added.length) resolve(d);
          else reject(new Error((d.errors && d.errors[0] && d.errors[0].replace(/^.*?: /, '')) || d.error || `Upload failed (${x.status})`));
        };
        x.onerror = () => reject(new Error('Network error'));
        x.send(fd);
      });
      job.progress = 1;
      job.state = 'done';
      for (const it of res.added) upsert(it);
    } catch (e) {
      job.state = 'error';
      job.error = e.message;
    }
    renderJob(job);
  }

  function bindUploads() {
    const dlg = $('#addDialog');
    const input = $('#fileInput');
    for (const b of [$('#addBtn'), ...$$('[data-open-add]')]) b.addEventListener('click', () => { dlg.showModal(); });
    $('#pickFiles').addEventListener('click', () => input.click());
    input.addEventListener('change', () => { addFiles(input.files); input.value = ''; });
    $('#uploadsClose').addEventListener('click', clearUploads);

    const addUrl = async () => {
      const u = $('#urlInput').value.trim();
      if (!u) return;
      const btn = $('#urlAdd');
      btn.disabled = true;
      try {
        const r = await api.post('/api/media/url', { url: u });
        for (const it of r.added) upsert(it);
        $('#urlInput').value = '';
        dlg.close();
        toast('Added from the web');
      } catch (e) { toast(e.message, 'error'); }
      btn.disabled = false;
    };
    $('#urlAdd').addEventListener('click', addUrl);
    $('#urlInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); addUrl(); } });

    // Drag and drop anywhere, plus paste.
    let depth = 0;
    const hasFiles = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files');
    addEventListener('dragenter', (e) => { if (!hasFiles(e)) return; depth++; $('#dropOverlay').hidden = false; });
    addEventListener('dragleave', (e) => { if (!hasFiles(e)) return; if (--depth <= 0) { depth = 0; $('#dropOverlay').hidden = true; } });
    addEventListener('dragover', (e) => { if (hasFiles(e)) e.preventDefault(); });
    addEventListener('drop', (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth = 0;
      $('#dropOverlay').hidden = true;
      addFiles(e.dataTransfer.files);
    });
    addEventListener('paste', (e) => {
      if (e.target.closest && e.target.closest('input, textarea')) return;
      const files = Array.from(e.clipboardData ? e.clipboardData.files : []);
      if (files.length) addFiles(files);
    });
  }

  // -------------------------------------------------------------- events

  function applyState(s) {
    state.config = Object.assign(s.config || {}, pending);
    state.slide = s.slide || null;
    state.playback = s.playback || {};
    state.playbackAt = Date.now();
    state.status = s.status || {};
    state.power = s.power !== false;
    if (s.info) state.info = s.info;
    state.media = new Map((s.media || []).map((m) => [m.name, m]));
    renderGrid();
    renderConfig();
    renderSlide();
    renderPlayback();
    renderInfo();
  }

  function connect() {
    const es = new EventSource('/api/events');
    const on = (name, fn) => es.addEventListener(name, (e) => {
      let d;
      try { d = JSON.parse(e.data); } catch (_) { return; }
      fn(d);
    });
    on('hello', (s) => { $('#offline').hidden = true; applyState(s); });
    on('slide', (s) => { state.slide = s; renderSlide(); });
    on('playback', (p) => { state.playback = p; state.playbackAt = Date.now(); renderPlayback(); });
    on('config', (c) => { state.config = Object.assign(c, pending); renderConfig(); });
    on('status', (s) => { state.status = s; renderStatus(); if (state.info) renderInfo(); });
    on('power', (p) => { if (state.status.monitor) state.status.monitor.power = !!p.on; renderStatus(); });
    on('media.add', upsert);
    on('media.update', upsert);
    on('media.remove', (it) => removeItem(it.name));
    es.onerror = () => { $('#offline').hidden = false; };
  }

  bindSettings();
  bindControls();
  bindGrid();
  bindDrawer();
  bindUploads();
  connect();
})();

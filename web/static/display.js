// Digital Canvas display client.
//
// The server decides what is shown and when; this page renders slides as
// stacked layers and crossfades them with a CSS opacity transition, which
// the browser composites on the GPU. Videos use the hardware decoder.
(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const kiosk = params.get('kiosk') || '';
  const stage = document.getElementById('stage');
  const osd = document.getElementById('osd');
  const bootAt = Date.now();

  let cfg = { rotation: 0, scale_mode: 'fit', display_mode: 'fullscreen' };
  let playback = { active: true };
  let current = null;   // { slide, layer }
  let latest = null;    // newest slide received (rendered when the screen wakes)
  let loadToken = 0;
  let powerOn = true;
  const preloaded = [];

  // ---- server communication ----

  function post(path, body) {
    return fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Kiosk-Token': kiosk },
      body: JSON.stringify(body),
      keepalive: true,
    }).then(r => r.json().catch(() => ({}))).catch(() => ({}));
  }

  function report(type, seq, extra) {
    post('/api/display/report', Object.assign({ type, seq, kiosk }, extra || {}));
  }

  function hello() {
    const dpr = window.devicePixelRatio || 1;
    report('hello', 0, {
      width: Math.round(screen.width * dpr),
      height: Math.round(screen.height * dpr),
    });
  }

  // ---- rendering ----

  function withTimeout(p, ms) {
    return Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), ms))]);
  }

  function imageReady(img) {
    if (img.decode) return img.decode();
    return new Promise((res, rej) => { img.onload = res; img.onerror = rej; });
  }

  function layerClass() {
    return 'layer r' + (cfg.rotation || 0) + (cfg.scale_mode === 'fill' ? ' fill' : '');
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }

  function buildIdle(slide, layer) {
    layer.classList.add('idle');
    const bg = new Image();
    bg.className = 'bg';
    bg.alt = '';
    bg.src = slide.bg || '/assets/background.jpg';
    layer.append(bg, el('div', 'idle-veil'));
    const card = el('div', 'idle-card');
    card.append(el('div', 'idle-name', slide.title || 'Digital Canvas'));
    card.append(el('div', 'idle-hint', 'Your canvas is empty. Add photos and videos from any device on your network:'));
    const urls = el('div');
    for (const u of (slide.urls || []).slice(0, 2)) urls.append(el('span', 'idle-url', u.replace(/^https?:\/\//, '')));
    card.append(urls);
    layer.append(card);
    return imageReady(bg).catch(() => {});
  }

  function build(slide) {
    const layer = el('div', layerClass());
    if (slide.kind === 'idle') return { layer, ready: buildIdle(slide, layer) };

    let bgReady = Promise.resolve();
    if (slide.bg && cfg.scale_mode !== 'fill') {
      const bg = new Image();
      bg.className = 'bg';
      bg.alt = '';
      bg.decoding = 'async';
      bg.src = slide.bg;
      layer.append(bg);
      bgReady = imageReady(bg).catch(() => {});
    }

    let ready;
    if (slide.kind === 'video') {
      const v = document.createElement('video');
      v.className = 'fg';
      v.muted = true;
      v.defaultMuted = true;
      v.playsInline = true;
      v.preload = 'auto';
      v.setAttribute('muted', '');
      v.setAttribute('playsinline', '');
      v.disablePictureInPicture = true;
      v.loop = !playback.active;
      ready = new Promise((res, rej) => {
        v.addEventListener('canplay', res, { once: true });
        v.addEventListener('error', () => rej(new Error('video error ' + (v.error ? v.error.code : ''))), { once: true });
      });
      v.addEventListener('ended', () => {
        if (current && current.slide.seq === slide.seq) report('ended', slide.seq);
      });
      v.src = slide.src;
      layer.append(v);
    } else {
      const img = new Image();
      img.className = 'fg';
      img.alt = '';
      img.decoding = 'async';
      // Animated GIFs restart only when loaded from a fresh URL.
      img.src = slide.kind === 'gif' ? slide.src + (slide.src.includes('?') ? '&' : '?') + 'play=' + slide.seq : slide.src;
      layer.append(img);
      ready = imageReady(img);
    }
    return { layer, ready: Promise.all([ready, bgReady]) };
  }

  function dispose(layer) {
    for (const v of layer.querySelectorAll('video')) {
      v.pause();
      v.removeAttribute('src');
      v.load(); // releases the hardware decoder
    }
    layer.remove();
  }

  // show renders a slide on top of the current one and fades it in.
  async function show(slide, opts) {
    opts = opts || {};
    latest = slide;
    if (!powerOn) return;
    const token = ++loadToken;
    const { layer, ready } = build(slide);
    let failed = null;
    try {
      await withTimeout(ready, slide.kind === 'video' ? 20000 : 30000);
    } catch (e) {
      failed = e;
    }
    if (token !== loadToken) { dispose(layer); return; } // superseded meanwhile
    if (failed) {
      dispose(layer);
      report('error', slide.seq, { error: 'could not load ' + slide.src + ': ' + failed.message });
      return;
    }
    stage.append(layer);
    const v = layer.querySelector('video');
    if (v) {
      v.loop = !playback.active;
      const p = v.play();
      if (p) p.catch(() => {});
    }
    let dur = opts.duration !== undefined ? opts.duration : Math.max(0, Number(slide.transition) || 0);
    if (!current) dur = Math.min(dur || 1, 1.5); // first slide fades in from black
    layer.getBoundingClientRect(); // flush styles so the transition runs
    layer.style.transition = dur > 0 ? 'opacity ' + dur + 's linear' : 'none';
    layer.style.opacity = '1';
    current = { slide, layer };
    report('ready', slide.seq);
    const settle = () => {
      if (!layer.isConnected) return;
      let prev = layer.previousElementSibling;
      while (prev) {
        const p = prev.previousElementSibling;
        dispose(prev);
        prev = p;
      }
      maybeReload();
    };
    if (dur > 0) setTimeout(settle, dur * 1000 + 120); else settle();
  }

  function rerender() {
    if (current) show(current.slide, { duration: 0.6 });
  }

  function applyConfig(next) {
    const layoutChanged = next.rotation !== cfg.rotation || next.scale_mode !== cfg.scale_mode;
    const scaleChanged = next.scale_mode !== cfg.scale_mode;
    const rotChanged = next.rotation !== cfg.rotation;
    cfg = next;
    if (layoutChanged && current) {
      rerender();
      if (scaleChanged) flash(cfg.scale_mode === 'fill' ? 'Fill screen' : 'Fit to screen');
      else if (rotChanged) flash('Rotation ' + cfg.rotation + '°');
    }
  }

  function applyPlayback() {
    if (!current) return;
    const v = current.layer.querySelector('video');
    if (v) v.loop = !playback.active;
  }

  function setPower(on) {
    if (on === powerOn) return;
    powerOn = on;
    document.body.classList.toggle('off', !on);
    for (const v of stage.querySelectorAll('video')) {
      if (on) { const p = v.play(); if (p) p.catch(() => {}); } else v.pause();
    }
    if (on && latest && (!current || latest.seq !== current.slide.seq)) show(latest, { duration: 0.8 });
    if (!on) setTimeout(maybeReload, 2000);
  }

  function preload(p) {
    if (!p || !p.src || p.kind === 'video') return;
    for (const src of [p.src, p.bg]) {
      if (!src) continue;
      const img = new Image();
      img.decoding = 'async';
      img.src = src;
      preloaded.push(img);
    }
    while (preloaded.length > 4) preloaded.shift();
  }

  // Long-running browsers slowly accumulate memory. Reload (invisibly) while
  // the screen is off, or after a day at the next slide change.
  function maybeReload() {
    const age = Date.now() - bootAt;
    if ((!powerOn && age > 3600e3) || age > 24 * 3600e3) location.reload();
  }

  // ---- on screen display and keyboard ----

  let osdTimer;
  function flash(text) {
    osd.textContent = text;
    osd.classList.add('show');
    clearTimeout(osdTimer);
    osdTimer = setTimeout(() => osd.classList.remove('show'), 1600);
  }

  async function command(action, label) {
    const r = await post('/api/command', { action });
    if (label && r.success !== false) flash(label);
    return r;
  }

  async function toggleFullscreen() {
    const r = await command('toggle_fullscreen');
    if (r.handled) return;
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch (_) { /* not allowed */ }
  }

  async function quit() {
    const r = await command('quit');
    if (r.handled) { flash('Closing…'); return; }
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }

  addEventListener('keydown', (e) => {
    if (e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
    switch (e.key) {
      case 'ArrowRight': command('next', 'Next'); break;
      case 'ArrowLeft': command('previous', 'Previous'); break;
      case 'p': case 'P': command('pause', 'Paused'); break;
      case 'r': case 'R': command('resume', 'Playing'); break;
      case ' ': command('toggle', playback.active ? 'Paused' : 'Playing'); break;
      case 's': case 'S': command('toggle_scale'); break;
      case 'a': case 'A': command('rotate'); break;
      case 'f': case 'F': toggleFullscreen(); break;
      case 'q': case 'Q': case 'Escape': quit(); break;
      default: return;
    }
    e.preventDefault();
  });

  let cursorTimer;
  addEventListener('mousemove', () => {
    document.body.classList.add('cursor');
    clearTimeout(cursorTimer);
    cursorTimer = setTimeout(() => document.body.classList.remove('cursor'), 2500);
  }, { passive: true });

  let resizeTimer;
  addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(hello, 500);
  });

  // ---- event stream ----

  function connect() {
    const url = '/api/events?role=display' + (kiosk ? '&kiosk=' + encodeURIComponent(kiosk) : '');
    const es = new EventSource(url);
    const on = (name, fn) => es.addEventListener(name, (e) => {
      let data = null;
      try { data = JSON.parse(e.data); } catch (_) { return; }
      fn(data);
    });
    on('hello', (s) => {
      cfg = s.config || cfg;
      playback = s.playback || playback;
      setPower(s.power !== false);
      if (s.slide && (!current || current.slide.seq !== s.slide.seq || current.slide.src !== s.slide.src)) show(s.slide);
      else applyPlayback();
      hello();
    });
    on('slide', show);
    on('playback', (p) => { playback = p; applyPlayback(); });
    on('config', applyConfig);
    on('power', (p) => setPower(!!p.on));
    on('preload', preload);
    on('reload', () => location.reload());
    on('osd', (o) => flash(o.text || ''));
  }

  connect();
})();

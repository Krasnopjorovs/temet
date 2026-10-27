/* Небо страницы: туманность и звёзды на двух слоях (#skyA снизу, #skyB сверху), которые плавно сменяют друг друга.
   Цвета — из доктрины (/api/doctrine → palette, sign_order, sign_elements, element_labels):
     NeoSky.init(doctrine)   — ночное небо по умолчанию и цвета знаков/планет для круга карты (CSS-переменные);
     NeoSky.fromChart(chart) — небо этой карты: облака цветов знаков тел из palette.anchors (Солнце, Луна, Асцендент),
                               само небо и панели слегка окрашены цветом первого знака (palette.tint),
                               яркость облака — по месту тела в anchors и доле его стихии в карте,
                               акцент страницы — по palette.accent_from (цвет знака Солнца или ведущей планеты).
                               Возвращает легенду { anchors: [{body, sign, element, elementLabel, color}], accent, lead }. */
(function (root) {
  let P = null, SE = {}, EL = {}, layers = null, lastW = 0, lastH = 0;
  const signTones = sign => (P.signs && P.signs[sign]) || P.elements[SE[sign]] || [P.night.accent, P.night.dust];
  const css = (k, v) => document.documentElement.style.setProperty(k, v);

  const hex = h => { const n = parseInt(h.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; };
  const rgba = (h, a) => `rgba(${hex(h).join(",")},${Math.max(0, Math.min(1, a)).toFixed(3)})`;
  const mix = (a, b, t) => "#" + hex(a).map((v, i) => Math.round(v + (hex(b)[i] - v) * t).toString(16).padStart(2, "0")).join("");
  const lum = h => {
    const c = hex(h).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const contrast = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  // тот же оттенок, осветлённый настолько, чтобы читаться текстом на тёмной панели (WCAG 4.5:1)
  const readable = (c, bg) => { let t = 0; while (contrast(mix(c, "#ffffff", t), bg) < 4.5 && t < 1) t += 0.04; return mix(c, "#ffffff", Math.min(t, 1)); };

  function rng(seed) {            // mulberry32: одно и то же зерно — одно и то же небо
    let a = seed >>> 0;
    return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1);
                   t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }
  const gauss = R => (R() + R() + R() + R() - 2) / 2;

  // места облаков на небе (доли ширины и высоты окна) — по порядку тел в palette.anchors
  const SLOTS = [{ x: 0.06, y: 0.12, size: 0.30, spread: 0.12 },
                 { x: 0.95, y: 0.55, size: 0.26, spread: 0.10 },
                 { x: 0.22, y: 0.98, size: 0.28, spread: 0.12 },
                 { x: 0.82, y: 0.04, size: 0.18, spread: 0.08 }];

  function draw(layer) {
    const sc = layer.scene, cv = layer.el.querySelector("canvas");
    if (!sc || !cv) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const W = window.innerWidth, H = Math.max(window.innerHeight, (window.screen && screen.height) || 0);
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    cv.style.width = W + "px"; cv.style.height = H + "px";
    const g = cv.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const base = g.createLinearGradient(0, 0, W * 0.3, H);
    base.addColorStop(0, sc.deep); base.addColorStop(0.55, sc.mid || sc.sky); base.addColorStop(1, sc.sky);
    g.globalCompositeOperation = "source-over";
    g.fillStyle = base; g.fillRect(0, 0, W, H);

    // туманность: у каждого облака мягкая основа и комки помельче, два тона стихии вперемешку;
    // пятна вытянуты и повёрнуты — облако не складывается в ровный круг
    const R = rng(sc.seed), M = Math.max(W, H);
    const blob = (x, y, r, col, a, stretch, rot) => {
      g.save(); g.translate(x, y); g.rotate(rot); g.scale(stretch, 1);
      const grd = g.createRadialGradient(0, 0, 0, 0, 0, r);
      grd.addColorStop(0, rgba(col, a)); grd.addColorStop(0.4, rgba(col, a * 0.5)); grd.addColorStop(1, rgba(col, 0));
      g.fillStyle = grd; g.fillRect(-r, -r, 2 * r, 2 * r); g.restore();
    };
    // светлые цвета (серебро, жемчуг) в режиме screen быстро превращаются в белый туман — их облака тише
    const soft = (col, a) => a * (1 - 0.8 * Math.max(0, lum(col) - 0.45));
    g.globalCompositeOperation = "screen";
    sc.clouds.forEach(cl => {
      const tilt = R() * Math.PI;
      for (let k = 0; k < 7; k++)
        blob((cl.x + gauss(R) * cl.spread * 0.6) * W, (cl.y + gauss(R) * cl.spread * 0.6) * H, M * cl.size * (0.6 + R() * 0.5),
             cl.colors[k % cl.colors.length], soft(cl.colors[k % cl.colors.length], cl.a) * (0.35 + R() * 0.3), 1.2 + R() * 0.8, tilt + gauss(R) * 0.5);
      for (let k = 0; k < 26; k++)
        blob((cl.x + gauss(R) * cl.spread * 1.6) * W, (cl.y + gauss(R) * cl.spread * 1.6) * H, M * cl.size * (0.08 + R() * 0.25),
             cl.colors[(k + 1) % cl.colors.length], soft(cl.colors[(k + 1) % cl.colors.length], cl.a) * (0.5 + R() * 0.8), 1 + R() * 1.6, tilt + gauss(R) * 0.8);
    });
    // тёмные пылевые прожилки поверх свечения
    g.globalCompositeOperation = "source-over";
    sc.clouds.forEach(cl => {
      for (let k = 0; k < 5; k++)
        blob((cl.x + gauss(R) * cl.spread * 1.2) * W, (cl.y + gauss(R) * cl.spread * 1.2) * H, M * cl.size * (0.12 + R() * 0.25),
             sc.deep, 0.45 + R() * 0.25, 2 + R() * 2.5, R() * Math.PI);
    });

    // звёзды: места постоянные (своё зерно), меняется только оттенок части звёзд
    const S = rng(20240917), n = Math.min(1800, Math.round(W * H / 1500));
    for (let k = 0; k < n; k++) {
      const x = S() * W, y = S() * H, m = S(), tintPick = S(), tw = S();
      const size = m < 0.85 ? 0.35 + m * 0.6 : m < 0.99 ? 0.9 + (m - 0.85) * 3.5 : 1.5 + (m - 0.99) * 60;
      const col = tintPick < 0.16 && sc.tints.length ? mix(sc.tints[k % sc.tints.length], sc.star, 0.35) : sc.star;
      const alpha = 0.35 + tw * 0.6;
      if (size > 1.4) {          // яркие звёзды — с небольшим ореолом
        const grd = g.createRadialGradient(x, y, 0, x, y, size * 2.6);
        grd.addColorStop(0, rgba(col, 0.35 * alpha)); grd.addColorStop(1, rgba(col, 0));
        g.fillStyle = grd; g.fillRect(x - size * 2.6, y - size * 2.6, size * 5.2, size * 5.2);
      }
      g.fillStyle = rgba(col, alpha);
      g.beginPath(); g.arc(x, y, size / 2, 0, Math.PI * 2); g.fill();
    }
    layer.drawn = [W, H];
  }

  function show(scene) {
    if (!layers) return;
    const [A, B] = layers;            // B лежит поверх A: проявляется он, или он гаснет и открывает A
    if (B.on) { A.scene = scene; draw(A); B.el.classList.add("off"); B.on = false; }
    else { B.scene = scene; draw(B); B.el.classList.remove("off"); B.on = true; }
  }

  function setAccent(color, tint = null, t = 0) {
    const panel = mix(P.night.sky, "#ffffff", 0.08);
    const card = tint ? mix(P.night.sky, tint, t * 0.6) : P.night.sky;   // панели чуть окрашены тем же цветом, что и небо
    css("--card", `rgba(${hex(card).join(",")},.62)`);
    css("--line", tint ? rgba(mix("#ECEAFB", tint, 0.35), 0.16) : "rgba(236,234,251,.14)");
    css("--acc", color);
    css("--acc-text", readable(color, panel));
    css("--on-acc", contrast(color, P.night.deep) >= contrast(color, "#ffffff") ? P.night.deep : "#ffffff");
  }

  function nightScene() {
    const n = P.night;
    return { seed: 7, deep: n.deep, sky: n.sky, star: n.star, tints: [n.accent, n.dust],
             clouds: [{ ...SLOTS[0], colors: [n.accent, n.dust], a: 0.09 },
                      { ...SLOTS[1], colors: [P.elements.WATER ? P.elements.WATER[0] : n.dust, n.accent], a: 0.08 },
                      { ...SLOTS[2], colors: [n.dust, n.accent], a: 0.06 }] };
  }

  function init(doctrine) {
    P = doctrine && doctrine.palette;
    if (!P || !P.night) return;
    SE = doctrine.sign_elements || {}; EL = doctrine.element_labels || {};
    const panel = mix(P.night.sky, "#ffffff", 0.08);
    for (const [el, tones] of Object.entries(P.elements || {})) {
      css(`--el-${el.toLowerCase()}`, tones[0]);
      css(`--el-${el.toLowerCase()}-text`, readable(tones[0], panel));
    }
    for (const [b, c] of Object.entries(P.bodies || {})) css(`--b-${b}`, c);
    (doctrine.sign_order || []).forEach((sign, i) => {      // кольцо знаков в круге — цветами знаков
      const c = signTones(sign)[0];
      css(`--sign-${i}`, c); css(`--sign-${i}-text`, readable(c, panel));
    });
    css("--partner", P.night.partner || P.night.accent);   // второй человек — свой цвет, не совпадающий с цветами аспектов
    layers = ["skyA", "skyB"].map(id => ({ el: document.getElementById(id), on: id === "skyA" }))
      .filter(l => l.el);
    if (layers.length !== 2) { layers = null; return; }
    layers[0].scene = nightScene(); draw(layers[0]);
    setAccent(P.night.accent);
    lastW = window.innerWidth; lastH = window.innerHeight;
    let t;
    window.addEventListener("resize", () => {
      clearTimeout(t);
      t = setTimeout(() => {           // мобильная адресная строка меняет только высоту — перерисовка не нужна
        if (window.innerWidth === lastW && window.innerHeight <= (layers[0].drawn || [0, 0])[1]) return;
        lastW = window.innerWidth; lastH = window.innerHeight;
        layers.forEach(l => l.scene && draw(l));
      }, 200);
    });
  }

  function fromChart(chart) {
    if (!P || !layers) return null;
    const share = (chart.balance && chart.balance.elements) || {};
    const seenSign = {};    // два тела в одном знаке получают разные его тона
    const anchors = (P.anchors || []).filter(b => chart.bodies[b] && chart.bodies[b].shown && chart.bodies[b].sign)
      .map(b => {
        const sign = chart.bodies[b].sign, el = SE[sign], tones = signTones(sign);
        const shift = (seenSign[sign] = (seenSign[sign] ?? -1) + 1) % tones.length;
        const colors = tones.slice(shift).concat(tones.slice(0, shift));
        return { body: b, sign, element: el, elementLabel: EL[el] || el, color: colors[0], colors };
      });
    const order = (chart.dominance && chart.dominance.order) || [];
    const leadBody = order.find(b => P.bodies && P.bodies[b]);
    const lead = leadBody ? { body: leadBody, color: P.bodies[leadBody] } : null;
    const accentColor = P.accent_from === "dominant" && lead ? lead.color : anchors.length ? anchors[0].color : P.night.accent;
    const n = P.night, first = anchors.length ? anchors[0].color : null, t = first ? +(P.tint ?? 0.2) : 0;
    const lon = b => Math.round(((chart.bodies[b] || {}).lon || 0) * 100);
    const RANK = [0.2, 0.15, 0.12];     // первое тело в anchors — самое яркое облако
    const scene = {
      seed: (lon("SUN") * 31 + lon("MOON") * 7 + 1) >>> 0, star: n.star,
      deep: first ? mix(n.deep, first, t * 0.25) : n.deep,
      mid: first ? mix(n.sky, first, t * 0.6) : n.sky,
      sky: first ? mix(n.sky, first, t) : n.sky,
      tints: anchors.map(a => a.color).concat(lead ? [lead.color] : []),
      clouds: anchors.map((a, i) => ({ ...SLOTS[i % SLOTS.length], colors: a.colors,
                                         a: (RANK[i] ?? 0.1) * (0.8 + 0.6 * Math.min(1, (share[a.element] || 0) * 2)) }))
        .concat(lead ? [{ ...SLOTS[3], colors: [lead.color], a: 0.1 }] : []),
    };
    show(scene);
    setAccent(accentColor, first, t);
    return { anchors, accent: { body: P.accent_from === "dominant" && lead ? lead.body : null, color: accentColor }, lead };
  }

  root.NeoSky = { init, fromChart };
})(typeof window !== "undefined" ? window : globalThis);

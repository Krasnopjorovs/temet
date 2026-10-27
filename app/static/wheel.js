/* Круг натальной карты (и двойной круг для пары) в SVG. Без зависимостей.
   natalWheel({ chart, outer, labels, aspects, strong }) -> строка <svg>
   chart / outer: { bodies: {CODE: {lon, shown, retro?, house?}}, cusps?: [12], time_known }
   aspects: [{ a, b, aspect, strength, orb? }] — для пары: a — тело внутренней карты, b — внешней.

   Читаемость: у каждой планеты — засечка на точном градусе у кольца знаков, подпись с градусом рядом
   (скопления разносятся в два ряда), точка на круге аспектов на том же градусе и тонкая направляющая между ними.
   Наведение на планету (или касание) подсвечивает её аспекты; подсказка — знак, градус, дом и аспекты. */
(function (root) {
  // слова — со страницы (window.t из i18n.js), имена знаков и планет — из подписей доктрины (labels)
  const T = (k, v) => (root.t ? root.t(k, v) : k);
  const abbr = (s, max, keep) => s.length > max ? s.slice(0, keep) + "." : s;   // длинное имя знака не влезает в кольцо
  // огонь, земля, воздух, вода — по кругу знаков; цвета задаёт страница (CSS-переменные из палитры доктрины)
  const ELEMENT = ["fire", "earth", "air", "water"].map(e => `var(--el-${e}, var(--mute))`);
  const ELEMENT_TEXT = ["fire", "earth", "air", "water"].map(e => `var(--el-${e}-text, var(--el-${e}, var(--fg)))`);
  const HARM = { TRI: 1, SXT: 1 }, TENSE = { SQR: 1, OPP: 1 };
  const BLUE = "var(--harm, #5AA8FF)", RED = "var(--tense, #FF6B6B)";
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // раздвинуть подписи по кругу, сохранив порядок; разрез — в самом большом промежутке
  function spread(lons, gap) {
    const n = lons.length;
    if (n < 2) return lons.slice();
    const idx = lons.map((l, i) => i).sort((i, j) => lons[i] - lons[j]);
    let cut = 0, best = -1;
    for (let k = 0; k < n; k++) {
      const a = lons[idx[k]], b = lons[idx[(k + 1) % n]];
      const g = ((b - a) % 360 + 360) % 360 || 360;
      if (g > best) { best = g; cut = (k + 1) % n; }
    }
    const order = idx.slice(cut).concat(idx.slice(0, cut));
    const orig = [];
    order.forEach((i, k) => { let v = lons[i]; if (k > 0 && v < orig[k - 1]) v += 360; orig.push(v); });
    const p = orig.slice();
    for (let it = 0; it < 100; it++) {
      for (let i = 1; i < n; i++) if (p[i] < p[i - 1] + gap) p[i] = p[i - 1] + gap;
      let i = 0;
      while (i < n) {
        let j = i;
        while (j + 1 < n && p[j + 1] - p[j] <= gap + 1e-9) j++;
        let so = 0, sp = 0;
        for (let k = i; k <= j; k++) { so += orig[k]; sp += p[k]; }
        const sh = (so - sp) / (j - i + 1);
        for (let k = i; k <= j; k++) p[k] += sh;
        i = j + 1;
      }
    }
    const out = new Array(n);
    order.forEach((i, k) => { out[i] = p[k]; });
    return out;
  }

  // два ряда подписей: соседи ближе minDeg уходят во второй ряд по очереди
  function rows(pos, minDeg) {
    const n = pos.length, row = new Array(n).fill(0);
    const order = pos.map((p, i) => i).sort((i, j) => pos[i] - pos[j]);
    for (let k = 1; k < n; k++) {
      const i = order[k], prev = order[k - 1];
      if (pos[i] - pos[prev] < minDeg && row[prev] === 0) row[i] = 1;
    }
    if (n > 2) {      // замыкание круга
      const first = order[0], last = order[n - 1];
      if (pos[first] + 360 - pos[last] < minDeg && row[first] === 0 && row[last] === 0) row[last] = 1;
    }
    return row;
  }

  function natalWheel({ chart, outer = null, labels = {}, aspects = [], strong = [],
                        outerLegend = T("wh_outer_legend"), outerTip = T("wh_outer_tip") }) {
    const bi = !!outer;
    const W = 720, cx = W / 2;
    const R = bi
      ? { zo: 262, zi: 230, rows: [208, 184, 160], hn: 220, as: 134, ob: 280, max: 318 }
      : { zo: 312, zi: 276, rows: [238, 210, 182], hn: 265, as: 152, max: 330 };
    const cy = R.max + 14;
    const known = chart.time_known && chart.cusps;
    const asc = known ? chart.bodies.ASC.lon : 0;
    const ang = lon => (180 + (lon - asc)) * Math.PI / 180;
    const pt = (lon, r) => [cx + r * Math.cos(ang(lon)), cy - r * Math.sin(ang(lon))];
    const f = v => v.toFixed(1);
    const name = c => (labels.bodies && labels.bodies[c]) || c;
    const short = c => { const n = name(c), m = n.match(/\(([^)]+)\)/); return m ? m[1] : n; };   // «Северный узел (Раху)» → «Раху»
    const order = labels.sign_order || [];
    const signName = i => (labels.signs && labels.signs[order[i]]) || order[i] || String(i + 1);
    const ASC = T("wh_asc");
    const aspName = c => ((labels.aspects && labels.aspects[c]) || c).toLowerCase();
    const deg = lon => { const d = ((lon % 30) + 30) % 30; return `${Math.floor(d)}°${String(Math.floor((d % 1) * 60)).padStart(2, "0")}′`; };
    const H = cy + R.max + 20 + (bi ? 66 : 44) + 14;     // + место под последнюю строку подписи
    const o = [];
    o.push(`<svg class="wheel" viewBox="0 0 ${W} ${H}" width="100%" role="img" font-family="inherit" style="max-width:${W}px;display:block;margin:0 auto">`);
    const line = (x1, y1, x2, y2, stroke, w, extra = "") =>
      o.push(`<line x1="${f(x1)}" y1="${f(y1)}" x2="${f(x2)}" y2="${f(y2)}" stroke="${stroke}" stroke-width="${w}"${extra}/>`);
    const text = (x, y, t, size = 12, color = "var(--fg)", weight = 400, extra = "") =>
      o.push(`<text x="${f(x)}" y="${f(y)}" font-size="${size}" font-weight="${weight}" fill="${color}" text-anchor="middle" dominant-baseline="central"${extra}>${esc(t)}</text>`);
    const circle = (r, w = 0.8, stroke = "var(--line)") => o.push(`<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${stroke}" stroke-width="${w}"/>`);
    const sector = (l0, l1, r0, r1, fill, op) => {
      const [a, b] = pt(l0, r1), [c, d] = pt(l1, r1), [e, g] = pt(l1, r0), [h, k] = pt(l0, r0);
      o.push(`<path d="M${f(a)} ${f(b)} A${r1} ${r1} 0 0 0 ${f(c)} ${f(d)} L${f(e)} ${f(g)} A${r0} ${r0} 0 0 1 ${f(h)} ${f(k)} Z" fill="${fill}" fill-opacity="${op}"/>`);
    };

    // кольцо знаков: оттенок стихии, деления по 5° и 10°
    for (let i = 0; i < 12; i++) {
      sector(i * 30, i * 30 + 30, R.zi, R.zo, `var(--sign-${i}, ${ELEMENT[i % 4]})`, 0.16);
      const [x1, y1] = pt(i * 30, R.zi), [x2, y2] = pt(i * 30, R.zo);
      line(x1, y1, x2, y2, "var(--line)", 0.8);
      const [tx, ty] = pt(i * 30 + 15, (R.zo + R.zi) / 2);
      text(tx, ty, bi ? abbr(signName(i), 6, 5) : abbr(signName(i), 9, 6), bi ? 11.5 : 12.5, `var(--sign-${i}-text, ${ELEMENT_TEXT[i % 4]})`, 500);
      for (let d = 5; d < 30; d += 5) {
        const [a, b] = pt(i * 30 + d, R.zi), [c, e] = pt(i * 30 + d, R.zi + (d % 10 ? 4 : 7));
        line(a, b, c, e, "var(--mute)", 0.6, ' opacity="0.6"');
      }
    }
    circle(R.zo); circle(R.zi);

    const boxes = [];   // занятые места: номера домов и уже поставленные подписи
    // дома: куспиды от круга аспектов до кольца знаков, номера — в полосе у круга аспектов; углы — жирно
    if (known) {
      chart.cusps.forEach((cu, i) => {
        const angle = i % 3 === 0;
        const [x1, y1] = pt(cu, R.as), [x2, y2] = pt(cu, angle ? R.zo + 8 : R.zi);
        line(x1, y1, x2, y2, angle ? "var(--fg)" : "var(--line)", angle ? 1.6 : 0.8, angle ? "" : ' stroke-dasharray="2 3"');
        const nx = chart.cusps[(i + 1) % 12];
        const mid = cu + ((nx - cu) % 360 + 360) % 360 / 2;
        const [hx, hy] = pt(mid, R.hn);
        text(hx, hy, String(i + 1), 10, "var(--mute)");
        boxes.push([hx - 7, hy - 7, hx + 7, hy + 7]);
      });
      if (!bi) {
        for (const [lon, lab, main] of [[chart.cusps[0], ASC, 1], [chart.cusps[9], "MC", 1], [chart.cusps[6], "Dsc", 0], [chart.cusps[3], "IC", 0]]) {
          const [x, y] = pt(lon, R.zo + 20);
          text(x, y, lab, main ? 13 : 11, main ? "var(--fg)" : "var(--mute)", 600);
        }
      }
    }
    circle(R.as, 0.6);

    // аспекты — до планет, чтобы подписи были поверх линий
    const aspBy = {};
    const drawAspects = () => {
      for (const a of aspects) {
        if (["ASC", "MC"].includes(a.a) || ["ASC", "MC"].includes(a.b)) continue;   // у углов нет точки на круге
        const A = chart.bodies[a.a], B = (bi ? outer : chart).bodies[a.b];
        if (!A || !B || !A.shown || !B.shown) continue;
        const col = HARM[a.aspect] ? BLUE : TENSE[a.aspect] ? RED : (bi ? "var(--partner, var(--acc))" : null);
        if (!col) continue;
        const [x1, y1] = pt(A.lon, R.as), [x2, y2] = pt(B.lon, R.as);
        const dash = (a.aspect === "SXT" || a.aspect === "OPP") ? ' stroke-dasharray="5 3"' : "";
        const kb = bi ? "o:" + a.b : a.b;
        line(x1, y1, x2, y2, col, (0.7 + 1.3 * (a.strength ?? 1)).toFixed(2),
             ` class="asp" data-a="${a.a}" data-b="${kb}" opacity="0.8"${dash}`);
      }
    };
    for (const a of aspects) {            // для подсказок: аспекты каждой планеты
      const kb = bi ? "o:" + a.b : a.b;
      (aspBy[a.a] = aspBy[a.a] || []).push(`${aspName(a.aspect)} — ${bi ? outerTip.toLowerCase() + ": " : ""}${short(a.b)}`);
      (aspBy[kb] = aspBy[kb] || []).push(`${aspName(a.aspect)} — ${short(a.a)}`);
    }
    drawAspects();

    // подпись ставится как можно ближе к своему градусу: перебор сдвигов по кругу и рядов, без наложений
    const overlap = (a, b) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
    function place(lon, w, h, radii) {
      let best = null;
      radii.forEach((r, ri) => {
        for (let d = 0; d <= 40; d += 0.5) {
          for (const sgn of d ? [1, -1] : [1]) {
            const cost = d + ri * 3;
            if (best && cost >= best.cost) continue;
            const [x, y] = pt(lon + sgn * d, r);
            const box = [x - w / 2 - 2, y - h / 2 - 1, x + w / 2 + 2, y + h / 2 + 1];
            if (!boxes.some(b => overlap(b, box))) best = { cost, lon: lon + sgn * d, r, box };
          }
        }
      });
      best = best || { lon, r: radii[0], box: null };
      if (best.box) boxes.push(best.box);
      return best;
    }

    function planets(c, isOuter) {
      const codes = Object.keys(c.bodies).filter(k => c.bodies[k].shown && k !== "ASC" && k !== "MC");
      const lons = codes.map(k => c.bodies[k].lon);
      // по порядку градусов, начиная после самого большого пустого промежутка — скопления раскладываются по порядку
      const order = codes.map((k, i) => i).sort((i, j) => lons[i] - lons[j]);
      let cut = 0, gapMax = -1;
      order.forEach((i, k) => { const nx = lons[order[(k + 1) % order.length]]; const g = ((nx - lons[i]) % 360 + 360) % 360 || 360;
                                if (g > gapMax) { gapMax = g; cut = (k + 1) % order.length; } });
      const seq = order.slice(cut).concat(order.slice(0, cut));
      const spot = new Array(codes.length);
      seq.forEach(i => {
        const k = codes[i], w = Math.max(short(k).length * 6.9 + 4, 44);
        spot[i] = place(lons[i], w, isOuter ? 15 : 26, isOuter ? [R.ob + 14, R.ob + 36] : R.rows);
      });
      const color = isOuter ? "var(--partner, var(--acc))" : "var(--fg)";
      codes.forEach((k, i) => {
        const b = c.bodies[k], lon = b.lon, id = isOuter ? "o:" + k : k;
        const tipSign = signName(Math.floor((((lon % 360) + 360) % 360) / 30));
        const tip = `${isOuter ? outerTip + ": " : ""}${name(k)} — ${deg(lon)} ${tipSign}${b.house ? `, ${T("wh_house", { n: b.house })}` : ""}${b.retro ? `, ${T("wh_retro")}` : ""}`
          + (aspBy[id] ? "\n" + aspBy[id].join("\n") : "");
        o.push(`<g class="pl" data-b="${id}" style="cursor:pointer"><title>${esc(tip)}</title>`);
        const r0 = isOuter ? R.zo : R.zi, r1 = isOuter ? R.zo + 9 : R.zi - 9;
        const [tx, ty] = pt(lon, r0), [ix, iy] = pt(lon, r1);
        line(tx, ty, ix, iy, isOuter ? color : `var(--b-${k}, ${color})`, 2);
        if (!isOuter) {         // направляющая от засечки к точке на круге аспектов
          const [gx, gy] = pt(lon, R.as);
          line(ix, iy, gx, gy, "var(--mute)", 0.5, ' opacity="0.35" stroke-dasharray="1 2"');
          o.push(`<circle cx="${f(gx)}" cy="${f(gy)}" r="3.2" fill="var(--b-${k}, var(--fg))"/>`);
        }
        const sp = spot[i], lr = sp.r;
        const [lx, ly0] = pt(sp.lon, lr);
        const ly = isOuter ? ly0 : ly0 - 6;
        const [ex, ey] = pt(sp.lon, isOuter ? lr - 10 : lr + 14);
        if (Math.hypot(ex - ix, ey - iy) > 6) line(ix, iy, ex, ey, color, 0.6, ' opacity="0.5"');
        const bold = strong.includes(k) && !isOuter;
        const halo = ' stroke="var(--bg)" stroke-width="3.5" paint-order="stroke" stroke-linejoin="round"';
        text(lx, ly, short(k), 12.5, color, bold ? 700 : 500, halo);
        if (!isOuter) text(lx, ly + 13, deg(lon).replace(/′.*/, "′") + (b.retro ? " R" : ""), 10, "var(--mute)", 400, halo);
        o.push(`</g>`);
      });
    }
    planets(chart, false);
    if (bi && known) {      // углы внутренней карты подписываются снаружи, вместе с планетами второго человека
      for (const [lon, lab] of [[chart.cusps[0], ASC], [chart.cusps[9], "MC"]]) {
        const sp = place(lon, 30, 15, [R.ob + 14, R.ob + 36]);
        const [x, y] = pt(sp.lon, sp.r);
        text(x, y, lab, 12.5, "var(--fg)", 700);
      }
    }
    if (bi) planets(outer, true);

    const ly = cy + R.max + 20;
    const leg = (y, color, label, dash = "") => {
      line(150, y, 186, y, color, 1.8, dash);
      o.push(`<text x="194" y="${y}" font-size="12" fill="var(--mute)" dominant-baseline="central">${esc(label)}</text>`);
    };
    leg(ly, BLUE, T("wh_harm"));
    leg(ly + 22, RED, T("wh_tense"));
    if (bi) leg(ly + 44, "var(--partner, var(--acc))", outerLegend);
    o.push(`<text x="${cx}" y="${ly + (bi ? 66 : 44)}" font-size="11" fill="var(--mute)" text-anchor="middle">${esc(T("wh_hint"))}</text>`);
    o.push("</svg>");
    return o.join("");
  }

  // подсветка аспектов выбранной планеты (вызывается один раз на странице)
  function wheelInteract(container) {
    const pick = (svg, id) => {
      svg.classList.toggle("focus", !!id);
      svg.querySelectorAll(".asp").forEach(l => l.classList.toggle("on", !!id && (l.dataset.a === id || l.dataset.b === id)));
      const linked = new Set([id]);
      svg.querySelectorAll(".asp.on").forEach(l => { linked.add(l.dataset.a); linked.add(l.dataset.b); });
      svg.querySelectorAll(".pl").forEach(g => g.classList.toggle("on", !!id && linked.has(g.dataset.b)));
    };
    // наведение — временная подсветка; касание или щелчок закрепляет выбор, повторный — снимает
    container.addEventListener("mouseover", e => { const g = e.target.closest(".wheel .pl"); if (g) pick(g.closest("svg"), g.dataset.b); });
    container.addEventListener("mouseout", e => {
      const g = e.target.closest(".wheel .pl"); if (!g) return;
      const svg = g.closest("svg"); pick(svg, svg.dataset.sel || null);
    });
    container.addEventListener("click", e => {
      const svg = e.target.closest(".wheel"); if (!svg) return;
      const g = e.target.closest(".pl");
      svg.dataset.sel = g && svg.dataset.sel !== g.dataset.b ? g.dataset.b : "";
      pick(svg, svg.dataset.sel || null);
    });
  }

  root.natalWheel = natalWheel;
  root.wheelInteract = wheelInteract;
  if (typeof module !== "undefined") module.exports = { natalWheel, spread, rows };
})(typeof window !== "undefined" ? window : globalThis);

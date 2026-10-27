/* Языки интерфейса. Слова страницы — в app/i18n/<язык>.json: сервер подставляет их в разметку (для поисковиков
   и до запуска скриптов) и кладёт словари в window.I18N_DATA, язык страницы — в window.I18N_LANG.
   Язык задаёт адрес: «/» и «/about» — русский, «/en/» и «/en/about» — английский.
   Подписи астрологии (планеты, знаки, дома, аспекты, режимы) приходят из доктрины (/api/doctrine?locale=…),
   тексты отчёта и прогноза — с сервера на языке страницы.
   t(key, vars): {x} — значение, {x_ord} — порядковое от числа (1st, 2nd…), массив — формы множественного числа по {n}.
   Здесь же — хранилище настроек в браузере (I18N.store, ключи temet.*). */
(function (root) {
  const PREFIX = "temet.", OLD = ["neoastro."];          // старые ключи (прежнее название сайта) переносятся один раз
  try {
    for (const k of Object.keys(localStorage)) for (const o of OLD)
      if (k.startsWith(o)) { const n = PREFIX + k.slice(o.length); if (localStorage.getItem(n) === null) localStorage.setItem(n, localStorage.getItem(k)); localStorage.removeItem(k); }
  } catch (e) {}
  const store = { get(k) { try { return JSON.parse(localStorage.getItem(PREFIX + k) || "null"); } catch (e) { return null; } },
                  set(k, v) { try { localStorage.setItem(PREFIX + k, JSON.stringify(v)); } catch (e) {} } };
  const D = root.I18N_DATA || {};
  const BASE = root.I18N_BASE || "ru";
  const LANGS = root.I18N_LANGS || Object.keys(D);
  const NAMES = root.I18N_NAMES || {};
  const LANG = root.I18N_LANG || document.documentElement.lang || BASE;
  // адреса страниц на языке: «/», «/about» у основного языка, «/en/», «/en/about» у остальных
  const prefix = l => (l === BASE ? "/" : `/${l}/`);
  const url = (page, l) => prefix(l || LANG) + (page && page !== "index" ? page : "");
  const pageOf = path => (path.replace(/^\/[a-z]{2}(?=\/)/, "").replace(/^\/+/, "").replace(/\/+$/, "") || "index");
  const ordinal = (n, l) => {
    if (l !== "en") return String(n);
    const k = Math.abs(+n), s = k % 100 >= 11 && k % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" })[k % 10] || "th";
    return `${n}${s}`;
  };
  const plural = (n, f) => {
    if (f.length === 1) return f[0];
    const k = Math.abs(+n);
    if (f.length >= 3) { const a = k % 10, b = k % 100; return a === 1 && b !== 11 ? f[0] : a >= 2 && a <= 4 && (b < 12 || b > 14) ? f[1] : f[2]; }
    return k === 1 ? f[0] : f[1];
  };
  function t(key, vars) {
    vars = vars || {};
    let s = (D[LANG] || {})[key] ?? (D[BASE] || {})[key] ?? key;
    if (Array.isArray(s) && typeof s[0] === "string" && "n" in vars) s = plural(vars.n, s);
    if (typeof s !== "string") return s;
    return s.replace(/\{(\w+?)(_ord)?\}/g, (m, k, o) => k in vars ? (o ? ordinal(vars[k], LANG) : String(vars[k])) : m);
  }
  // выбор языка запоминается (cookie — для сервера: на «/» он отправит на выбранный язык) и ведёт на ту же страницу
  function setLang(l) {
    if (!LANGS.includes(l)) return;
    store.set("lang", l);
    document.cookie = `temet_lang=${l}; path=/; max-age=31536000; samesite=lax`;
    location.href = url(pageOf(location.pathname), l) + location.search + location.hash;
  }
  // разметка: data-i18n — текст, data-i18n-html — разметка, data-i18n-attr="placeholder:key,aria-label:key"
  function apply(el) {
    el = el || document;
    el.querySelectorAll("[data-i18n]").forEach(x => x.textContent = t(x.dataset.i18n));
    el.querySelectorAll("[data-i18n-html]").forEach(x => x.innerHTML = t(x.dataset.i18nHtml));
    el.querySelectorAll("[data-i18n-attr]").forEach(x => x.dataset.i18nAttr.split(",").forEach(p => {
      const [a, k] = p.split(":"); x.setAttribute(a.trim(), t(k.trim()));
    }));
  }
  // переключатель языка: <nav class="lang" data-lang-switch></nav> — обычные ссылки на страницу на другом языке
  function switcher(el) {
    el.innerHTML = LANGS.map(l => `<a lang="${l}" hreflang="${l}" class="${l === LANG ? "on" : ""}" href="${url(pageOf(location.pathname), l)}"`
      + `${l === LANG ? ' aria-current="page"' : ""}>${NAMES[l] || l}</a>`).join("");
    el.querySelectorAll("a").forEach(a => a.onclick = e => { e.preventDefault(); if (a.lang !== LANG) setLang(a.lang); });
  }
  root.I18N = { lang: LANG, langs: LANGS, t, plural, ordinal, setLang, apply, switcher, store, url };
  root.t = t;
})(window);

/* Языки интерфейса. Подписи астрологии (планеты, знаки, дома, аспекты, режимы) приходят из доктрины
   (/api/doctrine?locale=…), тексты отчёта и прогноза — с сервера на выбранном языке; здесь — только слова страницы.
   t(key, vars): {x} — значение, {x_ord} — порядковое от числа (1st, 2nd…), массив — формы множественного числа по {n}.
   Язык: ?lang=…, иначе выбор на сайте (localStorage temet.lang и cookie для страниц сервера), иначе язык браузера.
   Здесь же — общее хранилище настроек в браузере (I18N.store, ключи temet.*). */
(function (root) {
  const PREFIX = "temet.", OLD = ["neoastro."];          // старые ключи (прежнее название сайта) переносятся один раз
  try {
    for (const k of Object.keys(localStorage)) for (const o of OLD)
      if (k.startsWith(o)) { const n = PREFIX + k.slice(o.length); if (localStorage.getItem(n) === null) localStorage.setItem(n, localStorage.getItem(k)); localStorage.removeItem(k); }
  } catch (e) {}
  const store = { get(k) { try { return JSON.parse(localStorage.getItem(PREFIX + k) || "null"); } catch (e) { return null; } },
                  set(k, v) { try { localStorage.setItem(PREFIX + k, JSON.stringify(v)); } catch (e) {} } };
  const D = {
    ru: {
      hero: "Астрология — язык для самопонимания и разговора, а не научный прогноз.",
      cta: "Готовы познавать себя?",
      hero_link: "Как это работает и как всё читать",
      footer_html: '<a href="https://github.com/Krasnopjorovs/temet">Исходный код</a> (AGPL‑3.0) · расчёты — <a href="https://www.astro.com/swisseph/">Swiss Ephemeris</a> · города — <a href="https://www.geonames.org/">GeoNames</a> (CC BY 4.0) · ничего не сохраняется',
      your_chart: "Ваша карта",
      calc: "Рассчитать карту", fc_week: "Прогноз на неделю", fc_month: "Прогноз на месяц",
      compat: "Совместимость с человеком", drafts: "показывать черновики текстов",
      looking_for: "Что вы ищете", close: "Закрыть", their_name: "Как его/её зовут", name_ph: "например, Анна", compare: "Сравнить карты",
      f_date: "Дата рождения", f_time: "Время (пусто — неизвестно)", f_unc: "Точность времени, ± мин",
      f_place: "Город рождения", f_place_ph: "начните вводить, например Рига",
      f_coords: "Координаты и часовой пояс (заполнятся из города)", f_lat: "Широта", f_lon: "Долгота", f_tz: "Часовой пояс (IANA)",
      err_date: "Укажите дату рождения",
      err_place: "Выберите город из списка (или заполните координаты и часовой пояс)",
      busy: "считаю…",
      more_items: ["Ещё {n} положение", "Ещё {n} положения", "Ещё {n} положений"],
      show_n: "Показать ({n})",
      pending_item: "Текст к этому положению ещё не написан.",
      draft: "черновик",
      lab_life: "Как это выглядит в жизни", lab_strength: "Ресурс", lab_shadow: "Когда этого слишком много", lab_action: "Что делать",
      sky_anchor: "{body} в знаке {sign}", sky_lead: "ведущая планета карты: {body}", sky_title: "Небо страницы окрашено вашей картой",
      no_time: "Время рождения неизвестно: дома и Асцендент не учитываются, Луна — с допуском.",
      dst: "Время попало на перевод часов — учтены оба варианта.",
      texts_ready: "Готово текстов: {a} из {b}.",
      intro_bg: "Эти положения одинаковы у всех, кто родился в те же годы: это фон эпохи, через который проявляются личные черты.",
      intro_syn: "Здесь отчёт складывает положения вместе: где разные стороны карты тянут в разные стороны и какие темы повторяются в нескольких положениях сразу. Под заголовком — положения, на которые опирается вывод; у них самих стоит такая же пометка.",
      wheel_aria: "Круг карты", wheel_link: "Что значат цвета и линии круга",
      tech: "Технические данные карты", tech_meta: "UTC {utc} · смещение {off} ч · система домов {hs}",
      th_body: "Тело", th_pos: "Положение", th_house: "Дом", th_ruler: "Управитель знака", th_state: "Состояние",
      th_aspect: "Аспект", th_type: "Тип", th_orb: "Орбис",
      // даты
      months_gen: ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"],
      months: ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"],
      weekdays: ["вс", "пн", "вт", "ср", "чт", "пт", "сб"],
      day: "{d} {mon}", day_year: "{d} {mon} {y}", month_year: "{mon} {y}", range: "{a} — {b}", at: "{d} в {t}",
      // прогноз
      span_from: "с {a}", span_to: "по {b}", span_from_to: "с {a} по {b}", span_until: "до {b}", span_all: "весь период и дольше",
      w_point: "{at}.", w_range: "{a} — {b}.",
      w_house: "В этом доме {span}.", w_ingress: " Входит в дом {at}.",
      w_retro: "Попятное движение {span}.", w_lasts: "Длится {span}.", w_active: "Действует {span}.", w_exact: " Точно: {list}.",
      w_multi: " Планета проходит эту точку несколько раз: она разворачивается и возвращается, поэтому тема повторяется и длится дольше обычного.",
      w_station_R: " Планета разворачивается назад прямо на этой точке {at}: тема звучит сильнее и дольше.",
      w_station_D: " Планета разворачивается вперёд прямо на этой точке {at}: тема звучит сильнее и дольше.",
      w_promise: " {a} и {b} связаны и в вашей натальной карте{asp}: транзит будит эту давнюю тему.",
      w_confirm: " Ту же тему задевает: {list}.",
      w_approx: " Дата приблизительная (±{n} дн.): так влияет неточность времени рождения.",
      pending_event: "Текст к этому событию ещё не написан.",
      fc_life: "Как это может ощущаться", fc_strength: "Что даёт этот период", fc_shadow: "На что обратить внимание", fc_action: "Что делать",
      key_days: "Ключевые дни", moon_days: "Луна по дням",
      moon_intro: "Луна проходит дом вашей карты за два-три дня и задаёт эмоциональный фон этих дней.",
      bg_summary: ["Фон периода: {n} долгое влияние", "Фон периода: {n} долгих влияния", "Фон периода: {n} долгих влияний"],
      bg_intro: "Медленные планеты и прогрессии: они идут дольше этого периода и задают его общий тон.",
      fc_outer_legend: "соединение; снаружи — небо в середине периода", fc_outer_tip: "Небо",
      fc_no_time: "Время рождения неизвестно: дома, Луна по дням и прогрессивная Луна не считаются.",
      fc_gaps: ["Тексты к прогнозу ещё пишутся: без текста пока {n} событие.", "Тексты к прогнозу ещё пишутся: без текста пока {n} события.", "Тексты к прогнозу ещё пишутся: без текста пока {n} событий."],
      fc_tz: "Время указано по часовому поясу {tz}.",
      prev: "Предыдущий период", next: "Следующий период", week: "Неделя", month: "Месяц",
      intensity_tip: "насыщеннее, чем {p}% случайных недель и месяцев",
      main: "Главное", calm: "Сильных влияний в этот период нет: спокойное время.",
      by_day: "По дням", click_row: "Нажмите на строку, чтобы прочитать текст.",
      more_events: ["Ещё {n} событие", "Ещё {n} события", "Ещё {n} событий"],
      lg_harm: "гармоничные", lg_tense: "напряжённые", lg_conj: "соединения, лунации", lg_house: "дома", lg_retro: "попятное движение",
      lg_exact: "● точное касание", lg_station: "○ разворот планеты",
      howto: "Как читать ленту и что значат цвета",
      howto_html: `<p>Каждая строка — одно влияние периода, полоска — дни, когда оно действует, по шкале дней сверху. Нажмите на строку, чтобы прочитать текст.</p>
      <ul>
        <li><b style="color:var(--tense)">Красный — напряжённые аспекты</b> (квадрат, оппозиция). Две силы тянут в разные стороны: трение, нагрузка, споры, желание всё изменить. Это не беда, а давление к действию: напряжение даёт энергию, если направить её в дело, а не в борьбу.</li>
        <li><b style="color:var(--harm)">Голубой — гармоничные аспекты</b> (трин, секстиль). Силы поддерживают друг друга: то, что в эти дни даётся легче, — разговоры, решения, отдых, начинания. Облегчение не действует само: им стоит воспользоваться.</li>
        <li><b style="color:var(--acc-text)">Цвет акцента — соединения, новолуния и полнолуния.</b> Две силы сливаются, и тема выходит на первый план; характер зависит от планет. Цвет акцента взят из вашей карты.</li>
        <li><b>Серый — планета идёт по дому</b>: в какой сфере жизни сейчас разворачивается её тема.</li>
        <li><b style="color:var(--partner)">Розовый пунктир — попятное движение</b>: время пересмотра и доработки в сфере этого дома.</li>
        <li><b>Точка</b> — момент точного аспекта, пик влияния. <b>Кольцо</b> — планета разворачивается на этой точке: тема звучит сильнее и дольше. Полоска до края шкалы — влияние началось раньше или продолжится после периода.</li>
      </ul>
      <p class="note">Подробнее — на странице <a href="/about#forecast">«Как это работает»</a>.</p>`,
      sky_period: "Небо этого периода и ваша карта",
      // совместимость
      them: "он/она", you: "вы", other_person: "второй человек",
      more_you: "важнее для вас", more_them: "важнее для: {who}",
      ov_yours: "{who} — в вашем {h}-м доме ({hl})", ov_named: "{who} — в {name}: {h}-м доме ({hl})", ov_their: "{who} — в его/её {h}-м доме ({hl})",
      contact: "{tb} ({them}) — {yb} ({you}): {asp}, {orb}°",
      out_of: "из 100 · {mode}<br>итог высокий, только если хорошо обоим",
      receive: "Вы получаете больше, чем в {a}% случайных пар; {who} — больше, чем в {b}%.",
      asym: "Заметный перекос: одному в этом союзе даётся гораздо больше, чем другому.",
      th_theme: "Тема", you_receive: "вы получаете", they_receive: "{who} получает",
      links: "Главные связи между вами", no_links: "Сильных связей нет.",
      links_note: "«+» — связь работает на союз в своей теме, «−» — создаёт напряжение. В теме «{attr}» напряжённые аспекты (квадрат, оппозиция) тоже считаются силой притяжения — это искра, а не обязательно лёгкость.",
      // круг карты
      wh_asc: "Асц", wh_house: "{n}-й дом", wh_retro: "ретроградно",
      wh_harm: "гармоничные связи: тригон, секстиль (пунктир)", wh_tense: "напряжённые связи: квадрат, оппозиция (пунктир)",
      wh_hint: "наведите на планету или коснитесь её — подсветятся её аспекты",
      wh_outer_legend: "соединение; снаружи цветом — планеты второго человека", wh_outer_tip: "Партнёр",
    },
    en: {
      hero: "Astrology is a language for self-understanding and conversation, not a scientific prediction.",
      cta: "Ready to know yourself?",
      hero_link: "How it works and how to read it",
      footer_html: '<a href="https://github.com/Krasnopjorovs/temet">Source code</a> (AGPL‑3.0) · calculations by <a href="https://www.astro.com/swisseph/">Swiss Ephemeris</a> · places by <a href="https://www.geonames.org/">GeoNames</a> (CC BY 4.0) · nothing is stored',
      your_chart: "Your chart",
      calc: "Calculate chart", fc_week: "Forecast for the week", fc_month: "Forecast for the month",
      compat: "Compatibility with someone", drafts: "show draft texts",
      looking_for: "What you are looking for", close: "Close", their_name: "Their name", name_ph: "for example, Anna", compare: "Compare charts",
      f_date: "Date of birth", f_time: "Time (leave empty if unknown)", f_unc: "Time accuracy, ± min",
      f_place: "Place of birth", f_place_ph: "start typing, for example Riga",
      f_coords: "Coordinates and time zone (filled in from the city)", f_lat: "Latitude", f_lon: "Longitude", f_tz: "Time zone (IANA)",
      err_date: "Enter the date of birth",
      err_place: "Choose a city from the list (or fill in the coordinates and time zone)",
      busy: "calculating…",
      more_items: ["{n} more placement", "{n} more placements"],
      show_n: "Show ({n})",
      pending_item: "The text for this placement has not been written yet.",
      draft: "draft",
      lab_life: "How it shows up in life", lab_strength: "Strength", lab_shadow: "When there is too much of it", lab_action: "What to do",
      sky_anchor: "{body} in {sign}", sky_lead: "leading planet of the chart: {body}", sky_title: "The sky of this page is coloured by your chart",
      no_time: "Birth time unknown: the houses and the Ascendant are left out, and the Moon is shown with a margin.",
      dst: "The time falls on a clock change, so both readings are taken into account.",
      texts_ready: "Texts ready: {a} of {b}.",
      intro_bg: "These placements are the same for everyone born in the same years: they are the background of the era through which personal traits show.",
      intro_syn: "Here the report puts placements together: where different sides of the chart pull in different directions and which themes repeat across several placements. Under each heading are the placements the conclusion rests on; they carry the same mark.",
      wheel_aria: "Chart wheel", wheel_link: "What the colours and lines of the wheel mean",
      tech: "Technical chart data", tech_meta: "UTC {utc} · offset {off} h · house system {hs}",
      th_body: "Body", th_pos: "Position", th_house: "House", th_ruler: "Sign ruler", th_state: "Dignity",
      th_aspect: "Aspect", th_type: "Type", th_orb: "Orb",
      months_gen: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
      months: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
      weekdays: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
      day: "{mon} {d}", day_year: "{mon} {d}, {y}", month_year: "{mon} {y}", range: "{a} — {b}", at: "{d} at {t}",
      span_from: "from {a}", span_to: "to {b}", span_from_to: "from {a} to {b}", span_until: "until {b}", span_all: "the whole period and beyond",
      w_point: "{at}.", w_range: "{a} — {b}.",
      w_house: "In this house {span}.", w_ingress: " Enters the house {at}.",
      w_retro: "Retrograde {span}.", w_lasts: "Lasts {span}.", w_active: "Active {span}.", w_exact: " Exact: {list}.",
      w_multi: " The planet passes this point several times: it turns around and comes back, so the theme repeats and lasts longer than usual.",
      w_station_R: " The planet turns retrograde right on this point {at}: the theme sounds stronger and lasts longer.",
      w_station_D: " The planet turns direct right on this point {at}: the theme sounds stronger and lasts longer.",
      w_promise: " {a} and {b} are also linked in your birth chart{asp}: the transit wakes up this old theme.",
      w_confirm: " The same theme is also touched by: {list}.",
      w_approx: " The date is approximate (±{n} days) because the birth time is not exact.",
      pending_event: "The text for this event has not been written yet.",
      fc_life: "How it may feel", fc_strength: "What this period gives", fc_shadow: "What to watch for", fc_action: "What to do",
      key_days: "Key days", moon_days: "The Moon day by day",
      moon_intro: "The Moon passes through a house of your chart in two to three days and sets the emotional tone of those days.",
      bg_summary: ["Background of the period: {n} long influence", "Background of the period: {n} long influences"],
      bg_intro: "Slow planets and progressions: they last longer than this period and set its overall tone.",
      fc_outer_legend: "conjunction; outside: the sky in the middle of the period", fc_outer_tip: "Sky",
      fc_no_time: "Birth time unknown: the houses, the Moon by day and the progressed Moon are not calculated.",
      fc_gaps: ["Forecast texts are still being written: {n} event has no text yet.", "Forecast texts are still being written: {n} events have no text yet."],
      fc_tz: "Times are shown in the {tz} time zone.",
      prev: "Previous period", next: "Next period", week: "Week", month: "Month",
      intensity_tip: "busier than {p}% of random weeks and months",
      main: "Highlights", calm: "No strong influences in this period: a quiet time.",
      by_day: "Day by day", click_row: "Click a row to read its text.",
      more_events: ["{n} more event", "{n} more events"],
      lg_harm: "harmonious", lg_tense: "tense", lg_conj: "conjunctions, lunations", lg_house: "houses", lg_retro: "retrograde motion",
      lg_exact: "● exact hit", lg_station: "○ planet turns",
      howto: "How to read the timeline and what the colours mean",
      howto_html: `<p>Each row is one influence of the period; the bar shows the days when it is active, on the day scale at the top. Click a row to read its text.</p>
      <ul>
        <li><b style="color:var(--tense)">Red: tense aspects</b> (square, opposition). Two forces pull in different directions: friction, load, arguments, a wish to change everything. It is not a disaster but pressure to act: tension gives energy if you put it into work rather than into a fight.</li>
        <li><b style="color:var(--harm)">Blue: harmonious aspects</b> (trine, sextile). The forces support each other: what comes easier on these days, such as conversations, decisions, rest and new starts. The ease does not act on its own: it is worth using.</li>
        <li><b style="color:var(--acc-text)">Accent colour: conjunctions, New Moons and Full Moons.</b> Two forces merge and the theme comes to the front; its character depends on the planets. The accent colour is taken from your chart.</li>
        <li><b>Grey: a planet moving through a house</b>, the area of life where its theme is unfolding now.</li>
        <li><b style="color:var(--partner)">Pink dashes: retrograde motion</b>, a time to review and rework things in the area of that house.</li>
        <li><b>A dot</b> is the moment of the exact aspect, the peak of the influence. <b>A ring</b> means the planet turns around on this point: the theme sounds stronger and lasts longer. A bar running to the edge of the scale means the influence started earlier or goes on after the period.</li>
      </ul>
      <p class="note">More on the <a href="/about#forecast">How it works</a> page.</p>`,
      sky_period: "The sky of this period and your chart",
      them: "partner", you: "you", other_person: "the other person",
      more_you: "matters more to you", more_them: "matters more to: {who}",
      ov_yours: "{who} — in your {h_ord} house ({hl})", ov_named: "{who} — in {name}'s {h_ord} house ({hl})", ov_their: "{who} — in their {h_ord} house ({hl})",
      contact: "{tb} ({them}) — {yb} ({you}): {asp}, {orb}°",
      out_of: "out of 100 · {mode}<br>the score is high only if it works for both of you",
      receive: "You receive more than in {a}% of random pairs; {who}: more than in {b}%.",
      asym: "A clear imbalance: one of you gets much more from this union than the other.",
      th_theme: "Theme", you_receive: "you receive", they_receive: "{who} receives",
      links: "The main links between you", no_links: "No strong links.",
      links_note: "“+” means the link works for the union in its theme, “−” means it creates tension. In the “{attr}” theme, tense aspects (square, opposition) also count as a pull: a spark, not necessarily ease.",
      wh_asc: "Asc", wh_house: "{n_ord} house", wh_retro: "retrograde",
      wh_harm: "harmonious links: trine, sextile (dashed)", wh_tense: "tense links: square, opposition (dashed)",
      wh_hint: "hover over or tap a planet to highlight its aspects",
      wh_outer_legend: "conjunction; outside in colour: the other person's planets", wh_outer_tip: "Partner",
    },
  };
  const BASE = "ru";
  const LANGS = Object.keys(D);
  const NAMES = { ru: "Русский", en: "English" };
  const ok = l => l && LANGS.includes(l) ? l : null;
  const short = l => String(l || "").toLowerCase().split(/[-_]/)[0];
  function read() { try { return localStorage.getItem(PREFIX + "lang"); } catch (e) { return null; } }
  function pick() {
    const q = new URLSearchParams(location.search).get("lang");
    if (ok(short(q))) return short(q);
    if (ok(read())) return read();
    for (const l of navigator.languages || [navigator.language]) if (ok(short(l))) return short(l);
    return BASE;
  }
  const LANG = pick();
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
    let s = D[LANG][key] ?? D[BASE][key] ?? key;
    if (Array.isArray(s) && typeof s[0] === "string" && "n" in vars) s = plural(vars.n, s);
    if (typeof s !== "string") return s;
    return s.replace(/\{(\w+?)(_ord)?\}/g, (m, k, o) => k in vars ? (o ? ordinal(vars[k], LANG) : String(vars[k])) : m);
  }
  function setLang(l) {
    if (!ok(l)) return;
    try { localStorage.setItem(PREFIX + "lang", l); } catch (e) {}
    document.cookie = `temet_lang=${l}; path=/; max-age=31536000; samesite=lax`;
    const u = new URL(location.href);
    u.searchParams.delete("lang");
    location.href = u.pathname + u.search + u.hash;
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
  // переключатель языка: <nav class="lang" data-lang-switch></nav>
  function switcher(el) {
    el.innerHTML = LANGS.map(l => `<button type="button" lang="${l}" class="${l === LANG ? "on" : ""}" aria-pressed="${l === LANG}">${NAMES[l] || l}</button>`).join("");
    el.querySelectorAll("button").forEach(b => b.onclick = () => b.lang !== LANG && setLang(b.lang));
  }
  // страница, которую сервер отдал на конкретном языке (data-page-lang), а выбран другой — попросить нужную
  const page = document.documentElement.dataset.pageLang;
  if (page && page !== LANG && new URLSearchParams(location.search).get("lang") !== LANG) {   // без петли, если версии нет
    const u = new URL(location.href); u.searchParams.set("lang", LANG); location.replace(u.href);
  }
  document.documentElement.lang = LANG;
  // сервер отдаёт страницы (about) на языке из cookie — держим её в согласии с выбранным языком
  document.cookie = `temet_lang=${LANG}; path=/; max-age=31536000; samesite=lax`;
  if (ok(short(new URLSearchParams(location.search).get("lang")))) {   // ссылка с ?lang= — запомнить выбор
    try { localStorage.setItem(PREFIX + "lang", LANG); } catch (e) {}
  }
  root.I18N = { lang: LANG, langs: LANGS, t, plural, ordinal, setLang, apply, switcher, store };
  root.t = t;
})(window);

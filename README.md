# Temet nosce

*Know thyself.* A birth chart report, a weekly and monthly forecast and a two-person compatibility check, in
Russian and English. Live at [temet.artjoms.ai](https://temet.artjoms.ai).

There is no language model at runtime. Every chart, transit and score is computed with the Swiss Ephemeris and a
set of open rules; the texts the reader sees were written in advance, checked and approved one by one, and the
service only picks the right ones. The same data always gives the same report, and nothing is stored on the server.

## What it does

- **Birth chart report.** Planets, signs, houses, aspects, dignities, rulers and compound patterns, grouped by
  areas of life. A synthesis step finds the tensions and recurring themes of the chart (seven classical
  polarities, compared against a population of random charts), and repeated wording between cards is removed.
- **Forecast for a week or a month.** Transits with entry, exact hits and exit (retrograde loops merged into one
  episode, stations on a point, natal "promise"), transits through houses, the Moon by day, New and Full Moons,
  eclipses, retrograde Mercury, Venus and Mars, the progressed Moon. The intensity of a period is a percentile
  against random charts and dates. Dates are checked against independent planetary theories and the NASA eclipse
  catalogue (`scripts.verify_engine`).
- **Compatibility.** Directed scores "A receives from B" and "B receives from A" by theme (attraction, stability,
  karmic growth, shared work, mind), as percentiles against millions of random pairs.
- **The page sky takes the colours of the chart**: the Sun, Moon and Ascendant signs, and the leading planet.

## Design

All astrological knowledge lives in data, not in code: `doctrine/classic_modern_v1.yaml` (bodies, rulerships,
dignities, orbs, weights, rules, forecast parameters, labels in every language) is loaded into Postgres. Another
school of astrology is another YAML file.

Compatibility is bilinear: a chart's "needs" vector times another chart's "emits" vector (Fourier series of the
aspect kernels, D = 1552), so pgvector can search for matches with the same quantity that ranks them. Birth-time
uncertainty enters exactly through a sinc factor.

Languages: labels come from the doctrine (`label: {ru: …, en: …}`), server-built strings from
`params.strings.<lang>`, page words from `app/static/i18n.js`; texts are stored per language.

## Run

    echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" > .env
    docker compose up -d db
    docker compose run --rm api python -m scripts.bootstrap --geonames
    docker compose up -d api           # http://127.0.0.1:8095 (loopback; API_BIND / API_PORT in .env)

The repository has no interpretation texts (see below), so the report shows the computed structure and says that a
text is not written yet. To add your own texts, write JSON files (`key`, `title`, `body`, `in_life`, `strength`,
`shadow`, `action`) and import them:

    docker compose run --rm api python -m scripts.import_content my_texts.json [--locale en]
    docker compose run --rm api python -m scripts.import_content --approve '%'

`GET /api/doctrine` lists the key space; `python -m scripts.gate_content` checks Russian texts and
`python -m scripts.gate_translation` checks translations against their source (`requirements-dev.txt`).

Tests: `pip install -r requirements-dev.txt && pytest tests/`. Engine checks: `python -m scripts.verify_engine`.

More detail (architecture, measurements, scripts) is in Russian in [docs/README.ru.md](docs/README.ru.md).

## License

Copyright © 2026 Artjoms Krasnopjorovs.

The code is free software under the GNU Affero General Public License v3.0 (`LICENSE`). The project uses the
Swiss Ephemeris under its AGPL option; if you run a modified version as a public service, you must offer your
source code to its users. Third-party notices are in `NOTICE.md`.

The interpretation texts and the prompts used to write them are not included and not covered by this license.

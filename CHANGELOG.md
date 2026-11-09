# Changelog

The plan for the next versions is in the [roadmap](https://github.com/Krasnopjorovs/temet/issues/1).

## 0.19.0 (2026-11-09)

- Every push and pull request is checked in GitHub Actions: lint (`ruff`), unit tests (`pytest`) and the engine
  checks against independent references (`scripts.verify_engine`: planetary theories VSOP87 and ELP, house
  formulas, a second time zone library, transit dates, stations, lunations, the NASA eclipse catalogue).
  A failed engine check now fails the run.
- One version for the whole project: the `VERSION` file is shown in the page footer, in `/healthz` and in the API
  description, and is the tag of the release.
- The roadmap is on GitHub: 15 milestones and 74 issues.

## 0.18.0 (2026-10-27): public launch

- Open source under AGPL-3.0; the site is public at [temet.artjoms.ai](https://temet.artjoms.ai).
- Pages for search engines: a server-rendered page per language, canonical and hreflang links, sitemap, Open Graph
  tags and JSON-LD.
- Unapproved texts only from the local network; a rate limit per visitor; nothing is stored.

## Before 0.18 (October 2026)

- **Birth chart engine.** Swiss Ephemeris calculations; all astrology in one doctrine file loaded into Postgres; a
  report ranked by PageRank over rulerships and aspects; synthesis of tensions and recurring themes against a
  population of random charts; birth time uncertainty in every result; compatibility as directed percentiles.
- **Forecasts for the week and month.** Transits as episodes with retrograde loops merged, stations and the natal
  "promise"; transits through houses; the Moon by day; New and Full Moons and eclipses; retrograde Mercury, Venus and
  Mars; the progressed Moon; intensity as a percentile; themes confirmed by two or more techniques.
- **English version.** The interface and every text in Russian and English, each language at its own address.

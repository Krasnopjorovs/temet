# Notices

Temet nosce is free software under the GNU Affero General Public License v3.0 (see `LICENSE`).
If you run a modified version as a network service, you must offer its source code to its users (AGPL §13);
the site does this with the "Source code" link in the footer.

## Swiss Ephemeris

Planet positions are computed with the Swiss Ephemeris by Astrodienst AG, Switzerland
(authors Dieter Koch and Alois Treindl), used through the `pyswisseph` binding. The Swiss Ephemeris is
dual-licensed (AGPL or the Swiss Ephemeris Professional License); this project uses it under the AGPL,
which is why the whole project is AGPL-3.0. The ephemeris data files in `ephe/` (`sepl_18.se1`,
`semo_18.se1`, `seas_18.se1`) are part of the Swiss Ephemeris and are distributed under the same terms.
https://www.astro.com/swisseph/

## GeoNames

City names, coordinates and time zones come from the GeoNames geographical database
(https://www.geonames.org/), licensed under Creative Commons Attribution 4.0 (CC BY 4.0).
The data is downloaded during setup (`scripts.load_geonames --download`) and is not stored in this repository.

## Fonts

`app/static/fonts/` contains Unbounded and Literata, both under the SIL Open Font License 1.1
(`OFL-Unbounded.txt`, `OFL-Literata.txt`).

## Python dependencies

Installed from PyPI, not bundled: pyswisseph (AGPL-3.0), FastAPI (MIT), uvicorn (BSD-3-Clause), pydantic (MIT),
numpy (BSD-3-Clause and others), psycopg (LGPL-3.0), psycopg-pool (LGPL-3.0), pgvector (MIT), PyYAML (MIT),
tzdata (Apache-2.0), pymorphy3 and pymorphy3-dicts-ru (MIT); for the text checks only: snowballstemmer
(BSD-3-Clause), pytest (MIT).

## Texts

The interpretation texts of the report and the forecast (natal placements, transits, compatibility notes) and
the prompts used to write them are **not** part of this repository and not covered by its license. They are a
separate work, © Artjoms Krasnopjorovs, all rights reserved. Without them the program runs and shows that a text
is not written yet; you can write and import your own (`scripts.import_content`).

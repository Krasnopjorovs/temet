"""Офлайн-геокодер: GeoNames cities15000 (все города > 15 000 жителей, с IANA-зонами).
Без внешних API при каждом запросе и без «тихого фолбэка в Цюрих».
python -m scripts.load_geonames --download          # скачать и загрузить
python -m scripts.load_geonames /path/cities15000.txt"""
import argparse
import io
import os
import urllib.request
import zipfile

from astro import store

URL = "https://download.geonames.org/export/dump/cities15000.zip"


def rows(fh):
    for line in fh:
        f = line.rstrip("\n").split("\t")
        if len(f) < 18:
            continue
        yield (int(f[0]), f[1], f[2], f[3][:20000], f[8], float(f[4]), float(f[5]), f[17], int(f[14] or 0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--download", action="store_true")
    a = ap.parse_args()
    if a.download:
        data = urllib.request.urlopen(URL, timeout=120).read()
        fh = io.TextIOWrapper(zipfile.ZipFile(io.BytesIO(data)).open("cities15000.txt"), encoding="utf-8")
    else:
        fh = open(a.path, encoding="utf-8")
    with store.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("truncate place")
        with cur.copy("copy place (id, name, ascii_name, alt_names, country, lat, lon, tz, population) "
                      "from stdin") as cp:
            n = 0
            for r in rows(fh):
                cp.write_row(r)
                n += 1
        conn.commit()
    print(f"loaded {n} places")


if __name__ == "__main__":
    main()

"""Пересчитать карты и векторы всех профилей после изменения доктрины.
python -m scripts.reembed"""
import os
import time

from psycopg.types.json import Jsonb

from astro import store
from astro.chart import build_chart
from astro.ephemeris import BirthInput
from astro.service import Runtime


def main():
    with store.connect(os.environ["DATABASE_URL"]) as conn:
        rt = Runtime.load(conn)
        with conn.cursor() as cur:
            cur.execute("select id, birth_local, time_known, time_uncertainty_min, tz, lat, lon, place_label "
                        "from profile where doctrine_id=%s", (rt.doctrine_id,))
            rows = cur.fetchall()
        t = time.time()
        for r in rows:
            bl = r["birth_local"]
            inp = BirthInput(bl.strftime("%Y-%m-%d"), bl.strftime("%H:%M") if r["time_known"] else None,
                             r["tz"], r["lat"], r["lon"],
                             r["time_uncertainty_min"] if r["time_known"] else None, r["place_label"])
            chart = build_chart(inp, rt.d)
            with conn.cursor() as cur:
                cur.execute("update profile set chart=%s, syn_hash=%s where id=%s",
                            (Jsonb(chart), rt.syn.fingerprint, r["id"]))
                store.write_vectors(cur, r["id"], rt.d.code, rt.syn.vectors(chart))
            conn.commit()
        print(f"re-embedded {len(rows)} profiles in {time.time() - t:.1f}s")


if __name__ == "__main__":
    main()

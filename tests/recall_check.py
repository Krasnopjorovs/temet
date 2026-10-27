"""Сверка выдачи API (HNSW в обе стороны + Нэш) с точным перебором всей базы.
python -m tests.recall_check <handle> [--api http://localhost:8095]"""
import argparse
import json
import os
import time
import urllib.request

from astro import store
from astro.service import Runtime
from astro.synastry import nash, percentile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("handle")
    ap.add_argument("--api", default="http://localhost:8095")
    ap.add_argument("--k", type=int, default=20)
    a = ap.parse_args()
    conn = store.connect(os.environ["DATABASE_URL"])
    rt = Runtime.load(conn)
    dc = rt.d.code
    with conn.cursor() as cur:
        cur.execute("select id from profile where handle=%s", (a.handle,))
        me = cur.fetchone()["id"]
    last = None
    for mode in rt.d.modes:
        t = time.time()
        url = f"{a.api}/api/profiles/{a.handle}/matches?mode={mode}&k={a.k}&include_synthetic=true"
        res = json.load(urllib.request.urlopen(url))
        dt = time.time() - t
        with conn.cursor() as cur:
            cur.execute("select id from profile where %s = any(modes) and id <> %s", (mode, me))
            ids = [r["id"] for r in cur.fetchall()]
        V = store.get_vectors(conn, ids + [me], [f"{dc}:x", f"{dc}:q:{mode}"])
        xm, qm = V[(me, f"{dc}:x")], V[(me, f"{dc}:q:{mode}")]
        lam, cal = rt.d.modes[mode]["nash_lambda"], rt.calibration[mode]
        exact = sorted(((100 * nash(percentile(qm @ V[(i, f"{dc}:x")], cal),
                                    percentile(V[(i, f"{dc}:q:{mode}")] @ xm, cal), lam), i) for i in ids),
                       reverse=True)[:a.k]
        got = {m["profile_id"] for m in res["matches"]}
        rec = len(got & {i for _, i in exact}) / a.k
        print(f"{mode:10} eligible={len(ids):5} scanned={res['candidates_scanned']:4} recall@{a.k}={rec:.2f} "
              f"best_api={res['matches'][0]['score']:6.2f} best_exact={exact[0][0]:6.2f} latency={dt * 1000:.0f}ms")
        last = res
    m = last["matches"][0]
    print(json.dumps({k: m[k] for k in ("handle", "score", "you_receive_pct", "they_receive_pct", "asymmetry")},
                     ensure_ascii=False))
    print("contacts:", json.dumps(m["you_receive_from_them"][:4], ensure_ascii=False))


if __name__ == "__main__":
    main()

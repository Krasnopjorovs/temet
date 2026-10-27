"""Postgres + pgvector. Доктрина читается из таблиц; эмбеддинги — по виду
'<doctrine>:x' и '<doctrine>:q:<MODE>', для каждого вида — частичный HNSW-индекс
по выражению v::vector(D) с оператором скалярного произведения."""
from __future__ import annotations

import json
import re

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .doctrine import TABLES, Doctrine, doctrine_from_tables


def connect(dsn: str) -> psycopg.Connection:
    conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=False)
    register_vector(conn)
    return conn


def configure(conn: psycopg.Connection) -> None:
    register_vector(conn)


# ------------------------------------------------------------------ doctrine
def write_doctrine(conn, tables: dict, source_yaml: str) -> int:
    dc = tables["doctrine"]
    with conn.cursor() as cur:
        cur.execute(
            """insert into doctrine (code, title, params, source_yaml) values (%s,%s,%s,%s)
               on conflict (code) do update set title=excluded.title, params=excluded.params,
               source_yaml=excluded.source_yaml, loaded_at=now() returning id""",
            (dc["code"], dc["title"], Jsonb(dc["params"]), source_yaml))
        did = cur.fetchone()["id"]
        for t in TABLES:
            cur.execute(f"delete from {t} where doctrine_id=%s", (did,))
            for row in tables[t]:
                cols = list(row)
                vals = [Jsonb(v) if isinstance(v, dict) else v for v in row.values()]
                cur.execute(
                    f"insert into {t} (doctrine_id, {', '.join(_q(c) for c in cols)}) "
                    f"values (%s, {', '.join(['%s'] * len(cols))})", [did, *vals])
    conn.commit()
    return did


def _q(col: str) -> str:
    return f'"{col}"' if col in ("class",) else col


def read_doctrine(conn, code: str) -> tuple[int, Doctrine]:
    with conn.cursor() as cur:
        cur.execute("select id, code, title, params from doctrine where code=%s", (code,))
        dc = cur.fetchone()
        if not dc:
            raise LookupError(f"doctrine {code} not loaded")
        t = {"doctrine": dc}
        for name in TABLES:
            cur.execute(f"select * from {name} where doctrine_id=%s", (dc["id"],))
            t[name] = [{k: v for k, v in r.items() if k != "doctrine_id"} for r in cur.fetchall()]
    return dc["id"], doctrine_from_tables(t)


def ensure_indexes(conn, doctrine: Doctrine, dim: int) -> list[str]:
    kinds = [f"{doctrine.code}:x"] + [f"{doctrine.code}:q:{m}" for m in doctrine.modes]
    made = []
    with conn.cursor() as cur:
        for k in kinds:
            name = "emb_" + re.sub(r"[^a-z0-9]+", "_", k.lower()) + f"_{dim}"
            cur.execute(
                f"create index if not exists {name} on embedding using hnsw "
                f"((v::vector({dim})) vector_ip_ops) with (m = 16, ef_construction = 128) "
                f"where kind = '{k}'")
            made.append(name)
    conn.commit()
    return made


# ------------------------------------------------------------------ calibration
def write_calibration(conn, doctrine_id: int, key: str, quantiles: list[float], n: int, population: str,
                      syn_hash: str):
    with conn.cursor() as cur:
        cur.execute(
            """insert into calibration (doctrine_id, key, quantiles, n_pairs, population, syn_hash)
               values (%s,%s,%s,%s,%s,%s)
               on conflict (doctrine_id, key) do update set quantiles=excluded.quantiles,
               n_pairs=excluded.n_pairs, population=excluded.population, syn_hash=excluded.syn_hash,
               created_at=now()""",
            (doctrine_id, key, quantiles, n, population, syn_hash))
    conn.commit()


def read_calibration(conn, doctrine_id: int, syn_hash: str) -> dict[str, list[float]]:
    """Только калибровка, посчитанная для текущих весов; устаревшая игнорируется."""
    with conn.cursor() as cur:
        cur.execute("select key, quantiles from calibration where doctrine_id=%s and syn_hash=%s",
                    (doctrine_id, syn_hash))
        return {r["key"]: r["quantiles"] for r in cur.fetchall()}


# ------------------------------------------------------------------ content
def read_content(conn, doctrine_id: int, keys: list[str], locale: str = "ru",
                 include_drafts: bool = False) -> dict[str, dict]:
    """одобренные тексты; с include_drafts — ещё черновики и правки одобренных (правка показывается вместо оригинала)"""
    statuses = ["approved", "draft"] if include_drafts else ["approved"]
    with conn.cursor() as cur:
        cur.execute("""select key, payload, draft_payload, status from content where doctrine_id=%s and locale=%s
                       and status = any(%s) and key = any(%s)""", (doctrine_id, locale, statuses, keys))
        out = {}
        for r in cur.fetchall():
            if include_drafts and r["draft_payload"] is not None:
                out[r["key"]] = {**r["draft_payload"], "_status": "draft"}
            else:
                out[r["key"]] = {**r["payload"], "_status": r["status"]}
        return out


def content_rows(conn, doctrine_id: int, locale: str = "ru") -> dict[str, tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute("select key, status, source from content where doctrine_id=%s and locale=%s",
                    (doctrine_id, locale))
        return {r["key"]: (r["status"], r["source"]) for r in cur.fetchall()}


def content_keys(conn, doctrine_id: int, locale: str = "ru") -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("select key, status from content where doctrine_id=%s and locale=%s", (doctrine_id, locale))
        return {r["key"]: r["status"] for r in cur.fetchall()}


# ------------------------------------------------------------------ profiles
def insert_profile(conn, doctrine_id: int, doctrine_code: str, prof: dict, chart: dict,
                   vectors: dict[str, np.ndarray]) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """insert into profile (doctrine_id, handle, birth_local, time_known, time_uncertainty_min, tz,
                                    lat, lon, place_label, modes, synthetic, chart, syn_hash)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
            (doctrine_id, prof["handle"], prof["birth_local"], chart["meta"]["time_known"],
             chart["meta"]["input"]["uncertainty_min"], prof["tz"], prof["lat"], prof["lon"],
             prof.get("place_label", ""), prof["modes"], prof.get("synthetic", False), Jsonb(chart),
             prof["syn_hash"]))
        pid = cur.fetchone()["id"]
        write_vectors(cur, pid, doctrine_code, vectors)
    conn.commit()
    return pid


def write_vectors(cur, pid: int, doctrine_code: str, vectors: dict[str, np.ndarray]):
    cur.execute("delete from embedding where profile_id=%s and kind like %s", (pid, f"{doctrine_code}:%"))
    with cur.copy("copy embedding (profile_id, kind, v) from stdin with (format binary)") as cp:
        cp.set_types(["int8", "text", "vector"])
        for kind, vec in vectors.items():
            cp.write_row([pid, f"{doctrine_code}:{kind}", np.asarray(vec, dtype=np.float32)])


def get_profile(conn, handle: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("select * from profile where handle=%s", (handle,))
        return cur.fetchone()


def get_vectors(conn, ids: list[int], kinds: list[str]) -> dict[tuple[int, str], np.ndarray]:
    with conn.cursor() as cur:
        cur.execute("select profile_id, kind, v from embedding where profile_id = any(%s) and kind = any(%s)",
                    (ids, kinds))
        return {(r["profile_id"], r["kind"]): _np(r["v"]) for r in cur.fetchall()}


def _np(v) -> np.ndarray:
    v = v.to_numpy() if hasattr(v, "to_numpy") else v
    return np.asarray(v, dtype=np.float64)


def ann(conn, kind: str, query: np.ndarray, dim: int, k: int, exclude_id: int,
        mode: str, include_synthetic: bool, ef_search: int = 200) -> list[tuple[int, float]]:
    """Максимум скалярного произведения: <#> возвращает -(a·b)."""
    with conn.cursor() as cur:
        cur.execute(f"set local hnsw.ef_search = {int(ef_search)}")
        cur.execute(
            f"""select e.profile_id, -((e.v::vector({dim})) <#> %s::vector({dim})) as s
                from embedding e join profile p on p.id = e.profile_id
                where e.kind = %s and e.profile_id <> %s and %s = any(p.modes)
                  and (%s or not p.synthetic)
                order by (e.v::vector({dim})) <#> %s::vector({dim})
                limit %s""",
            (np.asarray(query, dtype=np.float32), kind, exclude_id, mode, include_synthetic,
             np.asarray(query, dtype=np.float32), k))
        rows = [(r["profile_id"], float(r["s"])) for r in cur.fetchall()]
    conn.commit()
    return rows


def profile_meta(conn, ids: list[int], with_chart: list[int] = ()) -> dict[int, dict]:
    with conn.cursor() as cur:
        cur.execute("""select id, handle, place_label, modes, time_known, synthetic,
                              case when id = any(%s) then chart end as chart
                       from profile where id = any(%s)""", (list(with_chart), ids))
        return {r["id"]: r for r in cur.fetchall()}


def search_places(conn, q: str, limit: int = 8) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""select * from (
                         select id, name, country, lat, lon, tz, population,
                                greatest(similarity(ascii_name, %s), similarity(name, %s),
                                         word_similarity(%s, alt_names)) as sim
                         from place
                         where ascii_name %% %s or name %% %s or alt_names ilike %s) s
                       order by sim * ln(population + 10) desc limit %s""",
                    (q, q, q, q, q, f"%{q}%", limit))
        return cur.fetchall()


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False, default=str)

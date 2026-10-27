"""YAML доктрины -> таблицы Postgres + HNSW-индексы нужной размерности.
python -m scripts.load_doctrine doctrine/classic_modern_v1.yaml"""
import os
import sys

from astro import store
from astro.doctrine import doctrine_from_tables, tables_from_yaml
from astro.synastry import SynastryEngine


def main(path: str):
    text = open(path, encoding="utf-8").read()
    tables = tables_from_yaml(text)
    d = doctrine_from_tables(tables)          # валидация до записи
    D = SynastryEngine(d).D
    with store.connect(os.environ["DATABASE_URL"]) as conn:
        did = store.write_doctrine(conn, tables, text)
        idx = store.ensure_indexes(conn, d, D)
    print(f"doctrine {d.code} id={did}: {len(d.bodies)} bodies, {len(d.syn_aspect_w)} synastry weights, "
          f"{len(d.rules)} rules, embedding D={D}, indexes={len(idx)}")
    print("next: python -m scripts.calibrate  (and scripts.reembed if profiles exist)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "doctrine/classic_modern_v1.yaml")

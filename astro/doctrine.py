"""Доктрина: всё астрологическое знание как данные.

YAML -> нормализованные таблицы (те же строки, что лежат в Postgres) -> Doctrine.
БД     -> нормализованные таблицы -> Doctrine.
Один путь сборки объекта, поэтому тесты на YAML и прод на БД видят одно и то же.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import yaml

TABLES = (
    "body", "sign", "house", "rulership", "dignity", "aspect", "channel_map",
    "report_module", "synastry_dimension", "synastry_aspect_weight",
    "synastry_overlay_weight", "search_mode", "rule",
)


class DoctrineError(ValueError):
    pass


# ---------------------------------------------------------------- YAML -> tables
def _expand_foreach(rule: dict) -> list[dict]:
    loop = rule.get("foreach")
    if not loop:
        return [rule]
    (var, values), = loop.items()
    token = f"${var}"
    out = []
    for val in values:
        raw = json.dumps({k: v for k, v in rule.items() if k != "foreach"}, ensure_ascii=False)
        raw = raw.replace(f'"{token}"', json.dumps(val)).replace(token, str(val))
        out.append(json.loads(raw))
    return out


def tables_from_yaml(text: str) -> dict[str, Any]:
    y = yaml.safe_load(text)
    params = dict(y.get("params", {}))
    params["house_class_weight"] = y["house_class_weight"]
    params["aspect_exclude_pairs"] = y.get("aspect_exclude_pairs", [])
    params["fact_templates"] = y.get("fact_templates", {})
    params["dignity_labels"] = y.get("dignity_labels", {})
    for k in ("element_labels", "modality_labels", "level_labels"):
        params[k] = y.get(k, {})

    t: dict[str, Any] = {k: [] for k in TABLES}
    t["doctrine"] = {"code": y["code"], "title": y["title"], "params": params}

    for i, b in enumerate(y["bodies"]):
        t["body"].append({"ord": i, "code": b["code"], "kind": b["kind"], "source": b["source"],
                          "weight": float(b["weight"]), "needs_time": bool(b.get("needs_time", False)),
                          "label": b.get("label", {})})
    for s in y["signs"]:
        t["sign"].append({"idx": s["idx"], "code": s["code"], "element": s["element"],
                          "modality": s["modality"], "label": s.get("label", {})})
    for h in y["houses"]:
        t["house"].append({"num": h["num"], "class": h["class"], "label": h.get("label", {})})
    for sign_code, rows in y["rulerships"].items():
        for body, role, w in rows:
            t["rulership"].append({"sign_code": sign_code, "body_code": body, "role": role, "weight": float(w)})
    for body, sign_code, kind, score in y["dignities"]:
        t["dignity"].append({"body_code": body, "sign_code": sign_code, "kind": kind, "score": float(score)})
    for a in y["aspects"]:
        t["aspect"].append({"code": a["code"], "angle_deg": float(a["angle"]), "orb_deg": float(a["orb"]),
                            "weight": float(a["weight"]), "label": a.get("label", {})})
    for c in y.get("channels", []):
        t["channel_map"].append({"body_code": c["body"], "channel": int(c["channel"]),
                                 "arcana": c.get("arcana"), "verified": bool(c.get("verified", False))})
    for i, m in enumerate(y["report_modules"]):
        t["report_module"].append({"ord": i, "code": m["code"], "label": m.get("label", {}),
                                   "bodies": list(m.get("bodies", [])), "houses": list(m.get("houses", [])),
                                   "kinds": list(m.get("kinds", []))})

    profiles = y["aspect_profiles"]
    for dim, spec in y["synastry_dimensions"].items():
        t["synastry_dimension"].append({"code": dim, "label": spec.get("label", {})})
        acc: dict[tuple, float] = {}
        for p in spec.get("pairs", []):
            prof = profiles[p["profile"]]
            pairs = [tuple(p["pair"])]
            if p.get("symmetric") and p["pair"][0] != p["pair"][1]:
                pairs.append((p["pair"][1], p["pair"][0]))
            for recv, send in pairs:
                for asp, aw in prof.items():
                    key = (recv, send, asp)
                    acc[key] = acc.get(key, 0.0) + float(p["w"]) * float(aw)
        for (recv, send, asp), w in acc.items():
            if w != 0.0:
                t["synastry_aspect_weight"].append({"dimension": dim, "receiver_body": recv,
                                                    "sender_body": send, "aspect_code": asp, "weight": w})
        for send, h, w in spec.get("overlays", []):
            t["synastry_overlay_weight"].append({"dimension": dim, "sender_body": send,
                                                 "receiver_house": int(h), "weight": float(w)})
    for m in y["search_modes"]:
        t["search_mode"].append({"code": m["code"], "label": m.get("label", {}),
                                 "dim_weights": m["dims"], "nash_lambda": float(m["nash_lambda"])})
    for r in y.get("rules", []):
        for rr in _expand_foreach(r):
            t["rule"].append({"key": rr["key"], "module": rr["module"], "concept": rr["concept"],
                              "priority": float(rr.get("priority", 1.0)), "condition": rr["when"],
                              "label": rr.get("label", {}), "covers": list(rr.get("covers", [])),
                              "presents": rr.get("presents")})
    return t


# ---------------------------------------------------------------- tables -> Doctrine
@dataclass
class Body:
    ord: int
    code: str
    kind: str
    source: dict
    weight: float
    needs_time: bool
    label: dict


@dataclass
class Aspect:
    code: str
    angle_deg: float
    orb_deg: float
    weight: float
    label: dict


@dataclass
class Doctrine:
    code: str
    title: str
    params: dict
    bodies: list[Body]
    signs: list[dict]
    houses: list[dict]
    rulers: dict[str, list[tuple[str, str, float]]]       # sign_code -> [(body, role, weight)]
    dignities: dict[tuple[str, str], tuple[str, float]]  # (body, sign) -> (kind, score)
    aspects: list[Aspect]
    channels: dict[str, dict]
    modules: list[dict]
    dimensions: list[dict]
    syn_aspect_w: list[dict]
    syn_overlay_w: list[dict]
    modes: dict[str, dict]
    rules: list[dict]
    body_index: dict[str, int] = field(init=False)
    sign_by_idx: dict[int, dict] = field(init=False)
    sign_by_code: dict[str, dict] = field(init=False)
    aspect_by_code: dict[str, Aspect] = field(init=False)

    def __post_init__(self):
        self.bodies.sort(key=lambda b: b.ord)
        self.body_index = {b.code: i for i, b in enumerate(self.bodies)}
        self.sign_by_idx = {s["idx"]: s for s in self.signs}
        self.sign_by_code = {s["code"]: s for s in self.signs}
        self.aspect_by_code = {a.code: a for a in self.aspects}
        self._validate()

    # -- helpers used by the engine
    def body(self, code: str) -> Body:
        return self.bodies[self.body_index[code]]

    def primary_ruler(self, sign_code: str) -> str | None:
        for body, role, _ in self.rulers.get(sign_code, []):
            if role == "primary":
                return body
        return None

    def house_class(self, num: int) -> str:
        return next(h["class"] for h in self.houses if h["num"] == num)

    def label(self, obj: dict, locale: str = "ru") -> str:
        return obj.get("label", {}).get(locale) or obj.get("code", "")

    def _validate(self):
        bodies = set(self.body_index)
        signs = set(self.sign_by_code)
        errs = []
        if len(self.signs) != 12 or len(self.houses) != 12:
            errs.append("need exactly 12 signs and 12 houses")
        for s, rows in self.rulers.items():
            if s not in signs:
                errs.append(f"rulership: unknown sign {s}")
            errs += [f"rulership {s}: unknown body {b}" for b, _, _ in rows if b not in bodies]
        for (b, s) in self.dignities:
            if b not in bodies or s not in signs:
                errs.append(f"dignity: unknown {b}/{s}")
        dims = {d["code"] for d in self.dimensions}
        for r in self.syn_aspect_w:
            if r["receiver_body"] not in bodies or r["sender_body"] not in bodies:
                errs.append(f"synastry weight: unknown body in {r}")
            if r["aspect_code"] not in self.aspect_by_code:
                errs.append(f"synastry weight: unknown aspect {r['aspect_code']}")
            if r["dimension"] not in dims:
                errs.append(f"synastry weight: unknown dimension {r['dimension']}")
        for r in self.syn_overlay_w:
            if r["sender_body"] not in bodies:
                errs.append(f"overlay: unknown body {r['sender_body']}")
        for m in self.modes.values():
            errs += [f"mode {m['code']}: unknown dimension {d}" for d in m["dim_weights"] if d not in dims]
        for b in self.bodies:
            src = b.source
            if "offset_of" in src and src["offset_of"] not in bodies:
                errs.append(f"body {b.code}: offset_of unknown body")
        if errs:
            raise DoctrineError("; ".join(errs))


def doctrine_from_tables(t: dict[str, Any]) -> Doctrine:
    rulers: dict[str, list] = {}
    for r in t["rulership"]:
        rulers.setdefault(r["sign_code"], []).append((r["body_code"], r["role"], float(r["weight"])))
    return Doctrine(
        code=t["doctrine"]["code"],
        title=t["doctrine"]["title"],
        params=t["doctrine"]["params"],
        bodies=[Body(r["ord"], r["code"], r["kind"], r["source"], float(r["weight"]), bool(r["needs_time"]),
                     r["label"]) for r in t["body"]],
        signs=sorted(t["sign"], key=lambda s: s["idx"]),
        houses=sorted(t["house"], key=lambda h: h["num"]),
        rulers=rulers,
        dignities={(r["body_code"], r["sign_code"]): (r["kind"], float(r["score"])) for r in t["dignity"]},
        aspects=[Aspect(r["code"], float(r["angle_deg"]), float(r["orb_deg"]), float(r["weight"]), r["label"])
                 for r in t["aspect"]],
        channels={r["body_code"]: r for r in t["channel_map"]},
        modules=sorted(t["report_module"], key=lambda m: m["ord"]),
        dimensions=t["synastry_dimension"],
        syn_aspect_w=t["synastry_aspect_weight"],
        syn_overlay_w=t["synastry_overlay_weight"],
        modes={m["code"]: m for m in t["search_mode"]},
        rules=t["rule"],
    )


def load_yaml(path: str) -> Doctrine:
    with open(path, encoding="utf-8") as f:
        return doctrine_from_tables(tables_from_yaml(f.read()))

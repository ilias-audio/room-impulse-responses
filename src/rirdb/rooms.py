"""Room categories, IR-kind corrections and room metadata.

Each room gets a `category` from an ordered list of keyword rules applied to
its label, key and category hint (dataset folder names), optionally a
corrected `ir_kind` (outdoor, virtual, scale_model, ...). Curated overrides in
registry/rooms/<dataset>.csv win over the rules. Dataset-specific enrichers add
metadata such as room volume where the dataset publishes it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from rirdb import paths

# (pattern, category, ir_kind override). Order matters: first match wins.
RULES: list[tuple[str, str, str | None]] = [
    (r"auraliz|virtual|reconstruction|waveguide|simulat", "virtual", "virtual"),
    (r"scale[-_ ]?model", "scale_model", "scale_model"),
    (r"(?<!sound-sculpture-iceland-)-model$|_model$", "virtual", "virtual"),
    (r"slinky|spring|plate reverb|telephone|speaker", "device", "device"),
    (r"anechoic|(^|[-_ ])ane($|[-_ ])", "anechoic", "anechoic"),
    (r"(^|[-_ ])(car|train|bus)([-_ ]|$)|vehicle", "vehicle", "vehicle"),
    (r"cave|crag|mine|dungeon|tomb|crypt|cistern|bunker|cellar|maes-howe|newgrange|underground", "underground", None),
    (r"outside|outdoor|nature|forest|wood|park(?!ing)|street|field|beach|glacier|canyon|trollers-gill|"
     r"campground|backyard|quarry|valley|gorge|lake|mountain|desert", "outdoor", "outdoor"),
    (r"tunnel|underpass|bridge|arch|culvert", "tunnel_underpass", None),
    (r"church|cathedral|chapel|minster|abbey|shrine|parish|baptist|episcopal|mosque|temple|synagogue|basilica|"
     r"aula[-_ ]carolina", "worship", None),
    (r"concert|symphony|konzert|philharmon|musikverein|recital|brahmssaal|auditorium[-_ ]arvedi|arvedi", "concert_hall", None),
    (r"theatre|theater|auditorium|opera|sommertheater", "theatre_auditorium", None),
    (r"studio|booth|live[-_ ]room|listening|control[-_ ]room|drum", "studio_booth", None),
    (r"stair", "stairwell", None),
    (r"lecture|classroom|seminar|school|class", "lecture_classroom", None),
    (r"office|meeting|conference|council|typing", "office_meeting", None),
    (r"living|bedroom|kitchen|bathroom|shower|dining[-_ ]?room|diningroom|home|house|apartment|hotel|garage|"
     r"laundry|closet|toilet", "domestic", None),
    (r"restaurant|bar|pub|cafe|coffee|pizzeria|ice[-_ ]?cream|fast[-_ ]?food|supermarket|supermerket|store|shop|"
     r"mall|dininghall|diner|wine", "hospitality_retail", None),
    (r"gym|sports|pool|swimming|tennis|yoga|rink|bowling|recreation|court", "sports_leisure", None),
    (r"station|terminal|airport|subway|platform", "transport_hub", None),
    (r"factory|warehouse|reactor|kiln|parking|workshop|hangar|industrial", "industrial", None),
    (r"tower|castle|dome|monument|sculpture|mausoleum|palace", "large_structure", None),
    (r"corridor|hallway|hall[-_ ]way|lobby|foyer|atrium|lounge|entrance", "circulation", None),
    (r"museum|gallery|library|octagon|guildhall|club|hub|hall|building", "public_interior", None),
]
_COMPILED = [(re.compile(p, re.I), c, k) for p, c, k in RULES]

# dataset folder names -> category when no keyword matches (EchoThief folders, ...)
HINTS = {
    "Nature": ("outdoor", "outdoor"), "Underground": ("underground", None), "Underpasses": ("tunnel_underpass", None),
    "Stairwells": ("stairwell", None), "Venues": ("theatre_auditorium", None), "Recreation": ("sports_leisure", None),
    "Brutalism": ("public_interior", None),
}


def categorize(room_key: str, label: str | None, hint: str | None) -> tuple[str, str | None]:
    text = " ".join(str(t) for t in (room_key, label or "") if t)
    for rx, cat, kind in _COMPILED:
        if rx.search(text):
            return cat, kind
    if hint and hint in HINTS:
        return HINTS[hint]
    return "unknown", None


# ------------------------------------------------------------ enrichers
def _but_env_meta(root: Path) -> pd.DataFrame:
    """BUT ReverbDB env_meta.txt: type, description, dimensions, volume, materials."""
    rows = []
    for f in sorted(root.glob("*/env_meta.txt")):
        meta = {}
        for line in f.read_text(errors="replace").splitlines():
            if line.startswith("$") and "\t" in line:
                k, v = line[1:].split("\t", 1)
                meta[k.strip()] = v.strip()
        rows.append({
            "room_key": re.sub(r"[^a-z0-9]+", "-", f.parent.name.lower()).strip("-"),
            "volume_m3": pd.to_numeric(meta.get("EnvVolume"), errors="coerce"),
            "dims_m": " x ".join(meta.get(k, "") for k in ("EnvDepth", "EnvWidth", "EnvHeight")),
            "description": " ".join(filter(None, [meta.get("EnvType"), meta.get("EnvSubType"), meta.get("EnvDescription")])),
            "materials": ", ".join(f"{k[6:].lower()}: {meta[k]}" for k in ("EnvMatWall", "EnvMatFloor", "EnvMatCeiling") if meta.get(k)),
            "bg_noise_dba": pd.to_numeric(meta.get("EnvBCKNoiseLevel"), errors="coerce"),
            "type_hint": meta.get("EnvType", ""),
        })
    return pd.DataFrame(rows)


ENRICHERS = {"but_reverb": _but_env_meta}


def enrich_rooms(dataset_id: str, rooms: pd.DataFrame) -> pd.DataFrame:
    """Add category / ir_kind (rules, then curated CSV) and published room metadata."""
    rooms = rooms.copy()
    if dataset_id in ENRICHERS:
        meta = ENRICHERS[dataset_id](paths.files_dir(dataset_id))
        if not meta.empty:
            rooms = rooms.merge(meta, on="room_key", how="left")
            # the published room type is a better hint than the folder name
            rooms["room_label"] = rooms["room_label"].where(rooms.get("type_hint", "").fillna("") == "",
                                                            rooms["room_label"] + " (" + rooms["type_hint"].fillna("") + ")")
    cats = rooms.apply(lambda r: categorize(r["room_key"], " ".join(str(v) for v in (r.get("room_label"), r.get("description")) if isinstance(v, str)),
                                            r.get("category_hint")), axis=1)
    rooms["category"] = [c for c, _ in cats]
    rooms["ir_kind"] = [k or cur for (_, k), cur in zip(cats, rooms["ir_kind"])]
    cur = paths.REGISTRY_DIR / "rooms" / f"{dataset_id}.csv"
    if cur.exists():
        over = pd.read_csv(cur, dtype=str).fillna("")
        for _, o in over.iterrows():
            m = rooms["room_key"] == o["room_key"]
            for col in ("category", "ir_kind", "room_label", "note"):
                if col in o and o[col]:
                    rooms.loc[m, col] = o[col]
            if "volume_m3" in o and o["volume_m3"]:
                rooms.loc[m, "volume_m3"] = float(o["volume_m3"])
    return rooms

"""Generic adapter for datasets stored as audio files in a directory tree.

Registry parameters (adapter.params), all optional:
  glob:        file pattern relative to files/ (default "**/*.wav")
  exclude:     regex on the relative path (default: macOS junk)
  pattern:     regex with named groups room, src, rcv, cond, label (on the relpath)
  room_from:   "pattern" | "parent" | "file" | "dataset"  (default: pattern if it
               has a room group, else "file": every file is its own space)
  category_from: "parent" | "grandparent" | None  -> category_hint
  roles:       {n_channels: [role, ...]} e.g. {1: [omni], 2: [SL, SR], 4: [W, X, Y, Z]}
  capture_format: overrides the per-channel-count default
  channel_formats: {n_channels: capture_format}
  sh_norm:     FuMa | SN3D | N3D (for B-format files)
  orientation_known: bool (default true)
  ir_kind_from_regex: {regex: ir_kind} applied to the relpath (first match wins)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

import numpy as np
import soundfile as sf

from rirdb.adapters.base import IRRecord, slug

DEFAULT_EXCLUDE = r"(^|/)(__MACOSX|\._)|/\.DS_Store$"
DEFAULT_ROLES = {1: ["omni"], 2: ["SL", "SR"], 4: ["W", "X", "Y", "Z"]}
DEFAULT_FORMATS = {1: "mono_omni", 2: "stereo", 4: "foa_fuma"}


class WavTreeAdapter:
    def iter_records(self, dataset, root: Path) -> Iterator[IRRecord]:
        p = dataset.adapter.params
        exclude = re.compile(p.get("exclude", DEFAULT_EXCLUDE))
        pattern = re.compile(p["pattern"]) if p.get("pattern") else None
        room_from = p.get("room_from") or ("pattern" if pattern is not None and "room" in pattern.groupindex else "file")
        roles_map = {int(k): v for k, v in (p.get("roles") or {}).items()} or DEFAULT_ROLES
        fmt_map = {int(k): v for k, v in (p.get("channel_formats") or {}).items()}
        kinds = [(re.compile(rx), kind) for rx, kind in (p.get("ir_kind_from_regex") or {}).items()]
        default_kind = dataset.ir_kinds[0] if dataset.ir_kinds else "room"
        files = sorted(root.glob(p.get("glob", "**/*.wav")))
        for f in files:
            rel = f.relative_to(root).as_posix()
            if exclude.search(rel) or not f.is_file():
                continue
            try:
                info = sf.info(str(f))
            except RuntimeError:
                continue
            m = pattern.search(rel) if pattern else None
            if pattern is not None and m is None:
                continue
            g = m.groupdict() if m else {}
            stem = Path(rel).stem
            if room_from == "pattern":
                room = g.get("room") or "unknown"
            elif room_from == "parent":
                room = Path(rel).parent.name
            elif room_from == "dataset":
                room = dataset.id
            else:
                room = stem
            n_ch = info.channels
            roles = roles_map.get(n_ch) or [f"ch{i}" for i in range(n_ch)]
            if len(roles) != n_ch:
                roles = [f"ch{i}" for i in range(n_ch)]
            fmt = p.get("capture_format") or fmt_map.get(n_ch) or DEFAULT_FORMATS.get(n_ch, "array_raw")
            cat_from = p.get("category_from")
            category = None
            if cat_from == "parent":
                category = Path(rel).parent.name
            elif cat_from == "grandparent":
                category = Path(rel).parent.parent.name
            kind = next((k for rx, k in kinds if rx.search(rel)), default_kind)
            yield IRRecord(
                dataset_id=dataset.id,
                local_key=rel,
                room_key=slug(room),
                capture_format=fmt,
                channel_roles=tuple(roles),
                fs=int(info.samplerate),
                n_samples=int(info.frames),
                locator={"relpath": rel, "container": "audio"},
                condition_key=g.get("cond"),
                src_key=g.get("src"),
                rcv_key=g.get("rcv"),
                sh_norm=p.get("sh_norm") if fmt.startswith("foa") else None,
                orientation_known=bool(p.get("orientation_known", True)),
                room_label=g.get("label") or room,
                category_hint=category,
                ir_kind=kind,
                extra={"subtype": info.subtype},
            )

    def load(self, locator: dict, root: Path) -> tuple[np.ndarray, int]:
        x, fs = sf.read(str(root / locator["relpath"]), dtype="float64", always_2d=True)
        return x.T, int(fs)

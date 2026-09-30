"""Adapters for datasets whose layout needs code rather than a filename regex."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Iterator

import numpy as np
import soundfile as sf

from rirdb.adapters.base import IRRecord, slug
from rirdb.adapters.wav_tree import DEFAULT_EXCLUDE


# ---------------------------------------------------------------- OpenAIR
class OpenAirAdapter:
    """OpenAIR: files/<space>/<format folder>/<ir>.wav.

    Only IR folders are indexed (B-format, mono, stereo, 5.1, HOA, averaged or
    individual IR takes, scale models); sweeps, auralizations, convolution
    examples, pictures and data tables are skipped. Positions are often
    published in several formats (mono is usually W of the B-format), so one
    format per space is marked `preferred` (B-format > mono > stereo > other)
    for corpus statistics.
    """

    SKIP = re.compile(r"data tables|example|auraliz|sweep|ess|video|pic|image|virtual|recreation", re.I)
    PRIORITY = ("foa_fuma", "mono_omni", "stereo")

    @staticmethod
    def _format(folder: str, n_ch: int) -> tuple[str, list[str], str]:
        f = folder.lower()
        kind = "scale_model" if "scalemodel" in f.replace("_", "").replace("-", "") else "room"
        if n_ch == 4 and ("b-format" in f or "bformat" in f):
            return "foa_fuma", ["W", "X", "Y", "Z"], kind
        if n_ch == 16:
            # 3rd-order Ambisonics; normalisation not documented -> no Y role, so JLF is not computed
            return "hoa_sh", ["W"] + [f"ACN{i}" for i in range(1, 16)], kind
        if n_ch == 1:
            return "mono_omni", ["omni"], kind
        if n_ch == 2:
            return "stereo", ["SL", "SR"], kind
        if n_ch == 6:
            return "array_raw", ["sur_L", "sur_R", "sur_C", "sur_LFE", "sur_Ls", "sur_Rs"], kind
        return "array_raw", [f"ch{i}" for i in range(n_ch)], kind

    def iter_records(self, dataset, root: Path) -> Iterator[IRRecord]:
        exclude = re.compile(DEFAULT_EXCLUDE)
        recs: list[IRRecord] = []
        for f in sorted(root.glob("*/*/*.wav")) + sorted(root.glob("*/*/*.WAV")):
            rel = f.relative_to(root).as_posix()
            space, folder, _ = rel.split("/", 2)
            if exclude.search(rel) or self.SKIP.search(folder):
                continue
            try:
                info = sf.info(str(f))
            except RuntimeError:
                continue
            if info.frames / info.samplerate > 30:        # not an IR (long recordings)
                continue
            fmt, roles, kind = self._format(folder, info.channels)
            recs.append(IRRecord(
                dataset_id=dataset.id, local_key=rel, room_key=slug(space), capture_format=fmt,
                channel_roles=tuple(roles), fs=int(info.samplerate), n_samples=int(info.frames),
                locator={"relpath": rel, "container": "audio"}, sh_norm="FuMa" if fmt == "foa_fuma" else None,
                orientation_known=False, room_label=space.replace("-", " "), ir_kind=kind,
                condition_key=slug(folder), rcv_key=Path(rel).stem,
                extra={"subtype": info.subtype, "openair_folder": folder,
                       "reference_role": "sur_C" if fmt == "array_raw" and info.channels == 6 else None}))
        by_space = defaultdict(set)
        for r in recs:
            by_space[r.room_key].add(r.capture_format)
        for r in recs:
            fmts = by_space[r.room_key]
            best = next((p for p in self.PRIORITY if p in fmts), sorted(fmts)[0])
            r.extra["preferred"] = r.capture_format == best and r.ir_kind == "room"
            yield r

    def load(self, locator: dict, root: Path):
        x, fs = sf.read(str(root / locator["relpath"]), dtype="float64", always_2d=True)
        return x.T, int(fs)


# ---------------------------------------------------------------- Aachen AIR
class AirMatAdapter:
    """Aachen AIR 1.4 .mat files, one ear per file; pairs are joined into one record.

    air_binaural_{room}_{channel 0=right 1=left}_{head 0/1}_{rir_no}[_{azimuth}][_{x}].mat
    air_phone_[BT_]{room}_{hhp|hfrp}_{channel}.mat (dual-mic phone mock-up)
    """

    BIN = re.compile(r"air_binaural_(?P<room>[a-z_]+?)_(?P<ch>[01])_(?P<head>[01])_(?P<rir>\d+)(?P<rest>(?:_\d+)*)\.mat$")
    PHONE = re.compile(r"air_phone_(?P<bt>BT_)?(?P<room>[a-z0-9_]+?)_(?P<pos>hhp|hfrp)_(?P<ch>[01])\.mat$")

    def iter_records(self, dataset, root: Path) -> Iterator[IRRecord]:
        groups: dict[tuple, dict] = defaultdict(dict)
        meta: dict[tuple, dict] = {}
        for f in sorted(root.rglob("air_*.mat")):
            rel = f.relative_to(root).as_posix()
            if m := self.BIN.search(f.name):
                key = ("binaural", m["room"], m["head"], m["rir"], m["rest"])
                groups[key]["L" if m["ch"] == "1" else "R"] = rel
                meta[key] = m.groupdict()
            elif m := self.PHONE.search(f.name):
                key = ("phone", m["room"], m["pos"], m["bt"] or "", "")
                groups[key][f"mic_{m['ch']}"] = rel
                meta[key] = m.groupdict()
        for key, chans in sorted(groups.items()):
            kind, room = key[0], key[1]
            g = meta[key]
            if kind == "binaural":
                if set(chans) != {"L", "R"}:
                    continue
                head = g["head"] == "1"
                roles = ("L", "R") if head else ("SL", "SR")
                fmt = "binaural" if head else "stereo"
                files = [chans["L"], chans["R"]]
                rest = [p for p in g["rest"].split("_") if p]
                cond = f"head{g['head']}"
                rcv = f"rir{g['rir']}" + (f"_az{rest[0]}" if rest else "")
            else:
                roles = ("mic_0", "mic_1")
                fmt = "array_raw"
                files = [chans.get("mic_0"), chans.get("mic_1")]
                if None in files:
                    continue
                cond = f"phone_{g['pos']}{'_BT' if g['bt'] else ''}"
                rcv = g["pos"]
            h = self._read(root / files[0])
            yield IRRecord(
                dataset_id=dataset.id, local_key="|".join(files), room_key=slug(room), capture_format=fmt,
                channel_roles=roles, fs=h[1], n_samples=h[0].size,
                locator={"files": files, "container": "air_mat"}, condition_key=cond, rcv_key=rcv,
                room_label=room.replace("_", " "), extra={"air_type": kind})

    @staticmethod
    def _read(path: Path) -> tuple[np.ndarray, int]:
        import scipy.io

        m = scipy.io.loadmat(str(path), squeeze_me=True, struct_as_record=False)
        fs = int(getattr(m["air_info"], "fs", 48000))
        return np.asarray(m["h_air"], dtype=np.float64).ravel(), fs

    def load(self, locator: dict, root: Path):
        chans = [self._read(root / f) for f in locator["files"]]
        n = min(c[0].size for c in chans)
        return np.vstack([c[0][:n] for c in chans]), chans[0][1]


# ---------------------------------------------------------------- OpenSLR 28
class OpenSLR28Adapter:
    """Real RIRs of OpenSLR 28 (16 kHz): REVERB 2014 and RWCP. AIR copies are
    skipped (the full-rate originals are the aachen_air dataset)."""

    RVB = re.compile(r"RVB2014_type(?P<t>\d)_rir_(?P<room>[a-z]+room\d)_(?P<dist>near|far)_angl(?P<ang>[ab])\.wav$")
    RWCP = re.compile(r"RWCP_type(?P<t>\d)_rir_(?P<array>[a-z]+)_(?P<room>[a-z0-9]+)_imp(?P<ang>\d+|_rev)\.wav$")
    RWCP_LR = re.compile(r"RWCP_type4_rir_(?P<ang>[mp]?\d+)(?P<ch>[lr])\.wav$")   # left/right pairs per angle

    def iter_records(self, dataset, root: Path) -> Iterator[IRRecord]:
        base = root / "RIRS_NOISES" / "real_rirs_isotropic_noises"
        pairs: dict[str, dict] = defaultdict(dict)
        for f in sorted(base.glob("RWCP_type4_rir_*.wav")):
            if m := self.RWCP_LR.search(f.name):
                pairs[m["ang"]][m["ch"]] = f.relative_to(root).as_posix()
        for ang, lr in sorted(pairs.items()):
            if set(lr) != {"l", "r"}:
                continue
            info = sf.info(str(root / lr["l"]))
            yield IRRecord(
                dataset_id=dataset.id, local_key=f"{lr['l']}|{lr['r']}", room_key="rwcp-type4",
                capture_format="stereo", channel_roles=("SL", "SR"), fs=int(info.samplerate),
                n_samples=int(info.frames), locator={"files": [lr["l"], lr["r"]], "container": "audio_pair"},
                condition_key="type4", src_key=f"az{ang}", room_label="rwcp type4", category_hint="rwcp",
                extra={"subtype": info.subtype, "family": "rwcp", "note": "left/right channel pair"})
        for f in sorted(base.glob("*.wav")):
            rel = f.relative_to(root).as_posix()
            if m := self.RVB.search(f.name):
                room, family = m["room"], "reverb2014"
                cond, src, rcv, kind = f"type{m['t']}", f"angle_{m['ang']}", m["dist"], "room"
            elif m := self.RWCP.search(f.name):
                room, family = m["room"], "rwcp"
                cond, src, rcv = f"type{m['t']}_{m['array']}", f"az{m['ang']}", m["array"]
                kind = "anechoic" if room == "ane" else "room"
            else:
                continue
            info = sf.info(str(f))
            roles = ["omni"] if info.channels == 1 else [f"mic_{i}" for i in range(info.channels)]
            yield IRRecord(
                dataset_id=dataset.id, local_key=rel, room_key=slug(f"{family}-{room}"),
                capture_format="mono_omni" if info.channels == 1 else "array_raw",
                channel_roles=tuple(roles), fs=int(info.samplerate), n_samples=int(info.frames),
                locator={"relpath": rel, "container": "audio"}, condition_key=cond, src_key=src, rcv_key=rcv,
                room_label=f"{family} {room}", category_hint=family, ir_kind=kind,
                extra={"subtype": info.subtype, "family": family})

    def load(self, locator: dict, root: Path):
        if "files" in locator:
            chans = [sf.read(str(root / f), dtype="float64", always_2d=True) for f in locator["files"]]
            n = min(c[0].shape[0] for c in chans)
            return np.vstack([c[0][:n, 0] for c in chans]), int(chans[0][1])
        x, fs = sf.read(str(root / locator["relpath"]), dtype="float64", always_2d=True)
        return x.T, int(fs)


# ---------------------------------------------------------------- SOFA
class SofaAdapter:
    """Generic SOFA (netCDF4/HDF5) adapter: one record per measurement M, all receivers R.

    Params: glob (default **/*.sofa), room_from (file|parent), roles (list for R
    receivers, default mic_i), capture_format, reference_role, sh_norm,
    orientation_known.
    """

    def iter_records(self, dataset, root: Path) -> Iterator[IRRecord]:
        import h5py

        p = dataset.adapter.params
        exclude = re.compile(p.get("exclude", DEFAULT_EXCLUDE))
        for f in sorted(root.glob(p.get("glob", "**/*.sofa"))):
            rel = f.relative_to(root).as_posix()
            if exclude.search(rel):
                continue
            with h5py.File(f, "r") as h:
                M, R, N = h["Data.IR"].shape
                fs = int(np.ravel(h["Data.SamplingRate"][()])[0])
                src = np.asarray(h["SourcePosition"]) if "SourcePosition" in h else None
                lis = np.asarray(h["ListenerPosition"]) if "ListenerPosition" in h else None
                conv = h.attrs.get("SOFAConventions", b"")
                conv = conv.decode() if isinstance(conv, bytes) else str(conv)
            roles = p.get("roles") or [f"mic_{i}" for i in range(R)]
            if len(roles) != R:
                roles = [f"mic_{i}" for i in range(R)]
            room = Path(rel).parent.name if p.get("room_from") == "parent" else Path(rel).stem
            for m in range(M):
                sp = tuple(src[m if src.shape[0] == M else 0]) if src is not None else None
                lp = tuple(lis[m if lis.shape[0] == M else 0]) if lis is not None else None
                yield IRRecord(
                    dataset_id=dataset.id, local_key=f"{rel}#{m}", room_key=slug(room),
                    capture_format=p.get("capture_format", "array_raw"), channel_roles=tuple(roles), fs=fs,
                    n_samples=int(N), locator={"relpath": rel, "container": "sofa", "m": m},
                    src_key=f"m{m}", src_pos=sp, rcv_pos=lp, sh_norm=p.get("sh_norm"),
                    orientation_known=bool(p.get("orientation_known", True)), room_label=room.replace("_", " "),
                    extra={"sofa_conventions": conv, "reference_role": p.get("reference_role")})

    def load(self, locator: dict, root: Path):
        import h5py

        with h5py.File(root / locator["relpath"], "r") as h:
            x = np.asarray(h["Data.IR"][locator["m"]], dtype=np.float64)
            fs = int(np.ravel(h["Data.SamplingRate"][()])[0])
        return np.atleast_2d(x), fs

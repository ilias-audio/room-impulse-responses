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


class SofaAdapter:
    """Generic SOFA (netCDF4/HDF5) adapter.

    Data.IR is (M, R, N) or (M, R, N, E): one record per measurement m (and
    emitter e), with all R receivers as channels. Settings come from
    `adapter.params`, or from a list `params.groups` of such dicts when one
    dataset mixes file types (e.g. BRIR and SRIR files):
      glob (default **/*.sofa), pattern (regex on the file name: groups room, rcv, src, cond),
      room_from (pattern|file|parent), roles (list of R), capture_format, reference_role,
      sh_norm, orientation_known, m_select (list of m indices, e.g. [0] = frontal head
      orientation for rotation-dense BRIR sets), first_per_source (keep only the first
      measurement at each distinct SourcePosition: drops repeated measurements), m_is (src
      (default) | rcv: what the measurement index enumerates), ir_kind. An all-zero
      SourcePosition is treated as unpublished.
    Loading reads one slice lazily via h5py.
    """

    def iter_records(self, dataset, root: Path) -> Iterator[IRRecord]:
        import h5py

        params = dataset.adapter.params
        groups = params.get("groups") or [params]
        exclude = re.compile(params.get("exclude", DEFAULT_EXCLUDE))
        for p in groups:
            pattern = re.compile(p["pattern"]) if p.get("pattern") else None
            for f in sorted(root.glob(p.get("glob", "**/*.sofa"))):
                rel = f.relative_to(root).as_posix()
                if exclude.search(rel):
                    continue
                g = {}
                if pattern is not None:
                    m_ = pattern.search(f.name)
                    if m_ is None:
                        continue
                    g = m_.groupdict()
                try:
                    with h5py.File(f, "r") as h:
                        shape = h["Data.IR"].shape
                        fs = int(np.ravel(h["Data.SamplingRate"][()])[0])
                        src = np.asarray(h["SourcePosition"]) if "SourcePosition" in h else None
                        if src is not None and not np.any(src):
                            src = None                # all zeros: source positions not published
                        lis = np.asarray(h["ListenerPosition"]) if "ListenerPosition" in h else None
                        conv = h.attrs.get("SOFAConventions", b"")
                        conv = conv.decode() if isinstance(conv, bytes) else str(conv)
                except OSError:
                    continue      # not HDF5 (e.g. a git-LFS pointer)
                M, R, N = shape[:3]
                E = shape[3] if len(shape) == 4 else None
                roles = p.get("roles") or [f"mic_{i}" for i in range(R)]
                if len(roles) != R:
                    roles = [f"mic_{i}" for i in range(R)]
                room_from = p.get("room_from") or ("pattern" if g.get("room") else "file")
                if room_from == "pattern":
                    room = g.get("room")
                elif room_from == "dataset":
                    room = p.get("room_default") or dataset.id
                elif room_from == "parent":
                    room = Path(rel).parent.name
                else:
                    room = Path(rel).stem
                ms = p.get("m_select") or range(M)
                first_per_source = bool(p.get("first_per_source")) and src is not None and src.ndim == 2 \
                    and src.shape[0] == M
                if first_per_source:        # repeated measurements: the first m at each SourcePosition
                    firsts: dict = {}
                    for m in range(M):
                        firsts.setdefault(tuple(np.round(src[m], 3)), m)
                    ms = sorted(firsts.values())
                es = range(E) if E else [None]
                for m in ms:
                    if m >= M:
                        continue
                    for e in es:
                        sp = tuple(src[m if src.shape[0] == M else 0]) if src is not None and src.ndim == 2 else None
                        lp = tuple(lis[m if lis.shape[0] == M else 0]) if lis is not None and lis.ndim == 2 else None
                        key = f"{rel}#{m}" + (f"#{e}" if e is not None else "")
                        yield IRRecord(
                            dataset_id=dataset.id, local_key=key, room_key=slug(room),
                            capture_format=p.get("capture_format", "array_raw"), channel_roles=tuple(roles), fs=fs,
                            n_samples=int(N), locator={"relpath": rel, "container": "sofa", "m": int(m), "e": e},
                            src_key=f"e{e}" if e is not None else (g.get("src") or (
                                "src_" + "_".join(f"{v:g}" for v in np.round(src[m], 2)) if first_per_source
                                else None if p.get("m_is") == "rcv" else f"m{m}")),
                            rcv_key=g.get("rcv") or (f"m{m}" if e is not None or p.get("m_is") == "rcv" else None),
                            condition_key=g.get("cond"), src_pos=sp, rcv_pos=lp, sh_norm=p.get("sh_norm"),
                            orientation_known=bool(p.get("orientation_known", True)),
                            room_label=str(room).replace("_", " "), ir_kind=p.get("ir_kind", "room"),
                            extra={"sofa_conventions": conv, "reference_role": p.get("reference_role"),
                                   "preferred": bool(p.get("preferred", True))})

    def load(self, locator: dict, root: Path):
        import h5py

        with h5py.File(root / locator["relpath"], "r") as h:
            d = h["Data.IR"]
            x = d[locator["m"], :, :, locator["e"]] if locator.get("e") is not None else d[locator["m"]]
            fs = int(np.ravel(h["Data.SamplingRate"][()])[0])
        return np.atleast_2d(np.asarray(x, dtype=np.float64)), fs


# ---------------------------------------------------------------- MATLAB arrays
class MatArrayAdapter:
    """IRs stored as N-d arrays in .mat files (e.g. IoSR BRIRs: brir[N, 2 ears, 24 speakers]).

    Params: glob, file_pattern (regex on file name; groups become keys), var,
    time_axis, channel_axis, record_axis (one record per index; None = one per file),
    roles, capture_format, fs, room_default, record_prefix.
    """

    def _arr(self, path: Path, var: str):
        import scipy.io

        try:
            return np.asarray(scipy.io.loadmat(str(path), variable_names=[var])[var])
        except NotImplementedError:          # v7.3 (HDF5)
            import h5py

            with h5py.File(path, "r") as h:
                return np.asarray(h[var]).T

    def iter_records(self, dataset, root: Path) -> Iterator[IRRecord]:
        p = dataset.adapter.params
        fpat = re.compile(p.get("file_pattern", r".*\.mat$"))
        for f in sorted(root.glob(p.get("glob", "**/*.mat"))):
            m_ = fpat.search(f.name)
            if not m_:
                continue
            g = m_.groupdict()
            rel = f.relative_to(root).as_posix()
            a = self._arr(f, p["var"])
            n = a.shape[p.get("time_axis", 0)]
            n_rec = a.shape[p["record_axis"]] if p.get("record_axis") is not None else 1
            roles = p.get("roles") or [f"mic_{i}" for i in range(a.shape[p.get("channel_axis", 1)])]
            for k in range(n_rec):
                yield IRRecord(
                    dataset_id=dataset.id, local_key=f"{rel}#{k}", room_key=slug(g.get("room") or p.get("room_default", "unknown")),
                    capture_format=p.get("capture_format", "array_raw"), channel_roles=tuple(roles), fs=int(p["fs"]),
                    n_samples=int(n), locator={"relpath": rel, "container": "mat", "k": k},
                    src_key=f"{p.get('record_prefix', 'rec')}{k + 1}", rcv_key=g.get("rcv"), condition_key=g.get("cond"),
                    room_label=str(g.get("room") or p.get("room_default", "")).replace("_", " "), extra={})

    def load(self, locator: dict, root: Path):
        p = self._params
        a = self._arr(root / locator["relpath"], p["var"])
        t_ax, c_ax, r_ax = p.get("time_axis", 0), p.get("channel_axis", 1), p.get("record_axis")
        if r_ax is not None:
            a = np.take(a, locator["k"], axis=r_ax)
            if c_ax > r_ax:
                c_ax -= 1
            if t_ax > r_ax:
                t_ax -= 1
        return np.moveaxis(a, (c_ax, t_ax), (0, 1)).astype(np.float64), int(p["fs"])


# ---------------------------------------------------------------- N-d arrays (HDF5 / NPY)
class NdArrayAdapter:
    """Dense IR tensors in HDF5 datasets or .npy files (MIRACLE, SRIRACHA, MeshRIR, MP-RIR, ...).

    Params (all per `groups` entry, or top level):
      glob                 files to read

      array                HDF5 dataset path (h5) or MATLAB v5 variable (mat)
      array_pattern        regex: every matching top-level HDF5 array becomes a condition
      container            h5 | npy | mat (MATLAB v5, loaded whole)
      time_axis            axis holding samples
      channel_axis         axis holding simultaneous channels of one record (optional)
      record_axes          axes enumerated into records (all remaining axes if omitted)
      fs                   sampling rate, or fs_attr (HDF5 attribute path "dataset@attr" / "@attr")
      pattern              regex on the file name (groups room, cond, src, rcv)
      room_default, capture_format, roles, reference_role, ir_kind
      channels             indices along channel_axis to keep (e.g. one ear pair of several)
      record_is            rcv (default) | src: what the record index enumerates, for the position keys
      crop_s               keep only the first crop_s seconds (e.g. long deconvolutions whose tail is non-stationary noise)
      positions            {src|rcv: {array: path, axis_of: record axis index}} (optional, h5)
    Records are the Cartesian product of record-axis indices; loading slices lazily.
    """

    def _groups(self, params):
        return params.get("groups") or [params]

    _mat_cache: dict = {}

    def _open(self, path: Path, g: dict, array: str | None = None):
        array = array or g.get("array")
        if g.get("container", "h5") == "npy":
            return np.load(path, mmap_mode="r"), None
        if g["container"] == "mat":             # MATLAB v5: load once per file (small files)
            key = (str(path), array)
            if key not in self._mat_cache:
                import scipy.io

                self._mat_cache.clear()
                self._mat_cache[key] = np.asarray(scipy.io.loadmat(str(path), variable_names=[array])[array])
            return self._mat_cache[key], None
        import h5py

        try:
            import hdf5plugin  # noqa: F401
        except ImportError:
            pass
        h = h5py.File(path, "r")
        return h[array], h

    def _fs(self, path: Path, g: dict) -> int:
        if "fs" in g:
            return int(g["fs"])
        if "fs_var" in g:                              # MATLAB v5 variable
            import scipy.io

            return int(np.ravel(scipy.io.loadmat(str(path), variable_names=[g["fs_var"]])[g["fs_var"]])[0])
        import h5py

        with h5py.File(path, "r") as h:
            if "fs_dataset" in g:                     # scalar dataset, e.g. metadata/sampling_rate
                return int(np.ravel(h[g["fs_dataset"]][()])[0])
            ds, _, attr = g["fs_attr"].partition("@")
            obj = h[ds] if ds else h
            return int(np.ravel(obj.attrs[attr])[0])

    def iter_records(self, dataset, root: Path) -> Iterator[IRRecord]:
        import itertools

        for gi, g in enumerate(self._groups(dataset.adapter.params)):
            pattern = re.compile(g["pattern"]) if g.get("pattern") else None
            for f in sorted(root.glob(g["glob"])):
                m_ = pattern.search(f.relative_to(root).as_posix()) if pattern else None
                if pattern is not None and m_ is None:
                    continue
                gd = m_.groupdict() if m_ else {}
                rel = f.relative_to(root).as_posix()
                arrays = [g.get("array")]
                if g.get("array_pattern"):            # one HDF5 array per condition (e.g. dEchorate)
                    import h5py

                    with h5py.File(f, "r") as hh:
                        arrays = sorted(k for k in hh.keys() if re.fullmatch(g["array_pattern"], k))
                for array in arrays:
                    yield from self._records(dataset, g, gi, f, rel, gd, array, itertools)

    def _records(self, dataset, g, gi, f, rel, gd, array, itertools):
        arr, h = self._open(f, g, array)
        shape = arr.shape
        if h is not None:
            h.close()
        t_ax = g["time_axis"] % len(shape)
        c_ax = g.get("channel_axis")
        c_ax = None if c_ax is None else c_ax % len(shape)
        rec_axes = g.get("record_axes")
        rec_axes = [a % len(shape) for a in rec_axes] if rec_axes is not None else \
            [a for a in range(len(shape)) if a not in (t_ax, c_ax)]
        n_ch = len(g["channels"]) if g.get("channels") else (shape[c_ax] if c_ax is not None else 1)
        roles = g.get("roles") or (["omni"] if n_ch == 1 else [f"mic_{i}" for i in range(n_ch)])
        fs = self._fs(f, g)
        room = gd.get("room") or g.get("room_default") or dataset.id
        for idx in itertools.product(*[range(shape[a]) for a in rec_axes]):
            key = f"{rel}#" + (f"{array}#" if g.get("array_pattern") else "") + ",".join(map(str, idx))
            if g.get("record_is") == "src":
                src = "-".join(filter(None, [gd.get("src"), ",".join(map(str, idx))]))
                rcv = gd.get("rcv")
            else:
                src, rcv = gd.get("src"), gd.get("rcv") or ",".join(map(str, idx))
            yield IRRecord(
                dataset_id=dataset.id, local_key=key, room_key=slug(room),
                capture_format=g.get("capture_format", "mono_omni" if n_ch == 1 else "array_raw"),
                channel_roles=tuple(roles), fs=fs,
                n_samples=min(int(shape[t_ax]), int(round(g["crop_s"] * fs))) if g.get("crop_s") else int(shape[t_ax]),
                locator={"relpath": rel, "container": g.get("container", "h5"), "group": gi,
                         "idx": list(idx), "array": array},
                condition_key=gd.get("cond") or (array if g.get("array_pattern") else None),
                src_key=src, rcv_key=rcv,
                room_label=str(room).replace("_", " "), ir_kind=g.get("ir_kind", "room"),
                extra={"reference_role": g.get("reference_role")})

    def load(self, locator: dict, root: Path):
        g = self._groups(self._params)[locator.get("group", 0)]
        path = root / locator["relpath"]
        arr, h = self._open(path, g, locator.get("array"))
        try:
            shape = arr.shape
            t_ax = g["time_axis"] % len(shape)
            c_ax = g.get("channel_axis")
            c_ax = None if c_ax is None else c_ax % len(shape)
            rec_axes = g.get("record_axes")
            rec_axes = [a % len(shape) for a in rec_axes] if rec_axes is not None else \
                [a for a in range(len(shape)) if a not in (t_ax, c_ax)]
            sl = [slice(None)] * len(shape)
            for a, i in zip(rec_axes, locator["idx"]):
                sl[a] = i
            if g.get("crop_s"):
                sl[t_ax] = slice(0, int(round(g["crop_s"] * self._fs(path, g))))
            x = np.asarray(arr[tuple(sl)], dtype=np.float64)
            # remaining axes keep their relative order: put channels first, time last
            remaining = [a for a in range(len(shape)) if a not in rec_axes]
            if c_ax is None:
                x = x.reshape(1, -1)
            elif remaining.index(c_ax) > remaining.index(t_ax):
                x = x.T
            if g.get("channels"):
                x = np.atleast_2d(x)[list(g["channels"])]
        finally:
            if h is not None:
                h.close()
        return np.atleast_2d(x), self._fs(path, g)


# ---------------------------------------------------------------- TAU-SRIR DB
class TauSrirAdapter:
    """TAU-SRIR DB (MATLAB v7.3): rirs_<nn>_<room>.mat holds rirs(traj, height).{foa,mic},
    each [samples x 4 x DOAs] (HDF5: object references to (DOAs, 4, 7200) arrays, 24 kHz).
    One record per height x trajectory x DOA, FOA format (ACN W,Y,Z,X; SN3D)."""

    FS = 24000
    NAME = re.compile(r"rirs_(?P<n>\d+)_(?P<room>.+)\.mat$")

    def iter_records(self, dataset, root: Path) -> Iterator[IRRecord]:
        import h5py

        fmt = (self._params or {}).get("format", "foa")
        for f in sorted(root.glob("**/rirs_*.mat")):
            m_ = self.NAME.search(f.name)
            if not m_:
                continue
            rel = f.relative_to(root).as_posix()
            with h5py.File(f, "r") as h:
                refs = h["rirs"][fmt]
                for (hi, ti), ref in np.ndenumerate(refs[()]):
                    n_doa, n_ch, n = h[ref].shape
                    for k in range(n_doa):
                        yield IRRecord(
                            dataset_id=dataset.id, local_key=f"{rel}#{fmt}/{hi},{ti},{k}", room_key=slug(m_["room"]),
                            capture_format="foa_ambix" if fmt == "foa" else "tetra_raw",
                            channel_roles=("W", "Y", "Z", "X") if fmt == "foa" else ("m1", "m2", "m3", "m4"),
                            fs=self.FS, n_samples=int(n),
                            locator={"relpath": rel, "container": "tau_mat", "fmt": fmt, "hi": int(hi), "ti": int(ti), "k": k},
                            condition_key=f"height{hi + 1}", src_key=f"traj{ti + 1}_doa{k}", sh_norm="SN3D" if fmt == "foa" else None,
                            orientation_known=False, room_label=m_["room"].replace("_", " "), extra={})

    def load(self, locator: dict, root: Path):
        import h5py

        with h5py.File(root / locator["relpath"], "r") as h:
            ref = h["rirs"][locator["fmt"]][locator["hi"], locator["ti"]]
            x = np.asarray(h[ref][locator["k"]], dtype=np.float64)      # (4, 7200)
        return x, self.FS

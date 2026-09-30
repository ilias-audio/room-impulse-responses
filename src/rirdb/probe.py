"""Summarise what a fetched dataset actually contains (registry/probes/<id>.txt).

Adapters are written from this evidence: file types, directory layout, audio
headers (channels / fs / subtype / duration), and the internal structure of
HDF5 / NPY / MAT / SOFA containers.
"""

from __future__ import annotations

import collections
import io
from pathlib import Path

import numpy as np

from rirdb import paths

MAX_AUDIO_HEADERS = 3000
MAX_LIST = 40


def _tree(root: Path, depth: int = 3, per_dir: int = 12) -> list[str]:
    lines = []

    def walk(d: Path, level: int):
        if level > depth:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return
        dirs = [e for e in entries if e.is_dir()]
        files = [e for e in entries if e.is_file()]
        for e in dirs[:per_dir]:
            n = sum(1 for _ in e.rglob("*") if _.is_file())
            lines.append(f"{'  ' * level}{e.name}/  ({n} files)")
            walk(e, level + 1)
        if len(dirs) > per_dir:
            lines.append(f"{'  ' * level}... {len(dirs) - per_dir} more dirs")
        for e in files[: per_dir // 2]:
            lines.append(f"{'  ' * level}{e.name}  [{e.stat().st_size / 1e6:.2f} MB]")
        if len(files) > per_dir // 2:
            lines.append(f"{'  ' * level}... {len(files) - per_dir // 2} more files")

    walk(root, 0)
    return lines


def _audio_summary(files: list[Path], out: io.StringIO) -> None:
    import soundfile as sf

    combos = collections.Counter()
    durations = []
    bad = 0
    for f in files[:MAX_AUDIO_HEADERS]:
        try:
            i = sf.info(str(f))
        except RuntimeError:
            bad += 1
            continue
        combos[(i.channels, i.samplerate, i.subtype)] += 1
        durations.append(i.frames / i.samplerate)
    out.write(f"audio headers read: {len(durations)} of {len(files)} ({bad} unreadable)\n")
    for (ch, sr, st), n in combos.most_common(12):
        out.write(f"  {n:6d} x  {ch} ch  {sr} Hz  {st}\n")
    if durations:
        d = np.array(durations)
        out.write(f"  duration s: min {d.min():.3f}  median {np.median(d):.3f}  max {d.max():.3f}\n")


def _h5_summary(f: Path, out: io.StringIO) -> None:
    import h5py

    try:
        import hdf5plugin  # noqa: F401  (registers compression filters)
    except ImportError:
        pass
    out.write(f"-- {f.name}\n")
    with h5py.File(f, "r") as h:
        for k, v in list(h.attrs.items())[:10]:
            out.write(f"   @{k} = {str(v)[:120]}\n")
        count = [0]

        def visit(name, obj):
            if count[0] >= MAX_LIST:
                return
            count[0] += 1
            if isinstance(obj, h5py.Dataset):
                out.write(f"   {name}: {obj.shape} {obj.dtype}\n")
            else:
                out.write(f"   {name}/\n")

        h.visititems(visit)


def _npy_summary(f: Path, out: io.StringIO) -> None:
    try:
        a = np.load(f, mmap_mode="r", allow_pickle=False)
        if isinstance(a, np.lib.npyio.NpzFile):
            out.write(f"-- {f.name}: npz {[(k, a[k].shape, a[k].dtype) for k in list(a.files)[:20]]}\n")
        else:
            out.write(f"-- {f.name}: {a.shape} {a.dtype}\n")
    except ValueError as e:
        out.write(f"-- {f.name}: {e}\n")


def _mat_summary(f: Path, out: io.StringIO) -> None:
    import scipy.io

    try:
        out.write(f"-- {f.name}: {scipy.io.whosmat(str(f))[:20]}\n")
    except (NotImplementedError, ValueError):
        out.write(f"-- {f.name}: MATLAB v7.3 (HDF5)\n")
        _h5_summary(f, out)


def _sofa_summary(f: Path, out: io.StringIO) -> None:
    import sofar

    try:
        s = sofar.read_sofa(str(f), verify=False, verbose=False)
        out.write(f"-- {f.name}: {s.GLOBAL_SOFAConventions} v{s.GLOBAL_SOFAConventionsVersion}; "
                  f"Data.IR {np.shape(getattr(s, 'Data_IR', []))}; fs {np.ravel(getattr(s, 'Data_SamplingRate', [np.nan]))[0]}\n")
    except Exception as e:  # noqa: BLE001 - probe must never crash on odd files
        out.write(f"-- {f.name}: unreadable SOFA ({e})\n")


def probe(dataset_id: str) -> Path:
    root = paths.files_dir(dataset_id)
    out = io.StringIO()
    out.write(f"# probe {dataset_id}\n# root: {root}\n\n")
    files = [p for p in root.rglob("*") if p.is_file() and "__MACOSX" not in p.parts and not p.name.startswith("._")]
    exts = collections.Counter(p.suffix.lower() or "<none>" for p in files)
    total = sum(p.stat().st_size for p in files)
    out.write(f"{len(files)} files, {total / 1e9:.2f} GB\n")
    out.write("extensions: " + ", ".join(f"{e} {n}" for e, n in exts.most_common(20)) + "\n\n## tree\n")
    out.write("\n".join(_tree(root)) + "\n\n## audio\n")
    audio = sorted(p for p in files if p.suffix.lower() in (".wav", ".flac", ".aif", ".aiff"))
    if audio:
        _audio_summary(audio, out)
    for label, suffixes, fn in (
        ("hdf5", (".h5", ".hdf5"), _h5_summary),
        ("npy", (".npy", ".npz"), _npy_summary),
        ("mat", (".mat",), _mat_summary),
        ("sofa", (".sofa",), _sofa_summary),
    ):
        sel = sorted(p for p in files if p.suffix.lower() in suffixes)
        if sel:
            out.write(f"\n## {label} ({len(sel)} files; first {min(len(sel), 5)})\n")
            for f in sel[:5]:
                fn(f, out)
    dest = paths.PROBES_DIR / f"{dataset_id}.txt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(out.getvalue())
    return dest

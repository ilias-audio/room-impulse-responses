"""Check that every fetched dataset is complete and intact on disk.

Compares three committed records against RIRDB_ROOT:
  - registry/locks/<id>.lock.tsv       what should have been downloaded
  - raw/<id>/.ok/                      what was downloaded and verified
  - registry/manifests/<id>.files.tsv.gz  every extracted file with size + sha256

Quick mode checks presence and sizes; --full re-hashes every file. Missing
files usually mean the scratch purge; `repair` clears the markers so
`fetch/run.sh <id>` re-downloads them.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import shutil
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rirdb import paths
from rirdb.registry import Dataset

ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".tbz2", ".tar.bz2", ".tar.xz")


def _is_archive(name: str) -> bool:
    if name.endswith(ARCHIVE_SUFFIXES):
        return True
    # split-zip parts: x.z01, x.z02, ...
    stem, _, ext = name.rpartition(".")
    return bool(stem) and len(ext) == 3 and ext[0] == "z" and ext[1:].isdigit()


def _read_tsv(path: Path) -> list[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class DatasetReport:
    id: str
    wave: int | None
    stage: str = "unresolved"      # unresolved | resolved | fetched | extracted | inventoried
    lock_files: int = 0
    lock_bytes: int = 0
    manifest_files: int = 0
    manifest_bytes: int = 0
    missing: list[str] = field(default_factory=list)
    size_mismatch: list[str] = field(default_factory=list)
    hash_mismatch: list[str] = field(default_factory=list)
    unverified_downloads: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.missing or self.size_mismatch or self.hash_mismatch:
            return "CORRUPT" if (self.size_mismatch or self.hash_mismatch) else "MISSING"
        if self.stage == "unresolved":
            return "UNRESOLVED"
        if self.stage != "inventoried":
            return "INCOMPLETE"
        return "OK"


def verify_dataset(d: Dataset, full: bool = False, workers: int = 4) -> DatasetReport:
    rep = DatasetReport(id=d.id, wave=d.wave)
    lock = paths.LOCKS_DIR / f"{d.id}.lock.tsv"
    manifest = paths.MANIFESTS_DIR / f"{d.id}.files.tsv.gz"
    raw = paths.raw_dir(d.id)
    okdir = raw / ".ok"
    state = {}
    if paths.state_file(d.id).exists():
        state = json.loads(paths.state_file(d.id).read_text())

    if not lock.exists():
        return rep
    rep.stage = "resolved"
    rows = _read_tsv(lock)
    rep.lock_files = len(rows)
    rep.lock_bytes = sum(int(r["size"]) for r in rows if r["size"].isdigit())

    # 1. every locked download is verified (and present, unless an extracted archive)
    all_fetched = True
    for r in rows:
        rel = r["relpath"]
        if rel == "@mirror":
            continue
        marker = okdir / f"{rel}.ok"
        if not marker.exists():
            rep.unverified_downloads.append(rel)
            all_fetched = False
            continue
        if _is_archive(rel):
            if not (raw / "_archives" / rel).exists() and not (okdir / f"{rel}.extracted").exists():
                rep.missing.append(f"_archives/{rel}")
        else:
            p = raw / "files" / rel
            if not p.exists():
                rep.missing.append(rel)
            elif r["size"].isdigit() and p.stat().st_size != int(r["size"]):
                rep.size_mismatch.append(rel)
    if all_fetched and "fetched_at" in state:
        rep.stage = "fetched"
    if "extracted_at" in state and rep.stage == "fetched":
        rep.stage = "extracted"

    # 2. every file of the committed manifest is present (and intact)
    if manifest.exists():
        mrows = _read_tsv(manifest)
        rep.manifest_files = len(mrows)
        rep.manifest_bytes = sum(int(m["size"]) for m in mrows)
        to_hash = []
        files = raw / "files"
        for m in mrows:
            p = files / m["relpath"]
            if not p.exists():
                rep.missing.append(m["relpath"])
            elif p.stat().st_size != int(m["size"]):
                rep.size_mismatch.append(m["relpath"])
            elif full:
                to_hash.append((p, m["sha256"], m["relpath"]))
        if to_hash:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                for (p, want, rel), got in zip(to_hash, ex.map(_sha256, [t[0] for t in to_hash], chunksize=16)):
                    if got != want:
                        rep.hash_mismatch.append(rel)
        if rep.stage in ("extracted", "fetched") and "inventory" in state:
            rep.stage = "inventoried"
    elif rep.stage == "extracted":
        rep.notes.append("no manifest yet: run fetch/inventory.sh")
    return rep


def verify(datasets: list[Dataset], full: bool = False, workers: int = 4) -> list[DatasetReport]:
    return [verify_dataset(d, full=full, workers=workers) for d in datasets]


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return str(n)


def write_report(reports: list[DatasetReport], full: bool, out_dir: Path = paths.REPORTS_DIR / "verify") -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md_path, json_path = out_dir / f"{stamp}.md", out_dir / f"{stamp}.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "full" if full else "quick",
        "data_root": str(paths.data_root()),
        "datasets": [asdict(r) | {"status": r.status} for r in reports],
    }
    json_path.write_text(json.dumps(payload, indent=1) + "\n")

    lines = [
        f"# Verify report {stamp} ({payload['mode']})",
        "",
        f"Data root: `{paths.data_root()}`. Generated by `rirdb verify`.",
        "",
        "| dataset | wave | stage | status | locked files | on-disk files | size | problems |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        problems = []
        for label, items in (("missing", r.missing), ("size", r.size_mismatch),
                             ("hash", r.hash_mismatch), ("not fetched", r.unverified_downloads)):
            if items:
                problems.append(f"{len(items)} {label}")
        problems += r.notes
        lines.append(
            f"| {r.id} | {r.wave} | {r.stage} | **{r.status}** | {r.lock_files} | "
            f"{r.manifest_files} | {_fmt_bytes(r.manifest_bytes or r.lock_bytes)} | {'; '.join(problems)} |"
        )
    bad = [r for r in reports if r.status in ("MISSING", "CORRUPT")]
    lines += ["", f"**{len(bad)} dataset(s) with missing or corrupt files.**" if bad else "**No missing or corrupt files.**"]
    for r in bad:
        lines += ["", f"## {r.id}", ""]
        for label, items in (("missing", r.missing), ("size mismatch", r.size_mismatch), ("hash mismatch", r.hash_mismatch)):
            for rel in items[:20]:
                lines.append(f"- {label}: `{rel}`")
            if len(items) > 20:
                lines.append(f"- ... and {len(items) - 20} more {label}")
    md_path.write_text("\n".join(lines) + "\n")
    return md_path, json_path


def repair(dataset_id: str) -> None:
    """Forget download/extract markers so fetch/run.sh re-fetches everything missing."""
    okdir = paths.raw_dir(dataset_id) / ".ok"
    if okdir.exists():
        shutil.rmtree(okdir)
    state = paths.state_file(dataset_id)
    if state.exists():
        s = json.loads(state.read_text())
        for k in ("fetched_at", "extracted_at", "inventory"):
            s.pop(k, None)
        state.write_text(json.dumps(s))

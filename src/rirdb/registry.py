"""Dataset registry: the single source of truth for fetch, index and README.

`registry/datasets.yaml` is validated against the models below. Python never
touches the network; `compile_sources` writes a flat TSV that the bash fetch
layer (`fetch/*.sh`) reads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rirdb import paths

DatasetType = Literal["measured", "production", "simulated"]
IRKind = Literal[
    "room",          # enclosed architectural space
    "outdoor",       # forests, streets, canyons, ...
    "vehicle",       # car / train cabins
    "scale_model",   # physical scale models
    "device",        # loudspeakers, telephones, cabinets
    "plate",         # plate reverb units
    "spring",        # spring reverb units
    "digital_reverb",  # hardware / software algorithmic reverbs
    "creative",      # processed / effect IRs
]
CaptureFormat = Literal[
    "mono_omni",
    "stereo",
    "binaural",
    "foa_fuma",      # first-order B-format, FuMa ordering/normalisation
    "foa_ambix",     # first-order, ACN/SN3D
    "hoa_sh",        # higher-order spherical-harmonic signals (order in params)
    "em32_raw",      # Eigenmike em32 capsule signals
    "sma_raw",       # other spherical array capsules (Zylia, Voyage, ...)
    "tetra_raw",     # tetrahedral A-format
    "array_raw",     # linear / planar / circular / distributed arrays
    "sdm_array",     # open arrays for the Spatial Decomposition Method
]
Redistribute = Literal["yes", "unaltered_only", "no", "unknown"]
SourceKind = Literal[
    "zenodo", "depositonce", "figshare", "http", "wget_mirror", "github", "hf", "wayback", "manual"
]
Access = Literal["open", "registration", "manual", "broken"]
Status = Literal["planned", "active", "manual", "broken", "deferred"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class License(_Strict):
    spdx: str                       # SPDX id, or LicenseRef-... for custom terms
    url: str | None = None
    redistribute_audio: Redistribute = "unknown"
    note: str | None = None

    @field_validator("redistribute_audio", mode="before")
    @classmethod
    def _yaml_bool(cls, v):
        # YAML 1.1 (PyYAML) parses bare yes/no as booleans
        if isinstance(v, bool):
            return "yes" if v else "no"
        return v

    @property
    def non_commercial(self) -> bool:
        return "-NC" in self.spdx.upper() or self.spdx.lower().endswith("-nc")

    @property
    def share_alike(self) -> bool:
        return "-SA" in self.spdx.upper()

    @property
    def no_derivatives(self) -> bool:
        return "-ND" in self.spdx.upper()


class Source(_Strict):
    kind: SourceKind
    # zenodo: record ids; depositonce: item uuids; figshare: article ids;
    # github: "owner/repo@ref"; hf: "org/name@revision"
    records: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)      # http / wget_mirror / wayback
    include: list[str] = Field(default_factory=list)   # fnmatch globs on file names; empty = all
    exclude: list[str] = Field(default_factory=list)
    accept: list[str] = Field(default_factory=list)    # wget_mirror --accept patterns
    instructions: str | None = None                    # manual / registration datasets

    @model_validator(mode="after")
    def _check(self) -> "Source":
        needs_records = {"zenodo", "depositonce", "figshare", "github", "hf"}
        needs_urls = {"http", "wget_mirror", "wayback"}
        if self.kind in needs_records and not self.records:
            raise ValueError(f"source kind {self.kind!r} needs `records`")
        if self.kind in needs_urls and not self.urls:
            raise ValueError(f"source kind {self.kind!r} needs `urls`")
        if self.kind == "manual" and not self.instructions:
            raise ValueError("manual source needs `instructions`")
        return self


class Expected(_Strict):
    n_irs: int | None = None        # single-channel-or-multichannel IR measurements, as the authors count them
    n_rooms: int | None = None
    note: str | None = None


class Adapter(_Strict):
    name: str | None = None         # filled in P3 after `rirdb probe`
    params: dict = Field(default_factory=dict)


class Analysis(_Strict):
    scope: Literal["full", "subsample_v1", "none"] = "full"
    reference_role: str | None = None    # channel role analysed for arrays (e.g. "mic_0")
    subsample: dict | None = None


class Paper(_Strict):
    title: str
    url: str


class Dataset(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    year: int | None = None
    type: DatasetType
    ir_kinds: list[IRKind]
    capture_formats: list[CaptureFormat]
    fs_hz: list[int] = Field(default_factory=list)   # empty = to be confirmed by probe
    content: str
    expected: Expected = Field(default_factory=Expected)
    license: License
    access: Access
    source: Source
    keep_archive: bool | None = None      # None: keep only if archives total < 5 GB
    wave: int | None = Field(default=None, ge=0, le=4)
    adapter: Adapter = Field(default_factory=Adapter)
    analysis: Analysis = Field(default_factory=Analysis)
    homepage: str | None = None
    paper: Paper | None = None
    doi: str | None = None
    status: Status
    notes: str | None = None

    @field_validator("content")
    @classmethod
    def _one_line(cls, v: str) -> str:
        return " ".join(v.split())

    @property
    def spatial(self) -> bool:
        return any(
            f in self.capture_formats
            for f in ("binaural", "foa_fuma", "foa_ambix", "hoa_sh", "em32_raw", "sma_raw", "tetra_raw", "sdm_array")
        )

    @property
    def fetchable(self) -> bool:
        return self.access == "open" and self.status in ("planned", "active")


def load_registry(path: Path = paths.DATASETS_YAML) -> list[Dataset]:
    raw = yaml.safe_load(path.read_text())
    datasets = [Dataset.model_validate(d) for d in raw["datasets"]]
    ids = [d.id for d in datasets]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate dataset ids: {sorted(dupes)}")
    return datasets


def get_dataset(dataset_id: str, datasets: list[Dataset] | None = None) -> Dataset:
    for d in datasets or load_registry():
        if d.id == dataset_id:
            return d
    raise KeyError(f"unknown dataset id {dataset_id!r}")


# ---------------------------------------------------------------------------
# Compile for the bash fetch layer
# ---------------------------------------------------------------------------

SOURCES_TSV_COLUMNS = (
    "id", "wave", "status", "access", "kind", "records", "urls",
    "include", "exclude", "accept", "keep_archive",
)


def compile_sources(datasets: list[Dataset], out: Path) -> Path:
    """Flatten the registry into a TSV (lists joined with '|') for fetch/*.sh."""

    def cell(v) -> str:
        if isinstance(v, list):
            v = "|".join(v)
        s = "" if v is None else str(v)
        if "\t" in s or "\n" in s:
            raise ValueError(f"tab/newline in registry value {s!r}")
        return s if s else "-"

    lines = ["\t".join(SOURCES_TSV_COLUMNS)]
    for d in datasets:
        keep = "auto" if d.keep_archive is None else str(int(d.keep_archive))
        s = d.source
        lines.append("\t".join(cell(v) for v in (
            d.id, d.wave, d.status, d.access, s.kind, s.records, s.urls,
            s.include, s.exclude, s.accept, keep,
        )))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return out

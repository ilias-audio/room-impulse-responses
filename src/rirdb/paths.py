"""Filesystem layout: the git repo (code + registry) and RIRDB_ROOT (data on scratch)."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = REPO_ROOT / "registry"
# Jobs read a copy pinned at submission (RIRDB_REGISTRY), so editing the registry cannot break queued work.
DATASETS_YAML = Path(os.environ.get("RIRDB_REGISTRY") or REGISTRY_DIR / "datasets.yaml")
LOCKS_DIR = REGISTRY_DIR / "locks"
MANIFESTS_DIR = REGISTRY_DIR / "manifests"
PROBES_DIR = REGISTRY_DIR / "probes"
COMPILED_DIR = REGISTRY_DIR / "compiled"
README = REPO_ROOT / "README.md"
REPORTS_DIR = REPO_ROOT / "reports"

DEFAULT_DATA_ROOT = "/gpfs/scratch/eey119/rir-data"


def data_root() -> Path:
    """Root of all downloaded and derived data (never in git).

    Every path stored in the index is relative to this, so moving the corpus
    to permanent storage only means changing RIRDB_ROOT.
    """
    return Path(os.environ.get("RIRDB_ROOT", DEFAULT_DATA_ROOT))


def raw_dir(dataset_id: str) -> Path:
    return data_root() / "raw" / dataset_id


def files_dir(dataset_id: str) -> Path:
    """Extracted / directly-downloaded files of a dataset (read-only after fetch)."""
    return raw_dir(dataset_id) / "files"


def archives_dir(dataset_id: str) -> Path:
    return raw_dir(dataset_id) / "_archives"


def state_file(dataset_id: str) -> Path:
    return data_root() / "state" / f"{dataset_id}.json"

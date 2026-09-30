"""Cross-validation against values published with the datasets.

- OpenAIR "Data Tables": per-space octave-band T (reverberation time), EDT,
  C80, D50 computed by the OpenAIR authors with their own tools. Compared with
  the median of our valid per-IR values over the space's preferred IRs.
- ACE ground truth (when ace_arrays is analysed): see `ace()`.

Writes reports/validation/README.md (+ figures).
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

import numpy as np
import pandas as pd

from rirdb import paths
from rirdb.query import connect

BANDS = [125, 250, 500, 1000, 2000, 4000]
_BAND_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(k?)\s*(?:Hz)?\s*$", re.I)


def _band(label) -> int | None:
    if isinstance(label, (int, float)) and np.isfinite(label):
        v = float(label)
    else:
        m = _BAND_RE.match(str(label).replace("kHz", "k").replace("Hz", ""))
        if not m:
            return None
        v = float(m.group(1)) * (1000 if m.group(2) else 1)
    for b in BANDS:
        if abs(np.log2(v / b)) < 0.2:
            return b
    return None


def _metric(label: str) -> str | None:
    s = str(label).lower()
    if s.startswith("reverberation") or s.strip() in ("t30",):
        return "t30"
    if s.startswith("early decay") or s.strip() == "edt":
        return "edt"
    if "c80" in s:
        return "c80"
    if "d50" in s or s.startswith("definition"):
        return "d50"
    return None


def openair_tables() -> pd.DataFrame:
    rows = []
    for f in sorted(glob.glob(str(paths.files_dir("openair") / "*" / "Data Tables" / "*.xlsx"))):
        space = Path(f).parent.parent.name
        for _, df in pd.read_excel(f, sheet_name=None, header=None).items():
            # layout B: first column = parameter names, first row = bands
            header = df.iloc[0].tolist()
            if sum(_band(h) is not None for h in header[1:]) >= 4:
                for _, r in df.iloc[1:].iterrows():
                    m = _metric(r.iloc[0])
                    if m is None:
                        continue
                    for h, v in zip(header[1:], r.iloc[1:]):
                        b = _band(h)
                        if b is not None and pd.notna(v):
                            rows.append((space, m, b, float(v)))
                continue
            # layout A: a band row, then (label row, value row) pairs
            band_row = next((i for i in range(len(df)) if sum(_band(x) is not None for x in df.iloc[i]) >= 4), None)
            if band_row is None:
                continue
            bands = [_band(x) for x in df.iloc[band_row]]
            i = band_row + 1
            while i < len(df) - 1:
                m = _metric(df.iloc[i, 0])
                if m is not None:
                    for b, v in zip(bands, df.iloc[i + 1]):
                        if b is not None and pd.notna(v) and isinstance(v, (int, float)):
                            rows.append((space, m, b, float(v)))
                    i += 2
                else:
                    i += 1
    t = pd.DataFrame(rows, columns=["space", "metric", "band", "published"])
    # D50 published in % in some tables
    pct = (t["metric"] == "d50") & (t["published"] > 1.0)
    t.loc[pct, "published"] /= 100.0
    return t


def ours_per_space() -> pd.DataFrame:
    con = connect()
    cols = []
    for b in BANDS:
        cols += [f"CASE WHEN valid_t30_{b} THEN t30_{b} END AS t30_{b}",
                 f"CASE WHEN valid_edt_{b} THEN edt_{b} END AS edt_{b}",
                 f"CASE WHEN valid_c80_{b} THEN c80_{b} END AS c80_{b}",
                 f"CASE WHEN valid_d50_{b} THEN d50_{b} END AS d50_{b}"]
    df = con.execute(f"SELECT room_id, {', '.join(cols)} FROM corpus WHERE dataset_id = 'openair' AND preferred").df()
    df["space"] = df["room_id"].str.split("/").str[1]
    long = df.drop(columns="room_id").melt(id_vars="space", var_name="mb", value_name="ours").dropna()
    long["metric"] = long["mb"].str.split("_").str[0]
    long["band"] = long["mb"].str.split("_").str[1].astype(int)
    return long.groupby(["space", "metric", "band"], as_index=False)["ours"].median()


def openair_comparison() -> pd.DataFrame:
    from rirdb.adapters import slug

    pub = openair_tables()
    pub["space"] = pub["space"].map(slug)
    return pub.merge(ours_per_space(), on=["space", "metric", "band"], how="inner")


def summarise(m: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (metric, band), g in m.groupby(["metric", "band"]):
        if metric in ("t30", "edt"):
            r = np.log(g["ours"] / g["published"])
            out.append({"metric": metric, "band": band, "n_spaces": len(g),
                        "median ratio ours/published": round(float(np.exp(np.median(r))), 3),
                        "within 10 %": f"{np.mean(np.abs(np.exp(r) - 1) < 0.10) * 100:.0f} %"})
        else:
            d = g["ours"] - g["published"]
            unit = " dB" if metric == "c80" else ""
            out.append({"metric": metric, "band": band, "n_spaces": len(g),
                        "median ratio ours/published": f"median diff {np.median(d):+.2f}{unit}",
                        "within 10 %": f"MAE {np.mean(np.abs(d)):.2f}{unit}"})
    return pd.DataFrame(out)


def figure(m: pd.DataFrame, out: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from rirdb.report.corpus import AXIS, GRID, INK, INK2, MUTED, SURFACE

    fig, axes = plt.subplots(1, 2, figsize=(9, 4.2), dpi=130)
    fig.patch.set_facecolor(SURFACE)
    for ax, metric, label in ((axes[0], "t30", "T (s)"), (axes[1], "edt", "EDT (s)")):
        g = m[(m["metric"] == metric) & (m["band"].isin([500, 1000]))]
        ax.set_facecolor(SURFACE)
        lim = [0.1, max(12.0, g[["ours", "published"]].max().max() * 1.2)] if len(g) else [0.1, 10]
        ax.plot(lim, lim, color=AXIS, linewidth=1)
        ax.scatter(g["published"], g["ours"], s=16, color="#2a78d6", alpha=0.8, linewidths=0)
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlim(lim); ax.set_ylim(lim)
        ax.set_xlabel(f"OpenAIR published {label}", color=INK2); ax.set_ylabel(f"rirdb {label}", color=INK2)
        ax.set_title(f"{metric.upper()} per space, 500 Hz and 1 kHz ({len(g)} points)", color=INK, fontsize=9, loc="left")
        ax.grid(True, color=GRID, linewidth=0.6); ax.tick_params(colors=MUTED, labelsize=8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    return out


def build(out_dir: Path = paths.REPORTS_DIR / "validation") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    m = openair_comparison()
    s = summarise(m)
    figure(m, out_dir / "openair_t30_edt.png")
    md = [
        "# Validation against published values",
        "",
        "## OpenAIR data tables",
        "",
        f"{m['space'].nunique()} spaces with a published table and analysed IRs. Ours: median over the space's "
        "preferred IRs of *valid* values (pyrato, Lundeby-compensated EDC). Published: the per-space table "
        "(method and IR selection not documented by OpenAIR, so perfect agreement is not expected; the "
        "'Reverberation Time' row is compared with T30).",
        "",
        "| metric | band | spaces | median ratio / diff | agreement |",
        "|---|---|---|---|---|",
        *[f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |" for r in s.values.tolist()],
        "",
        "![T30 and EDT vs OpenAIR](openair_t30_edt.png)",
        "",
    ]
    (out_dir / "README.md").write_text("\n".join(md) + "\n")
    m.to_csv(out_dir / "openair_comparison.csv", index=False)
    return out_dir / "README.md"

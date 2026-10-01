"""Corpus report: per-dataset tables and IR-space coverage figures.

Writes reports/corpus/README.md (+ small PNG figures, committed) from the
merged metrics of every analysed dataset.

Colour: three categorical groups (validated all-pairs with the dataviz
validator: worst CVD dE 9.2, normal-vision dE 24.0 on the light surface), each
also carrying its own marker shape, plus tables for every number shown.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from rirdb import paths
from rirdb.query import connect

SURFACE = "#fcfcfb"
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
GROUPS = {   # label: (colour, marker)
    "measured, omni / array": ("#2a78d6", "o"),
    "measured, spatial / binaural": ("#eb6834", "s"),
    "production library": ("#1baf7a", "^"),
}
BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SPATIAL = {"binaural", "foa_fuma", "foa_ambix", "hoa_sh", "em32_raw", "sma_raw", "tetra_raw", "sdm_array"}


def _group(row) -> str:
    if row["type"] == "production":
        return "production library"
    return "measured, spatial / binaural" if row["capture_format"] in SPATIAL else "measured, omni / array"


def load_corpus() -> pd.DataFrame:
    con = connect()
    df = con.execute("SELECT * FROM corpus").df()
    df["group"] = df.apply(_group, axis=1)
    return df


def _style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.xaxis.label.set_color(INK2)
    ax.yaxis.label.set_color(INK2)


def _fig(w=7.0, h=4.6):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(w, h), dpi=130)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    return fig, ax


def fig_t30_c80(df: pd.DataFrame, out: Path) -> Path:
    """Reverberance vs clarity: where the corpus sits in the two main perceptual axes."""
    fig, ax = _fig()
    d = df[(df["ir_kind"] == "room") & df["preferred"].fillna(True)]
    for label, (col, mk) in GROUPS.items():
        g = d[(d["group"] == label) & np.isfinite(d["t30_mid"]) & np.isfinite(d["c80_mid"])]
        ax.scatter(g["t30_mid"], g["c80_mid"], s=10, c=col, marker=mk, alpha=0.55, linewidths=0,
                   label=f"{label} ({len(g):,})")
    ax.set_xscale("log")
    ax.set_xlabel("T30, mid (500 Hz + 1 kHz), s  [log]")
    ax.set_ylabel("C80, mid, dB")
    ax.set_title("Reverberance vs clarity (ISO 3382 single numbers, valid values only)", color=INK, fontsize=10, loc="left")
    ax.set_ylim(-15, 40)
    leg = ax.legend(frameon=False, fontsize=8, loc="upper right")
    for t in leg.get_texts():
        t.set_color(INK2)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    return out


def fig_coverage(df: pd.DataFrame, out: Path) -> Path:
    """IR-space coverage: count of IRs per (log T30_mid, DRR) cell; empty cells are gaps."""
    import matplotlib.colors as mcolors

    fig, ax = _fig(7.0, 4.2)
    d = df[(df["ir_kind"] == "room") & df["preferred"].fillna(True)]
    d = d[np.isfinite(d["t30_mid"]) & np.isfinite(d["drr_bb"])]
    xb = np.geomspace(0.05, 10, 23)
    yb = np.arange(-25, 31, 2.5)
    h, _, _ = np.histogram2d(d["t30_mid"].clip(xb[0], xb[-1]), d["drr_bb"].clip(yb[0], yb[-1]), bins=[xb, yb])
    cmap = mcolors.ListedColormap(BLUES)
    bounds = [1, 2, 5, 10, 25, 50, 100, 1e9]
    norm = mcolors.BoundaryNorm(bounds, cmap.N)
    hm = np.ma.masked_where(h.T == 0, h.T)
    pc = ax.pcolormesh(xb, yb, hm, cmap=cmap, norm=norm, edgecolors=SURFACE, linewidth=0.5)
    ax.set_xscale("log")
    ax.set_xlabel("T30, mid, s  [log]")
    ax.set_ylabel("DRR, broadband, dB")
    ax.set_title("Coverage of the IR space: IRs per cell (white = no IR)", color=INK, fontsize=10, loc="left")
    cb = fig.colorbar(pc, ax=ax, ticks=bounds[:-1], shrink=0.85)
    cb.ax.tick_params(colors=MUTED, labelsize=8)
    cb.outline.set_visible(False)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    return out


def fig_t30_bands(df: pd.DataFrame, out: Path) -> Path:
    """Median T30 per octave band, per dataset group, normalised to the mid value (tonal shape of decay)."""
    fig, ax = _fig(7.0, 4.2)
    bands = [125, 250, 500, 1000, 2000, 4000, 8000]
    d = df[(df["ir_kind"] == "room") & df["preferred"].fillna(True)]
    for label, (col, mk) in GROUPS.items():
        g = d[d["group"] == label]
        if g.empty:
            continue
        mid = g["t30_mid"]
        med, lo, hi = [], [], []
        for b in bands:
            col_t = f"tbest_{b}"
            if col_t not in g:
                med.append(np.nan); lo.append(np.nan); hi.append(np.nan)
                continue
            r = (g[col_t] / mid).replace([np.inf, -np.inf], np.nan).dropna()
            med.append(r.median()); lo.append(r.quantile(0.25)); hi.append(r.quantile(0.75))
        ax.plot(bands, med, color=col, marker=mk, markersize=6, linewidth=2, label=label)
        ax.fill_between(bands, lo, hi, color=col, alpha=0.12, linewidth=0)
    ax.set_xscale("log")
    ax.set_xticks(bands, [str(b) if b < 1000 else f"{b // 1000}k" for b in bands])
    ax.axhline(1.0, color=AXIS, linewidth=1)
    ax.set_xlabel("Octave band, Hz")
    ax.set_ylabel("T(f) / T30,mid")
    ax.set_title("Frequency shape of the decay (median, interquartile band)", color=INK, fontsize=10, loc="left")
    leg = ax.legend(frameon=False, fontsize=8)
    for t in leg.get_texts():
        t.set_color(INK2)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    return out


def _fmt(v, nd=2):
    return "" if v is None or not np.isfinite(v) else f"{v:.{nd}f}"


def dataset_table(df: pd.DataFrame) -> str:
    rows = []
    for ds, g in df.groupby("dataset_id"):
        n = len(g)
        grades = g["grade"].value_counts()
        q = lambda c, p: g[c].quantile(p) if c in g else np.nan  # noqa: E731
        rows.append({
            "dataset": ds, "IRs": n, "rooms": g["room_id"].nunique(),
            "A/B/C/D": "/".join(str(int(grades.get(k, 0))) for k in "ABCD"),
            "T30 mid (p10-p50-p90)": f"{_fmt(q('t30_mid', .1))} / {_fmt(q('t30_mid', .5))} / {_fmt(q('t30_mid', .9))}",
            "EDT mid": _fmt(q("edt_mid", .5)),
            "C80 mid": _fmt(q("c80_mid", .5), 1),
            "D50 mid": _fmt(q("d50_mid", .5)),
            "DRR": _fmt(q("drr_bb", .5), 1),
            "STI": _fmt(q("sti", .5)),
            "BR / TR": f"{_fmt(q('br', .5))} / {_fmt(q('tr', .5))}",
            "t_mix ms": _fmt(q("t_mix_ned_ms", .5), 0),
            "errors": int((g["error"].fillna("") != "").sum()),
        })
    t = pd.DataFrame(rows)
    head = "| " + " | ".join(t.columns) + " |\n|" + "|".join("---" for _ in t.columns) + "|\n"
    return head + "\n".join("| " + " | ".join(str(v) for v in r) + " |" for r in t.itertuples(index=False))


def flag_table(df: pd.DataFrame) -> str:
    flags = [c for c in df.columns if c.startswith("flag_")]
    rates = df.groupby("dataset_id")[flags].mean() * 100
    keep = [c for c in flags if rates[c].max() >= 1.0]
    head = "| dataset | " + " | ".join(c[5:].replace("_", " ") for c in keep) + " |\n|---|" + "---|" * len(keep) + "\n"
    return head + "\n".join(f"| {ds} | " + " | ".join(f"{rates.loc[ds, c]:.0f}" for c in keep) + " |"
                            for ds in rates.index)


def build(out_dir: Path = paths.REPORTS_DIR / "corpus") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    df = load_corpus()
    figs = {
        "t30_c80.png": fig_t30_c80(df, out_dir / "t30_c80.png"),
        "coverage_t30_drr.png": fig_coverage(df, out_dir / "coverage_t30_drr.png"),
        "t30_bands.png": fig_t30_bands(df, out_dir / "t30_bands.png"),
    }
    room = df[df["ir_kind"] == "room"]
    con = connect()
    dups = con.execute("""SELECT d.content_sha1[:10] AS sha, list(i.dataset_id || ': ' || i.local_key) AS files
                          FROM duplicates d, UNNEST(d.ir_ids) AS u(id) JOIN irs i ON i.ir_id = u.id
                          GROUP BY 1 ORDER BY 1""").df()
    if dups.empty:
        dup_md = ["No exact duplicates (identical decoded samples) found."]
    else:
        dups["datasets"] = [" + ".join(sorted({f.split(":")[0] for f in fs})) for fs in dups["files"]]
        dups["extra"] = [len(fs) - 1 for fs in dups["files"]]
        dups.assign(files=[" = ".join(fs) for fs in dups["files"]]).to_csv(out_dir / "duplicates.csv", index=False)
        per = dups.groupby("datasets").agg(groups=("sha", "size"), extra=("extra", "sum")).sort_values("groups", ascending=False)
        dup_md = ([f"{len(dups)} group(s) of byte-identical IRs (the `corpus_dedup` view marks all but one with "
                   "`dup_of`; full list in [duplicates.csv](duplicates.csv)):", "",
                   "| dataset(s) | groups | redundant copies |", "|---|---|---|"]
                  + [f"| {k} | {r.groups} | {r.extra} |" for k, r in per.iterrows()]
                  + ["", "Examples:", ""] + [f"- {' = '.join(f)}" for f in dups["files"].head(5)])
    md = [
        "# Corpus report",
        "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by `rirdb report corpus` from "
        f"`metrics/v1` (analyzer {df['analyzer_version'].dropna().iloc[0] if 'analyzer_version' in df else '?'}, "
        f"config {df['config_sha256'].dropna().iloc[0] if 'config_sha256' in df else '?'}).",
        "",
        f"**{len(df):,} IRs** analysed from **{df['dataset_id'].nunique()} datasets**, "
        f"**{df['room_id'].nunique():,} rooms/spaces**; {len(room):,} are room IRs "
        f"(the rest: outdoor, scale models, anechoic, devices). "
        f"Grades: {', '.join(f'{k} {v:,}' for k, v in df['grade'].value_counts().sort_index().items())} "
        "(A: T30 valid 125 Hz-4 kHz; B: T20/T30 valid 250 Hz-2 kHz; C: partial; D: none).",
        "",
        "Single numbers follow ISO 3382-1 (mean of 500 Hz and 1 kHz; only where both are valid). "
        "Figures use one preferred representation per measured position (e.g. OpenAIR B-format over its mono copy) and room IRs only.",
        "",
        "## Per dataset (medians unless noted)",
        "",
        dataset_table(df),
        "",
        "## Quality-flag rates (% of IRs; flags seen in >= 1 % of some dataset)",
        "",
        flag_table(df),
        "",
        "## Exact duplicates",
        "",
        *dup_md,
        "",
        "## Figures",
        "",
        "![T30 vs C80](t30_c80.png)",
        "",
        "![Coverage T30 x DRR](coverage_t30_drr.png)",
        "",
        "![Decay frequency shape](t30_bands.png)",
        "",
        "Methods and validity rules: [docs/decisions/analyzer-v1.md](../../docs/decisions/analyzer-v1.md).",
    ]
    (out_dir / "README.md").write_text("\n".join(md) + "\n")
    return out_dir / "README.md"

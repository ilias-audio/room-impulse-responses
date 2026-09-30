"""`rirdb` command line. Run every command through sbatch (see docs/hpc.md)."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from rirdb import paths
from rirdb.registry import compile_sources, load_registry

app = typer.Typer(no_args_is_help=True, add_completion=False)
registry_app = typer.Typer(no_args_is_help=True, help="Validate and compile registry/datasets.yaml.")
app.add_typer(registry_app, name="registry")
console = Console()


@registry_app.command("compile")
def registry_compile() -> None:
    """Validate the registry, write compiled/sources.tsv and regenerate the README tables."""
    from rirdb.readme import update_readme

    datasets = load_registry()
    out = compile_sources(datasets, paths.COMPILED_DIR / "sources.tsv")
    changed = update_readme(paths.README, datasets)
    console.print(f"{len(datasets)} datasets valid; wrote {out.relative_to(paths.REPO_ROOT)}; "
                  f"README {'updated' if changed else 'unchanged'}")


@registry_app.command("list")
def registry_list(wave: int | None = typer.Option(None, help="Only this wave.")) -> None:
    """Print the registry as a table."""
    table = Table("id", "type", "wave", "status", "access", "source", "license")
    for d in load_registry():
        if wave is not None and d.wave != wave:
            continue
        table.add_row(d.id, d.type, str(d.wave), d.status, d.access, d.source.kind, d.license.spdx)
    console.print(table)


def _select(dataset_ids: list[str] | None, wave: list[int] | None, all_: bool):
    datasets = load_registry()
    if dataset_ids:
        known = {d.id for d in datasets}
        unknown = set(dataset_ids) - known
        if unknown:
            raise typer.BadParameter(f"unknown dataset ids: {sorted(unknown)}")
        return [d for d in datasets if d.id in dataset_ids]
    if wave:
        return [d for d in datasets if d.wave in wave and d.fetchable]
    if all_:
        return [d for d in datasets if d.fetchable]
    raise typer.BadParameter("give dataset ids, --wave N, or --all")


@app.command()
def verify(
    dataset_ids: list[str] = typer.Argument(None, help="Dataset ids (default: use --wave/--all)."),
    wave: list[int] = typer.Option(None, "--wave", help="Waves to verify (repeatable)."),
    all_: bool = typer.Option(False, "--all", help="All fetchable datasets."),
    full: bool = typer.Option(False, help="Re-hash every file against the manifest."),
    repair: bool = typer.Option(False, help="Clear markers of datasets with missing files so fetch/run.sh re-fetches them."),
    workers: int = typer.Option(8, help="Hashing processes (--full)."),
) -> None:
    """Check locks, downloads and extracted files; write reports/verify/<date>.{md,json}."""
    from rirdb import verify as v

    reports = v.verify(_select(dataset_ids, wave, all_), full=full, workers=workers)
    md, _ = v.write_report(reports, full=full)
    table = Table("dataset", "wave", "stage", "status", "files", "problems")
    for r in reports:
        n_bad = len(r.missing) + len(r.size_mismatch) + len(r.hash_mismatch)
        table.add_row(r.id, str(r.wave), r.stage, r.status, str(r.manifest_files or r.lock_files),
                      f"{n_bad} bad, {len(r.unverified_downloads)} not fetched" if (n_bad or r.unverified_downloads) else "")
    console.print(table)
    console.print(f"report: {md.relative_to(paths.REPO_ROOT)}")
    bad = [r for r in reports if r.status in ("MISSING", "CORRUPT")]
    if repair:
        for r in bad:
            v.repair(r.id)
            console.print(f"repaired markers for {r.id}: now run `sbatch jobs/download.sh fetch/run.sh {r.id}`")
    if bad:
        raise typer.Exit(code=1)


@app.command()
def probe(dataset_ids: list[str] = typer.Argument(..., help="Datasets to probe.")) -> None:
    """Summarise fetched files into registry/probes/<id>.txt (commit it)."""
    from rirdb.probe import probe as run_probe

    for d in dataset_ids:
        out = run_probe(d)
        console.print(f"wrote {out.relative_to(paths.REPO_ROOT)}")


@app.command()
def index(
    dataset_ids: list[str] = typer.Argument(None),
    wave: list[int] = typer.Option(None, "--wave"),
    all_: bool = typer.Option(False, "--all"),
) -> None:
    """Build the canonical IR index for datasets with an adapter configured."""
    from rirdb.index import build_index

    table = Table("dataset", "IRs", "rooms", "subsample_v1", "fs", "channels", "expected")
    for d in _select(dataset_ids, wave, all_):
        if not d.adapter.name:
            console.print(f"[yellow]skip {d.id}: no adapter configured[/yellow]")
            continue
        s = build_index(d)
        exp = d.expected.n_irs
        table.add_row(d.id, str(s["n_irs"]), str(s["n_rooms"]), str(s["n_subsample_v1"]),
                      ",".join(map(str, s["fs"])), ",".join(map(str, s["channels"])), str(exp or "?"))
    console.print(table)


@app.command()
def analyze(
    dataset_id: str = typer.Option(..., "--dataset"),
    shard: str = typer.Option("0", help="Shard index, or 'auto' inside a SLURM array."),
    n_shards: int = typer.Option(1),
    workers: int = typer.Option(0, help="Processes (0: SLURM_CPUS_PER_TASK or 4)."),
    full: bool = typer.Option(False, help="Analyse all records, not only subsample_v1."),
    limit: int = typer.Option(0, help="Only the first N records of the shard (smoke tests)."),
) -> None:
    """Analyse one shard of a dataset (metrics parquet + feature h5)."""
    import os

    from rirdb.run import analyze_shard, auto_shard

    if shard == "auto":
        s, n = auto_shard()
    else:
        s, n = int(shard), n_shards
    w = workers or int(os.environ.get("SLURM_CPUS_PER_TASK", 4))
    out = analyze_shard(dataset_id, s, n, w, full=full, limit=limit or None)
    console.print(f"wrote {out}")


@app.command()
def merge(dataset_ids: list[str] = typer.Argument(...)) -> None:
    """Merge metric shards into metrics/v1/<id>/wide.parquet."""
    from rirdb.run import merge as run_merge

    for d in dataset_ids:
        console.print(f"wrote {run_merge(d)}")


@app.command("query")
def query_cmd(
    where: str = typer.Argument(..., help="SQL predicate over the `corpus` view."),
    columns: str = typer.Option("", help="Comma-separated columns (default: a core set)."),
    limit: int = typer.Option(50),
    order_by: str = typer.Option("", help="ORDER BY clause, e.g. 't30_mid DESC'."),
    csv: str = typer.Option("", help="Also write the result to this CSV path."),
) -> None:
    """Pick IRs by constraints (DuckDB over the metrics Parquet)."""
    import pandas as pd

    from rirdb.query import query

    df = query(where, [c.strip() for c in columns.split(",") if c.strip()] or None, limit, order_by or None)
    with pd.option_context("display.width", 200, "display.max_columns", 40, "display.max_colwidth", 40):
        console.print(df.to_string(index=False))
    console.print(f"{len(df)} rows")
    if csv:
        df.to_csv(csv, index=False)


report_app = typer.Typer(no_args_is_help=True, help="Generate reports.")
app.add_typer(report_app, name="report")


@report_app.command("corpus")
def report_corpus() -> None:
    """Per-dataset tables + IR-space figures -> reports/corpus/README.md."""
    from rirdb.report.corpus import build

    console.print(f"wrote {build().relative_to(paths.REPO_ROOT)}")


@report_app.command("validation")
def report_validation() -> None:
    """Compare with values published with the datasets -> reports/validation/."""
    from rirdb.validate import build

    console.print(f"wrote {build().relative_to(paths.REPO_ROOT)}")


@report_app.command("cards")
def report_cards() -> None:
    """One card per registry dataset -> docs/datasets/<id>.md."""
    from rirdb.report.cards import build

    console.print(f"wrote {len(build())} dataset cards to docs/datasets/")


@app.command()
def embed(dataset_ids: list[str] = typer.Argument(...), batch: int = typer.Option(16)) -> None:
    """CLAP embeddings of analysed IRs (GPU job, `pixi run -e embed`)."""
    from rirdb.embed import embed_dataset

    for d in dataset_ids:
        console.print(f"wrote {embed_dataset(d, batch=batch)}")


@app.command()
def snapshot() -> None:
    """Write snapshots/metrics_core.parquet (committed; purge insurance)."""
    from rirdb.export import snapshot as run_snapshot

    out = run_snapshot()
    console.print(f"wrote {out.relative_to(paths.REPO_ROOT)} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    app()

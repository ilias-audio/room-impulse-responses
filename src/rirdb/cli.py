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


if __name__ == "__main__":
    app()

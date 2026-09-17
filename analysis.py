"""Reproducible data collection for the semester-project report.

Collection deliberately stops at CSV/JSON files.  Plotting reads those files
in a separate process, so figures can be revised without rerunning the model.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Any

# One-at-a-time sensitivity analysis.  Each entry names the `SimConfig` field
# to vary and the values to try; the default value is one of them, so every
# sweep brackets the baseline and the middle point is comparable to the
# baseline scenario run above.
SWEEPS: dict[str, tuple[str, tuple[float, ...]]] = {
    "map_width": ("map_width", (8, 12, 16, 20, 26)),
    "defender_multiplier": (
        "defender_multiplier",
        (1.0, 1.5, 2.0, 2.5, 3.0),
    ),
    "growth_rate": ("growth_rate", (0.02, 0.035, 0.05, 0.075, 0.10)),
}


def _write_dicts(
    path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _sample_rows(result) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Per-turn rows of the detailed run, tagged with where they came from.

    Every scenario contributes its rows to one shared file, so the scenario
    and seed have to travel with each row.
    """
    prefix = {"scenario": result.scenario.name, "seed": result.sample_metrics.seed}
    country_turns = [
        {**prefix, **asdict(turn)} for turn in result.sample_metrics.country_turns
    ]
    world_turns = [
        {**prefix, **asdict(turn)} for turn in result.sample_metrics.world_turns
    ]
    return country_turns, world_turns


def _map_rows(result) -> list[dict[str, Any]]:
    """The final map of the detailed run, one row per cell.

    Unclaimed cells are written out too, as empty owner fields, so the file
    always holds width x height rows and the plot can rebuild the grid without
    knowing how big it was supposed to be.
    """
    rows = []
    for cell in result.sample_world.map:
        country = cell.country
        rows.append(
            {
                "scenario": result.scenario.name,
                "seed": result.sample_metrics.seed,
                "row": cell.row,
                "column": cell.col,
                "country": country.name if country else "",
                "strategy": country.strategy_name if country else "",
                "alive": int(country.alive) if country else "",
            }
        )
    return rows


def _sweep_scenario(base: Any, sweep: str, parameter: str, value: float) -> Any:
    """Copy of `base` with one parameter changed, named after that change."""
    # 1.5 -> "1p5": the name is used as an identifier in the CSV files.
    value_label = str(value).replace(".", "p")
    return replace(
        base,
        name=f"sweep_{sweep}_{value_label}",
        description=f"{parameter} sensitivity at {value}.",
        config=replace(base.config, **{parameter: value}),
    )


def collect_results(
    output_dir: Path,
    runs: int = 100,
    base_seed: int = 0,
    scenarios: Mapping[str, Any] | None = None,
    sweeps: Mapping[str, tuple[str, tuple[float, ...]]] = SWEEPS,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[Path]:
    """Run the approved experiment suite and persist every plotting input.

    One "condition" is one scenario or one point of one sweep, repeated over
    `runs` seeds.  Everything a figure could want ends up in a handful of
    combined CSV files plus a manifest describing how they were produced.
    """
    if runs <= 0:
        raise ValueError("runs must be positive")

    # Imported here rather than at module level so that `analysis.py plot`
    # never drags in the simulation at all.
    from experiment import SCENARIOS, run_experiment
    from metrics import CountrySummary, CountryTurn, StrategyStats, WorldTurn

    scenarios = SCENARIOS if scenarios is None else scenarios
    total_conditions = len(scenarios) + sum(len(values) for _, values in sweeps.values())
    completed_conditions = 0

    # Rows accumulate here and are written once at the end: a full collection
    # takes minutes, and partially written files would be worse than none.
    output_dir = Path(output_dir)
    scenario_runs: list[dict[str, Any]] = []
    scenario_stats: list[dict[str, Any]] = []
    sweep_runs: list[dict[str, Any]] = []
    sweep_stats: list[dict[str, Any]] = []
    sample_country_turns: list[dict[str, Any]] = []
    sample_world_turns: list[dict[str, Any]] = []
    sample_final_maps: list[dict[str, Any]] = []

    for scenario in scenarios.values():
        result = run_experiment(scenario, runs=runs, base_seed=base_seed)
        scenario_runs.extend(asdict(summary) for summary in result.summaries)
        scenario_stats.extend(
            {"scenario": scenario.name, **asdict(stat)} for stat in result.stats
        )
        country_turns, world_turns = _sample_rows(result)
        sample_country_turns.extend(country_turns)
        sample_world_turns.extend(world_turns)
        sample_final_maps.extend(_map_rows(result))
        completed_conditions += 1
        if progress is not None:
            progress(completed_conditions, total_conditions, scenario.name)

    # Sweeps all start from the balanced baseline, so the only difference
    # between two points of a sweep is the parameter being swept.
    sweep_base = scenarios.get("all_strategies", SCENARIOS["all_strategies"])
    for sweep, (parameter, values) in sweeps.items():
        for value in values:
            scenario = _sweep_scenario(sweep_base, sweep, parameter, value)
            result = run_experiment(scenario, runs=runs, base_seed=base_seed)
            sweep_runs.extend(
                {
                    "sweep": sweep,
                    "parameter": parameter,
                    "parameter_value": value,
                    **asdict(summary),
                }
                for summary in result.summaries
            )
            sweep_stats.extend(
                {
                    "sweep": sweep,
                    "parameter": parameter,
                    "parameter_value": value,
                    "scenario": scenario.name,
                    **asdict(stat),
                }
                for stat in result.stats
            )
            completed_conditions += 1
            if progress is not None:
                progress(completed_conditions, total_conditions, f"{sweep}={value}")

    # Field order is taken from the dataclasses, so a new measure shows up in
    # the CSV header automatically instead of being silently dropped.
    summary_fields = [field.name for field in fields(CountrySummary)]
    stats_fields = [field.name for field in fields(StrategyStats)]
    country_turn_fields = [field.name for field in fields(CountryTurn)]
    world_turn_fields = [field.name for field in fields(WorldTurn)]
    written = [
        _write_dicts(
            output_dir / "scenario_runs.csv", scenario_runs, summary_fields
        ),
        _write_dicts(
            output_dir / "scenario_stats.csv",
            scenario_stats,
            ["scenario", *stats_fields],
        ),
        _write_dicts(
            output_dir / "sweep_runs.csv",
            sweep_runs,
            ["sweep", "parameter", "parameter_value", *summary_fields],
        ),
        _write_dicts(
            output_dir / "sweep_stats.csv",
            sweep_stats,
            [
                "sweep",
                "parameter",
                "parameter_value",
                "scenario",
                *stats_fields,
            ],
        ),
        _write_dicts(
            output_dir / "sample_country_turns.csv",
            sample_country_turns,
            ["scenario", "seed", *country_turn_fields],
        ),
        _write_dicts(
            output_dir / "sample_world_turns.csv",
            sample_world_turns,
            ["scenario", "seed", *world_turn_fields],
        ),
        _write_dicts(
            output_dir / "sample_final_maps.csv",
            sample_final_maps,
            ["scenario", "seed", "row", "column", "country", "strategy", "alive"],
        ),
    ]

    # Without the manifest the CSV files are just numbers: it records the full
    # configuration of every condition, which is what makes a collected data
    # set reproducible months later.
    manifest = {
        "schema_version": 1,
        "runs": runs,
        "base_seed": base_seed,
        "scenarios": [
            {
                "name": scenario.name,
                "description": scenario.description,
                "composition": list(scenario.composition),
                "config": asdict(scenario.config),
            }
            for scenario in scenarios.values()
        ],
        "sweeps": {
            name: {"parameter": parameter, "values": list(values)}
            for name, (parameter, values) in sweeps.items()
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    written.append(manifest_path)
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect experiments and create the semester-report figures."
    )
    # Three subcommands, and the split between the first two is the point of
    # the module: `plot` must be runnable without simulating anything.
    commands = parser.add_subparsers(dest="command", required=True)

    collect = commands.add_parser("collect", help="run experiments and write CSV data")
    collect.add_argument("--runs", type=int, default=100, help="seeds per condition")
    collect.add_argument("--seed", type=int, default=0, help="first seed")
    collect.add_argument("--output", default="results", help="result root directory")

    plot = commands.add_parser("plot", help="plot previously collected CSV data")
    plot.add_argument("--input", default="results/data", help="input data directory")
    plot.add_argument(
        "--output", default="results/figures", help="figure output directory"
    )

    combined = commands.add_parser("all", help="collect data, then create figures")
    combined.add_argument("--runs", type=int, default=100, help="seeds per condition")
    combined.add_argument("--seed", type=int, default=0, help="first seed")
    combined.add_argument("--output", default="results", help="result root directory")
    return parser


def _print_progress(completed: int, total: int, label: str) -> None:
    print(f"[{completed:>2}/{total}] {label}", flush=True)


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    written: list[Path]
    if args.command == "collect":
        written = collect_results(
            Path(args.output) / "data",
            runs=args.runs,
            base_seed=args.seed,
            progress=_print_progress,
        )
    elif args.command == "plot":
        # Matplotlib is only needed for figures, so collecting data works on a
        # machine that has nothing but the standard library installed.
        from plots import plot_all

        written = plot_all(args.input, args.output)
    else:
        written = collect_results(
            Path(args.output) / "data",
            runs=args.runs,
            base_seed=args.seed,
            progress=_print_progress,
        )
        from plots import plot_all

        written.extend(
            plot_all(Path(args.output) / "data", Path(args.output) / "figures")
        )
    for path in written:
        print(f"wrote {path}")


if __name__ == "__main__":
    main()

"""Command line front end for the group interaction simulation.

Examples
--------
    uv run main.py --list
    uv run main.py --scenario all_strategies --runs 20
    uv run main.py --scenario duel:peace,hegemony --runs 50 --trace
    uv run main.py --all --runs 10 --csv-dir out
    uv run main.py --set defender_multiplier=3 --set growth_rate=0.1
"""

from __future__ import annotations

import argparse
from dataclasses import fields, replace

from config import SimConfig
from experiment import (
    SCENARIOS,
    Scenario,
    compare_scenarios,
    format_report,
    format_trace,
    resolve_scenario,
    run_experiment,
    write_experiment_csv,
)
from strategies import STRATEGIES


def _coerce(current: object, raw: str) -> object:
    """Read a `--set` value as whatever type the field already holds.

    `SimConfig` is the only description of its own types, so the current
    value is used as the pattern instead of repeating them here.
    """
    if isinstance(current, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    if current is None:  # only `map_height`, which defaults to None
        return int(raw)
    return raw


def apply_overrides(config: SimConfig, overrides: list[str]) -> SimConfig:
    """Apply `--set key=value` settings on top of a scenario's config."""
    known = {f.name for f in fields(SimConfig)}
    changes: dict[str, object] = {}
    for override in overrides:
        key, _, raw = override.partition("=")
        key = key.strip()
        if key not in known:
            raise SystemExit(
                f"unknown setting {key!r}; available: {', '.join(sorted(known))}"
            )
        changes[key] = _coerce(getattr(config, key), raw)
    return replace(config, **changes)


def prepare(scenario: Scenario, args: argparse.Namespace) -> Scenario:
    """Layer the command line on top of a scenario's own configuration.

    The scenario's settings are the baseline and `--set` wins over them, so
    `--scenario crowded --set map_width=20` is a crowded composition on a
    roomy map rather than an error.
    """
    config = apply_overrides(scenario.config, args.overrides)
    if args.turns is not None:
        config = replace(config, turns=args.turns)
    return replace(scenario, config=config)


def list_scenarios() -> str:
    lines = ["Scenarios:"]
    width = max(len(name) for name in SCENARIOS)
    for name, scenario in SCENARIOS.items():
        lines.append(f"  {name.ljust(width)}  {scenario.description}")
    lines.append("  duel:<strategy>,<strategy>  Head to head on a small map.")
    lines.append("")
    lines.append(f"Strategies: {', '.join(STRATEGIES)}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simulate populations that explore, fight and make pacts."
    )
    parser.add_argument(
        "--scenario",
        default="all_strategies",
        help="scenario name, or duel:<strategy>,<strategy>",
    )
    parser.add_argument(
        "--all", action="store_true", help="run every built-in scenario"
    )
    parser.add_argument(
        "--list", action="store_true", help="list scenarios and strategies"
    )
    parser.add_argument("--runs", type=int, default=20, help="seeds per scenario")
    parser.add_argument("--turns", type=int, help="override the turn limit")
    parser.add_argument("--seed", type=int, default=0, help="first seed")
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="override a SimConfig setting (repeatable)",
    )
    parser.add_argument("--csv-dir", help="write the collected metrics as CSV here")
    parser.add_argument(
        "--trace",
        type=int,
        nargs="?",
        const=10,
        metavar="EVERY",
        help="print the sample run's world time series every N turns",
    )
    parser.add_argument("--no-map", action="store_true", help="hide the final map")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.list:
        print(list_scenarios())
        return

    scenarios = (
        list(SCENARIOS.values()) if args.all else [resolve_scenario(args.scenario)]
    )
    results = []
    for scenario in scenarios:
        result = run_experiment(
            prepare(scenario, args), runs=args.runs, base_seed=args.seed
        )
        results.append(result)
        print(format_report(result, show_map=not args.no_map))
        if args.trace:
            print()
            print(format_trace(result, every=args.trace))
        print()
        if args.csv_dir:
            for path in write_experiment_csv(result, args.csv_dir):
                print(f"wrote {path}")
            print()

    # A single scenario has already been reported in full above; the closing
    # table is only useful when there is something to compare it with.
    if len(results) > 1:
        print(compare_scenarios(results))


if __name__ == "__main__":
    main()

"""Scenarios and the runner that compares strategies under them.

A scenario is a starting composition plus a `SimConfig`.  Running one means
repeating it over several seeds and aggregating the per-country summaries by
strategy, which is the comparison the report is built on.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from config import SimConfig
from metrics import (
    CountrySummary,
    Metrics,
    StrategyStats,
    aggregate,
    render_table,
    write_csv,
)
from model import Cell, Country, World
from strategies import STRATEGIES, make_strategy

# The balanced field: one country per strategy, which is the only composition
# in which the strategies can be ranked against each other fairly.
CORE_STRATEGIES = ("peace", "switzerland", "hegemony", "retaliation", "random")

# The summaries carry more numbers than fit on a terminal line, so the text
# report prints these subsets.  The CSV files keep everything.
SUMMARY_COLUMNS = (
    "strategy",
    "countries",
    "survival_rate",
    "dominance_rate",
    "mean_survival_turns",
    "mean_final_population",
    "median_final_population",
    "mean_final_territory",
    "mean_attacks_made",
    "mean_attacks_suffered",
    "mean_casualties",
    "mean_alliance_turns",
)

RUN_COLUMNS = (
    "country",
    "strategy",
    "survived",
    "survival_turns",
    "death_cause",
    "final_population",
    "final_territory",
    "attacks_made",
    "attacks_suffered",
    "cells_conquered",
    "cells_lost",
    "casualties",
    "pacts_formed",
    "pacts_broken",
)


@dataclass(frozen=True)
class Scenario:
    """A starting composition plus the world it starts in.

    `composition` lists one strategy name per country, so repeating a name
    fields several countries of that strategy.
    """

    name: str
    description: str
    composition: tuple[str, ...]
    config: SimConfig

    def validate(self) -> None:
        unknown = sorted(set(self.composition) - set(STRATEGIES))
        if unknown:
            raise ValueError(f"unknown strategies in {self.name}: {unknown}")
        if len(self.composition) < 2:
            raise ValueError(f"{self.name} needs at least two countries")


def _scenario(
    name: str, description: str, composition, **config_overrides
) -> Scenario:
    return Scenario(
        name=name,
        description=description,
        composition=tuple(composition),
        config=replace(SimConfig(), **config_overrides),
    )


# The first six vary the environment while keeping the field balanced; the
# last four keep the environment fixed and change who the neighbours are.
SCENARIOS: dict[str, Scenario] = {
    scenario.name: scenario
    for scenario in (
        _scenario(
            "all_strategies",
            "One country per strategy on a roomy map.",
            CORE_STRATEGIES,
            map_width=16,
        ),
        _scenario(
            "crowded",
            "The same five, but land runs out almost immediately.",
            CORE_STRATEGIES,
            map_width=8,
        ),
        _scenario(
            "spacious",
            "The same five with more land than they can ever settle.",
            CORE_STRATEGIES,
            map_width=26,
        ),
        _scenario(
            "strong_defence",
            "All strategies, but defending is three times as effective.",
            CORE_STRATEGIES,
            map_width=16,
            defender_multiplier=3.0,
        ),
        _scenario(
            "weak_defence",
            "All strategies, with no home advantage at all.",
            CORE_STRATEGIES,
            map_width=16,
            defender_multiplier=1.0,
        ),
        _scenario(
            "slow_growth",
            "All strategies with populations that recover slowly from war.",
            CORE_STRATEGIES,
            map_width=16,
            growth_rate=0.02,
        ),
        _scenario(
            "one_aggressor",
            "A single hegemony among four peaceful neighbours.",
            ("hegemony", "peace", "peace", "peace", "peace"),
            map_width=16,
        ),
        _scenario(
            "many_aggressors",
            "Four hegemonies and one peaceful country.",
            ("hegemony", "hegemony", "hegemony", "hegemony", "peace"),
            map_width=16,
        ),
        _scenario(
            "deterrence",
            "Aggressors against countries that always strike back.",
            ("hegemony", "hegemony", "retaliation", "retaliation", "peace"),
            map_width=16,
        ),
        _scenario(
            "neutrals",
            "Neutrality against open-handed pacifism, with wolves around.",
            ("switzerland", "switzerland", "peace", "peace", "hegemony", "hegemony"),
            map_width=18,
        ),
    )
}


def resolve_scenario(name: str) -> Scenario:
    """Look up a scenario, or build a duel on the fly: `duel:peace,hegemony`."""
    if name.startswith("duel:"):
        parts = tuple(p.strip() for p in name[len("duel:") :].split(",") if p.strip())
        scenario = _scenario(
            name,
            f"Head to head: {' vs '.join(parts)}.",
            parts,
            map_width=10,
        )
        scenario.validate()
        return scenario
    try:
        return SCENARIOS[name]
    except KeyError:
        raise ValueError(
            f"unknown scenario {name!r}; available: {', '.join(SCENARIOS)} "
            f"(or duel:<strategy>,<strategy>)"
        ) from None


# --- building and running ------------------------------------------------


def starting_cells(world: World, count: int) -> list[Cell]:
    """Scatter starting cells, keeping them as far apart as the map allows.

    Where countries start decides a great deal -- two of them placed side by
    side meet on turn one and are at war before either has any land -- so the
    positions are spread out instead of drawn uniformly.  The target distance
    is the side of the square each country would get if the map were divided
    evenly; candidates are drawn at random and rejected if they fall closer
    than that, and if enough attempts fail (a crowded map cannot honour the
    spacing) the requirement drops by a cell and the whole thing is retried.
    """
    cells = list(world.map)
    if count > len(cells):
        raise ValueError("more countries than cells")
    spacing = (len(cells) / count) ** 0.5
    while spacing >= 0:
        chosen: list[Cell] = []
        for _ in range(200 * count):  # generous, then give up on this spacing
            if len(chosen) == count:
                return chosen
            candidate = world.rng.choice(cells)
            # Manhattan distance, to match the four-neighbour movement rule.
            if all(
                abs(candidate.row - c.row) + abs(candidate.col - c.col) >= spacing
                for c in chosen
            ):
                chosen.append(candidate)
        if len(chosen) == count:
            return chosen
        spacing -= 1
    raise ValueError("could not place the countries")


def build_world(
    scenario: Scenario, seed: int, record_timeseries: bool = True
) -> World:
    metrics = Metrics(scenario.name, seed, record_timeseries)
    world = World(scenario.config, seed, metrics)
    cells = starting_cells(world, len(scenario.composition))
    # Names have to be unique -- the metrics key on them -- so two hegemonies
    # become "hegemony-1" and "hegemony-2".
    counters: dict[str, int] = {}
    for strategy_name, cell in zip(scenario.composition, cells):
        counters[strategy_name] = counters.get(strategy_name, 0) + 1
        country = Country(
            name=f"{strategy_name}-{counters[strategy_name]}",
            strategy=make_strategy(strategy_name),
            population=scenario.config.start_population,
        )
        world.add_country(country, cell)
    return world


def run_once(
    scenario: Scenario, seed: int, record_timeseries: bool = True
) -> tuple[World, list[CountrySummary]]:
    scenario.validate()
    world = build_world(scenario, seed, record_timeseries)
    world.run()
    return world, world.metrics.summarize(world)


@dataclass
class ExperimentResult:
    """Everything one scenario produced: the aggregate, and one run in full."""

    scenario: Scenario
    runs: int
    summaries: list[CountrySummary]
    stats: list[StrategyStats]
    sample_world: World
    sample_summaries: list[CountrySummary]

    @property
    def sample_metrics(self) -> Metrics:
        return self.sample_world.metrics


def run_experiment(
    scenario: Scenario, runs: int = 20, base_seed: int = 0
) -> ExperimentResult:
    """Repeat a scenario over `runs` seeds; keep the first run in full detail.

    Seeds are consecutive from `base_seed`, so the same call always produces
    the same numbers and a scenario can be re-run to check a surprise.
    """
    summaries: list[CountrySummary] = []
    sample_world: World | None = None
    sample_summaries: list[CountrySummary] = []
    for index in range(runs):
        # Only the first seed keeps its per-turn rows.  Those are illustration
        # -- every comparison rests on the summaries -- and keeping them for a
        # hundred seeds is what would make a full collection expensive.
        keep_timeseries = index == 0
        world, run_summaries = run_once(
            scenario, base_seed + index, record_timeseries=keep_timeseries
        )
        summaries.extend(run_summaries)
        if keep_timeseries:
            sample_world = world
            sample_summaries = run_summaries
    assert sample_world is not None
    return ExperimentResult(
        scenario=scenario,
        runs=runs,
        summaries=summaries,
        stats=aggregate(summaries),
        sample_world=sample_world,
        sample_summaries=sample_summaries,
    )


# --- reporting -----------------------------------------------------------


def format_report(result: ExperimentResult, show_map: bool = True) -> str:
    """The console report: settings, the aggregate, then one run to look at."""
    scenario = result.scenario
    lines = [
        "=" * 78,
        f"{scenario.name}: {scenario.description}",
        f"  countries: {', '.join(scenario.composition)}",
        f"  settings:  {scenario.config.describe()}",
        f"  runs:      {result.runs}",
        "",
        render_table(
            result.stats,
            SUMMARY_COLUMNS,
            title=f"Strategies over {result.runs} runs "
            f"(one observation per country per run)",
        ),
        "",
        render_table(
            sorted(result.sample_summaries, key=lambda s: -s.final_territory),
            RUN_COLUMNS,
            title=f"Sample run (seed {result.sample_metrics.seed}, "
            f"ended on turn {result.sample_world.turn})",
        ),
    ]
    if show_map:
        world = result.sample_world
        legend = ", ".join(
            f"{letter}={country.name}"
            for letter, country in zip(world.map_letters(), world.countries)
        )
        lines += ["", f"Final map of the sample run ({legend}):", world.render()]
    return "\n".join(lines)


def format_trace(result: ExperimentResult, every: int = 10) -> str:
    """Per-turn world time series of the sample run, thinned out for reading."""
    rows = [
        turn
        for turn in result.sample_metrics.world_turns
        if turn.turn % every == 0 or turn.turn == result.sample_world.turn
    ]
    return render_table(rows, title=f"Sample run, every {every} turns")


def write_experiment_csv(result: ExperimentResult, directory: str | Path) -> list[Path]:
    """Dump everything a plot could need.  No plotting happens here."""
    directory = Path(directory) / result.scenario.name
    written = [
        write_csv(directory / "strategy_stats.csv", result.stats),
        write_csv(directory / "run_summaries.csv", result.summaries),
        write_csv(
            directory / "sample_country_turns.csv",
            result.sample_metrics.country_turns,
        ),
        write_csv(
            directory / "sample_world_turns.csv", result.sample_metrics.world_turns
        ),
    ]
    return [path for path in written if path is not None]


def compare_scenarios(results: list[ExperimentResult]) -> str:
    """One line per strategy per scenario, for the cross-condition comparison."""

    @dataclass(slots=True)
    class Row:
        scenario: str
        strategy: str
        survival_rate: float
        dominance_rate: float
        mean_final_population: float
        mean_final_territory: float

    rows = [
        Row(
            scenario=result.scenario.name,
            strategy=stat.strategy,
            survival_rate=stat.survival_rate,
            dominance_rate=stat.dominance_rate,
            mean_final_population=stat.mean_final_population,
            mean_final_territory=stat.mean_final_territory,
        )
        for result in results
        for stat in result.stats
    ]
    return render_table(rows, title="All scenarios")

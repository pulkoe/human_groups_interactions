"""Measurement: what happened during a run, and how strategies compare.

Three levels of detail are collected:

* `CountryTurn` / `WorldTurn` -- a per-turn time series of one run.
* `CountrySummary`            -- one row per country per run.
* `StrategyStats`             -- one row per strategy, aggregated over runs.

Nothing here draws anything.  The time series and summaries are written out
as CSV so they can be plotted with whatever tool you like.
"""

from __future__ import annotations

import csv
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import Pact

if TYPE_CHECKING:
    from model import Country, World


# --- records -------------------------------------------------------------


@dataclass(slots=True)
class CountryTurn:
    """One country, one turn."""

    turn: int
    country: str
    strategy: str
    alive: int
    population: int
    territory: int
    capacity: int
    known_cells: int
    attacks_made: int
    attacks_suffered: int
    battles_won: int
    cells_gained: int
    cells_lost: int
    casualties: int
    trade_agreements: int
    non_aggression_pacts: int
    military_alliances: int
    mean_attitude_out: float
    mean_attitude_in: float


@dataclass(slots=True)
class WorldTurn:
    """The whole world, one turn."""

    turn: int
    alive_countries: int
    total_population: int
    claimed_cells: int
    unclaimed_cells: int
    attacks: int
    casualties: int
    active_pacts: int


@dataclass(slots=True)
class CountrySummary:
    """One country at the end of one run -- the three success measures from
    the assignment (final population, survival length, controlled territory)
    plus the behaviour that produced them."""

    scenario: str
    seed: int
    country: str
    strategy: str
    survived: int
    survival_turns: int
    death_cause: str
    final_population: int
    peak_population: int
    final_territory: int
    peak_territory: int
    territory_share: float
    dominant: int
    attacks_made: int
    attacks_suffered: int
    battles_won: int
    cells_conquered: int
    cells_lost: int
    cells_explored: int
    casualties: int
    contacts: int
    pacts_formed: int
    pacts_broken: int
    pacts_lapsed: int
    trade_turns: int
    non_aggression_turns: int
    alliance_turns: int
    unions_absorbed: int


@dataclass(slots=True)
class StrategyStats:
    """One strategy, aggregated over every country that played it."""

    strategy: str
    countries: int
    survival_rate: float
    dominance_rate: float
    mean_survival_turns: float
    mean_final_population: float
    median_final_population: float
    stdev_final_population: float
    mean_peak_population: float
    mean_final_territory: float
    mean_peak_territory: float
    mean_attacks_made: float
    mean_attacks_suffered: float
    mean_casualties: float
    mean_alliance_turns: float
    mean_pacts_formed: float


# --- small statistics helpers -------------------------------------------


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _median(values: Sequence[float]) -> float:
    return statistics.median(values) if values else 0.0


def _stdev(values: Sequence[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


# --- collection ----------------------------------------------------------


class Metrics:
    """Collects events as they happen and snapshots the world every turn.

    A `World` always owns one, so actions can simply call into it; a metrics
    object with `record_timeseries=False` still counts everything needed for
    the summary but keeps no per-turn rows (cheaper for large sweeps).
    """

    def __init__(
        self,
        scenario: str = "",
        seed: int = 0,
        record_timeseries: bool = True,
    ):
        self.scenario = scenario
        self.seed = seed
        self.record_timeseries = record_timeseries
        self.country_turns: list[CountryTurn] = []
        self.world_turns: list[WorldTurn] = []
        # Cumulative counters and counters for the current turn, by country name.
        self._totals: dict[str, Counter] = defaultdict(Counter)
        self._turn: dict[str, Counter] = defaultdict(Counter)
        self._peak_population: dict[str, float] = defaultdict(float)
        self._peak_territory: dict[str, int] = defaultdict(int)
        self._deaths: dict[str, tuple[int, str]] = {}

    # -- events ----------------------------------------------------------

    def _bump(self, country: Country, key: str, amount: float = 1) -> None:
        self._totals[country.name][key] += amount
        self._turn[country.name][key] += amount

    def record_attack(self, attacker: Country, defender: Country, won: bool) -> None:
        self._bump(attacker, "attacks_made")
        self._bump(defender, "attacks_suffered")
        if won:
            self._bump(attacker, "battles_won")

    def record_conquest(self, attacker: Country, defender: Country) -> None:
        self._bump(attacker, "cells_gained")
        self._bump(defender, "cells_lost")

    def record_exploration(self, country: Country) -> None:
        self._bump(country, "cells_explored")
        self._bump(country, "cells_gained")

    def record_casualties(self, country: Country, people: float) -> None:
        if people > 0:
            self._bump(country, "casualties", people)

    def record_contact(self, country_a: Country, country_b: Country) -> None:
        self._bump(country_a, "contacts")
        self._bump(country_b, "contacts")

    def record_pact_start(
        self, country_a: Country, country_b: Country, pact: Pact
    ) -> None:
        self._bump(country_a, "pacts_formed")
        self._bump(country_b, "pacts_formed")

    def record_pact_end(
        self, country_a: Country, country_b: Country, pact: Pact, reason: str
    ) -> None:
        key = "pacts_broken" if reason == "broken" else "pacts_lapsed"
        self._bump(country_a, key)
        self._bump(country_b, key)

    def record_union(self, absorber: Country, absorbed: Country) -> None:
        self._bump(absorber, "unions_absorbed")

    def record_death(self, country: Country, turn: int, cause: str) -> None:
        # The first cause recorded wins; a country cannot die twice, and the
        # cause is what distinguishes a conquest from a collapse or a union.
        self._deaths.setdefault(country.name, (turn, cause))

    # -- per-turn snapshot -------------------------------------------------

    def update(self, world: World) -> None:
        """Called at the end of every turn by `World.step`."""
        attacks = 0
        casualties = 0.0
        for country in world.countries:
            counts = self._turn[country.name]
            attacks += counts["attacks_made"]
            casualties += counts["casualties"]

            if country.alive:
                self._peak_population[country.name] = max(
                    self._peak_population[country.name], country.population
                )
                self._peak_territory[country.name] = max(
                    self._peak_territory[country.name], country.territory
                )

            # Counted per partner, not per turn: two simultaneous alliances
            # add two to `alliance_turns`, which is what makes the number
            # comparable between a country with one ally and one with four.
            pacts = self._count_pacts(world, country)
            for pact, number in pacts.items():
                if number:
                    self._totals[country.name][f"{pact}_turns"] += number

            if self.record_timeseries:
                out, into = self._mean_attitudes(world, country)
                self.country_turns.append(
                    CountryTurn(
                        turn=world.turn,
                        country=country.name,
                        strategy=country.strategy_name,
                        alive=int(country.alive),
                        population=round(country.population),
                        territory=country.territory,
                        capacity=round(world.capacity(country)),
                        known_cells=len(country.known_cells),
                        attacks_made=counts["attacks_made"],
                        attacks_suffered=counts["attacks_suffered"],
                        battles_won=counts["battles_won"],
                        cells_gained=counts["cells_gained"],
                        cells_lost=counts["cells_lost"],
                        casualties=round(counts["casualties"]),
                        trade_agreements=pacts[Pact.TRADE_AGREEMENT],
                        non_aggression_pacts=pacts[Pact.NON_AGGRESSION_PACT],
                        military_alliances=pacts[Pact.MILITARY_ALLIANCE],
                        mean_attitude_out=out,
                        mean_attitude_in=into,
                    )
                )

        if self.record_timeseries:
            claimed = sum(c.territory for c in world.countries)
            self.world_turns.append(
                WorldTurn(
                    turn=world.turn,
                    alive_countries=len(world.alive_countries),
                    total_population=round(
                        sum(c.population for c in world.alive_countries)
                    ),
                    claimed_cells=claimed,
                    unclaimed_cells=world.map.size - claimed,
                    attacks=attacks,
                    casualties=round(casualties),
                    active_pacts=sum(
                        len(d.pacts)
                        for d in world.diplomacies
                        if d.country_a.alive and d.country_b.alive
                    ),
                )
            )

        # The per-turn counters start over; the cumulative ones do not.
        self._turn.clear()

    @staticmethod
    def _count_pacts(world: World, country: Country) -> dict[Pact, int]:
        counts = dict.fromkeys(Pact, 0)
        if not country.alive:
            return counts
        for other, diplomacy in world.get_diplomacies(country).items():
            if not other.alive:
                continue
            for pact in diplomacy.pacts:
                counts[pact] += 1
        return counts

    @staticmethod
    def _mean_attitudes(world: World, country: Country) -> tuple[float, float]:
        """Average attitude this country holds, and that others hold of it."""
        out: list[int] = []
        into: list[int] = []
        if country.alive:
            for other, diplomacy in world.get_diplomacies(country).items():
                if not (other.alive and diplomacy.established):
                    continue
                out.append(diplomacy.score(country))
                into.append(diplomacy.score(other))
        return round(_mean(out), 2), round(_mean(into), 2)

    # -- end of run --------------------------------------------------------

    def summarize(self, world: World) -> list[CountrySummary]:
        """One row per country, dead ones included, at the end of a run."""
        alive = world.alive_countries
        # Dominance is decided on territory, with population breaking ties.
        # It is a snapshot at whatever turn the run stopped on, so a country
        # that was overtaken on the last turn gets nothing for it.
        dominant = (
            max(alive, key=lambda c: (c.territory, c.population)) if alive else None
        )
        summaries = []
        for country in world.countries:
            totals = self._totals[country.name]
            death_turn, cause = self._deaths.get(country.name, (None, ""))
            summaries.append(
                CountrySummary(
                    scenario=self.scenario,
                    seed=self.seed,
                    country=country.name,
                    strategy=country.strategy_name,
                    survived=int(country.alive),
                    # A survivor's "survival time" is the length of the run,
                    # so the measure only compares within one scenario.
                    survival_turns=death_turn if death_turn is not None else world.turn,
                    death_cause=cause,
                    final_population=round(country.population),
                    peak_population=round(self._peak_population[country.name]),
                    final_territory=country.territory,
                    peak_territory=self._peak_territory[country.name],
                    territory_share=round(country.territory / world.map.size, 4),
                    dominant=int(country == dominant),
                    attacks_made=totals["attacks_made"],
                    attacks_suffered=totals["attacks_suffered"],
                    battles_won=totals["battles_won"],
                    # Land is gained by settling it or by taking it; only the
                    # second is interesting, so the first is subtracted out.
                    cells_conquered=totals["cells_gained"] - totals["cells_explored"],
                    cells_lost=totals["cells_lost"],
                    cells_explored=totals["cells_explored"],
                    casualties=round(totals["casualties"]),
                    contacts=totals["contacts"],
                    pacts_formed=totals["pacts_formed"],
                    pacts_broken=totals["pacts_broken"],
                    pacts_lapsed=totals["pacts_lapsed"],
                    trade_turns=totals[f"{Pact.TRADE_AGREEMENT}_turns"],
                    non_aggression_turns=totals[f"{Pact.NON_AGGRESSION_PACT}_turns"],
                    alliance_turns=totals[f"{Pact.MILITARY_ALLIANCE}_turns"],
                    unions_absorbed=totals["unions_absorbed"],
                )
            )
        return summaries


# --- aggregation ---------------------------------------------------------


def aggregate(summaries: Iterable[CountrySummary]) -> list[StrategyStats]:
    """Group per-country results by strategy.

    One country in one run is one observation, so a scenario that fields two
    Hegemony countries contributes two observations for Hegemony.
    """
    grouped: dict[str, list[CountrySummary]] = defaultdict(list)
    for summary in summaries:
        grouped[summary.strategy].append(summary)

    stats = []
    for strategy, rows in grouped.items():
        populations = [r.final_population for r in rows]
        stats.append(
            StrategyStats(
                strategy=strategy,
                countries=len(rows),
                survival_rate=round(_mean([r.survived for r in rows]), 3),
                dominance_rate=round(_mean([r.dominant for r in rows]), 3),
                mean_survival_turns=round(_mean([r.survival_turns for r in rows]), 1),
                mean_final_population=round(_mean(populations), 1),
                median_final_population=round(_median(populations), 1),
                stdev_final_population=round(_stdev(populations), 1),
                mean_peak_population=round(
                    _mean([r.peak_population for r in rows]), 1
                ),
                mean_final_territory=round(
                    _mean([r.final_territory for r in rows]), 2
                ),
                mean_peak_territory=round(_mean([r.peak_territory for r in rows]), 2),
                mean_attacks_made=round(_mean([r.attacks_made for r in rows]), 2),
                mean_attacks_suffered=round(
                    _mean([r.attacks_suffered for r in rows]), 2
                ),
                mean_casualties=round(_mean([r.casualties for r in rows]), 1),
                mean_alliance_turns=round(_mean([r.alliance_turns for r in rows]), 1),
                mean_pacts_formed=round(_mean([r.pacts_formed for r in rows]), 2),
            )
        )
    # Best first, by land and then by people, so the report's tables read as
    # a ranking without the reader having to sort them.
    stats.sort(key=lambda s: (-s.mean_final_territory, -s.mean_final_population))
    return stats


# --- output --------------------------------------------------------------


def write_csv(path: str | Path, rows: Sequence[Any]) -> Path | None:
    """Write a list of dataclass records to `path`.  Returns the path, or
    None when there was nothing to write."""
    if not rows:
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [f.name for f in fields(rows[0])]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)
    return path


def render_table(
    rows: Sequence[Any], columns: Sequence[str] | None = None, title: str = ""
) -> str:
    """Fixed-width text table of dataclass records, for stdout and the report."""
    if not rows:
        return f"{title}\n(no data)" if title else "(no data)"
    columns = list(columns or [f.name for f in fields(rows[0])])
    header = [c.replace("_", " ") for c in columns]
    body = [[_format_cell(getattr(row, c)) for c in columns] for row in rows]
    widths = [
        max(len(header[i]), max(len(line[i]) for line in body))
        for i in range(len(columns))
    ]
    lines = []
    if title:
        lines.append(title)
    lines.append("  ".join(h.ljust(widths[i]) for i, h in enumerate(header)))
    lines.append("  ".join("-" * w for w in widths))
    for line in body:
        lines.append("  ".join(line[i].rjust(widths[i]) for i in range(len(columns))))
    return "\n".join(lines)


def _format_cell(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)

"""Every tunable parameter of the simulation.

`SimConfig` is frozen: a scenario derives a variant with
`dataclasses.replace(config, growth_rate=0.1)`, which keeps the parameters of
a run immutable and trivial to print into the report.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class Pact(Enum):
    """The three independent components a pact may contain.

    The original notes call `TRADE_AGREEMENT` "food sharing".  There is no
    explicit food stock in the model (food is implicit in the carrying
    capacity of a cell), so sharing food is expressed as a raised carrying
    capacity -- see `SimConfig.trade_capacity_bonus`.
    """

    TRADE_AGREEMENT = 1
    NON_AGGRESSION_PACT = 2
    MILITARY_ALLIANCE = 3

    def __str__(self) -> str:
        return self.name.lower()


# Both sides must feel at least this well towards each other before they are
# willing to enter the pact.  Trade sits at neutral on purpose: it is the only
# thing two strangers can agree on, and the goodwill it generates is what
# makes the deeper pacts reachable at all.
PACT_THRESHOLDS: Mapping[Pact, int] = MappingProxyType(
    {
        Pact.TRADE_AGREEMENT: 0,
        Pact.NON_AGGRESSION_PACT: 30,
        Pact.MILITARY_ALLIANCE: 50,
    }
)

# Relationship gained by both sides for every turn a pact stays alive.
PACT_BONUSES: Mapping[Pact, int] = MappingProxyType(
    {
        Pact.TRADE_AGREEMENT: 2,
        Pact.NON_AGGRESSION_PACT: 3,
        Pact.MILITARY_ALLIANCE: 5,
    }
)

# Pacts that an attack breaks.  A trade agreement survives a war.
PEACE_PACTS = frozenset({Pact.NON_AGGRESSION_PACT, Pact.MILITARY_ALLIANCE})


@dataclass(frozen=True)
class SimConfig:
    """Parameters of one simulated world."""

    # --- map -------------------------------------------------------------
    map_width: int = 16
    map_height: int | None = None  # None -> square map

    # --- population ------------------------------------------------------
    cell_capacity: int = 1000
    """One cell produces one unit of food, which feeds `cell_capacity` people."""
    start_population: int = 100
    growth_rate: float = 0.05
    """Logistic growth rate; high enough that strategic differences show up."""
    famine_rate: float = 0.2
    """Fraction of the excess population lost per turn when over capacity."""
    trade_capacity_bonus: float = 0.10
    """Extra carrying capacity per trade partner ("food sharing")."""
    max_trade_partners_counted: int = 5

    # --- war -------------------------------------------------------------
    defender_multiplier: float = 1.5
    power_territory_exponent: float = 0.5
    """Power is `population / territory ** exponent`.

    0.0 -> pure population (big empires steamroll everything),
    1.0 -> pure population density (size does not help at all).
    The default 0.5 makes a large population stronger, but with diminishing
    returns, because force has to be projected across more cells.
    """
    ally_power_contribution: float = 0.5
    """Fraction of an ally's own power it commits to someone else's battle."""
    alliance_requires_border: bool = True
    """An ally can only help if it shares a border with the opponent."""
    assimilation_rate: float = 0.5
    """Share of a conquered cell's inhabitants that joins the conqueror."""
    winner_casualty_rate: float = 0.2
    loser_casualty_rate: float = 0.4
    """Casualties of each side, as a fraction of the contested cell's
    population.  They are split over everyone who fought on that side, which
    is what an ally risks when it joins someone else's war."""

    # --- diplomacy -------------------------------------------------------
    relationship_min: int = -100
    relationship_max: int = 100
    relationship_decay: int = 1
    """Attitudes drift back towards neutral by this much per turn, which is
    what eventually ends a war (there is no explicit state of war)."""
    attack_penalty: int = -50
    conquest_penalty: int = -10
    """Extra resentment for every cell actually lost."""
    ally_intervention_penalty: int = -20
    """Applied to the attitude towards a country that fought against you."""
    break_pact_penalty: int = -50
    break_pact_reputation_penalty: int = -20
    """Every other pact partner of an oathbreaker also thinks less of it."""
    pact_tolerance: int = 10
    """How far a relationship may sink below the pact threshold before the
    pact lapses.  A lapse is not the same as breaking the pact by attacking."""
    union_threshold: int = 80
    """Mutual attitude required before a consolidation (union) is possible."""
    retaliation_window: int = 10
    """How many turns a retaliating country remembers an attack."""

    # --- run -------------------------------------------------------------
    turns: int = 300

    @property
    def height(self) -> int:
        return self.map_height or self.map_width

    def describe(self) -> str:
        return (
            f"{self.map_width}x{self.height} map, "
            f"growth={self.growth_rate}, "
            f"defender={self.defender_multiplier}x, "
            f"power_exp={self.power_territory_exponent}, "
            f"turns={self.turns}"
        )

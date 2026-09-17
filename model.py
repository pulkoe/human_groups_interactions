"""The simulated world: map, countries, diplomacy, and the turn loop.

Only state and rules live here.  What a country *decides* to do lives in
`strategies.py`, what an action *does* lives in `actions.py`, and what we
measure lives in `metrics.py`.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import TYPE_CHECKING

from config import PACT_BONUSES, PACT_THRESHOLDS, Pact, SimConfig
from metrics import Metrics

if TYPE_CHECKING:
    from strategies import Strategy


class Cell:
    """One unit of area.  Produces one unit of food, may be claimed once."""

    __slots__ = ("row", "col", "country")

    def __init__(self, row: int, col: int):
        self.row = row
        self.col = col
        self.country: Country | None = None

    def __repr__(self) -> str:
        owner = self.country.name if self.country else "-"
        return f"Cell({self.row},{self.col},{owner})"


class Map:
    def __init__(self, width: int, height: int | None = None):
        self.width = width
        self.height = height or width
        self.cells = [
            [Cell(row, col) for col in range(self.width)] for row in range(self.height)
        ]

    def __iter__(self):
        for row in self.cells:
            yield from row

    @property
    def size(self) -> int:
        return self.width * self.height

    def get_cell_neighbors(self, cell: Cell) -> list[Cell]:
        """Von Neumann neighbourhood, in a fixed order (keeps runs repeatable)."""
        neighbors = []
        for d_row, d_col in ((-1, 0), (0, -1), (0, 1), (1, 0)):
            n_row, n_col = cell.row + d_row, cell.col + d_col
            if 0 <= n_row < self.height and 0 <= n_col < self.width:
                neighbors.append(self.cells[n_row][n_col])
        return neighbors


class Country:
    """A population: how many people, which cells, what it knows, how it feels."""

    def __init__(self, name: str, strategy: Strategy, population: float):
        self.name = name
        self.strategy = strategy
        self.population = float(population)
        self.cells: set[Cell] = set()
        self.known_cells: set[Cell] = set()
        # Turn on which this country was last attacked by another one.
        self.grudges: dict[Country, int] = {}
        self.death_turn: int | None = None
        self.death_cause: str | None = None

    @property
    def territory(self) -> int:
        return len(self.cells)

    @property
    def alive(self) -> bool:
        return self.death_turn is None

    @property
    def strategy_name(self) -> str:
        return self.strategy.name

    def sorted_cells(self) -> list[Cell]:
        """Owned cells in map order -- set iteration order is not repeatable."""
        return sorted(self.cells, key=lambda c: (c.row, c.col))

    # Countries are identified by name throughout -- the metrics key on it,
    # and diplomacy dictionaries are keyed by the country object -- so names
    # have to be unique within a world.
    def __eq__(self, other: object) -> bool:
        if isinstance(other, Country):
            return self.name == other.name
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.name)

    def __repr__(self) -> str:
        return f"Country({self.name}, pop={int(self.population)}, cells={self.territory})"


class Diplomacy:
    """The state between two countries.

    The attitude is *directional*: how A feels about B need not match how B
    feels about A.  A pact, in contrast, is symmetrical -- it either exists
    between the two of them or it does not.
    """

    def __init__(self, country_a: Country, country_b: Country, config: SimConfig):
        if country_a == country_b:
            raise ValueError("A country cannot have diplomacy with itself.")
        self.country_a = country_a
        self.country_b = country_b
        self.config = config
        # Attitude *of* the key *towards* the other country.
        self._scores: dict[Country, int] = {country_a: 0, country_b: 0}
        # Every pair has a Diplomacy from the start, but it means nothing
        # until the two have actually met; `established` is that distinction.
        self.established = False
        self.pacts: set[Pact] = set()

    def other(self, country: Country) -> Country:
        return self.country_b if country == self.country_a else self.country_a

    def score(self, viewer: Country) -> int:
        """How `viewer` feels about the other country."""
        return self._scores[viewer]

    @property
    def mutual_score(self) -> int:
        """The less enthusiastic of the two attitudes.

        Pacts are symmetrical, so the reluctant side decides whether one is
        possible: goodwill in one direction cannot carry an agreement.
        """
        return min(self._scores.values())

    def update_relationship(self, viewer: Country, delta: int) -> None:
        self._scores[viewer] = max(
            self.config.relationship_min,
            min(self.config.relationship_max, self._scores[viewer] + delta),
        )

    def update_both(self, delta: int) -> None:
        for country in self._scores:
            self.update_relationship(country, delta)

    def decay(self) -> None:
        """Drift both attitudes back towards neutral."""
        step = self.config.relationship_decay
        for country, score in self._scores.items():
            if score > 0:
                self._scores[country] = max(0, score - step)
            elif score < 0:
                self._scores[country] = min(0, score + step)

    def __repr__(self) -> str:
        return (
            f"Diplomacy({self.country_a.name}->{self.score(self.country_a)}, "
            f"{self.country_b.name}->{self.score(self.country_b)}, "
            f"pacts={{{', '.join(sorted(str(p) for p in self.pacts))}}})"
        )


class World:
    def __init__(
        self,
        config: SimConfig | None = None,
        seed: int | None = None,
        metrics: Metrics | None = None,
    ):
        self.config = config or SimConfig()
        self.rng = random.Random(seed)
        self.map = Map(self.config.map_width, self.config.height)
        self.countries: list[Country] = []
        # Every Diplomacy is stored under both of its endpoints, so it stays a
        # single shared object seen from either side; `_pairs` lets us walk
        # each of them exactly once.
        self._diplomacies: dict[Country, dict[Country, Diplomacy]] = {}
        self._pairs: list[Diplomacy] = []
        self.metrics: Metrics = metrics if metrics is not None else Metrics()
        self.turn = 0

    # -- setup ------------------------------------------------------------

    def add_country(self, country: Country, start_cell: Cell | None = None) -> None:
        """Add a country and open a relationship with everyone already here."""
        if country in self._diplomacies:
            raise ValueError(f"{country.name} is already part of the world.")
        self._diplomacies[country] = {}
        for other in self.countries:
            diplomacy = Diplomacy(country, other, self.config)
            self._diplomacies[country][other] = diplomacy
            self._diplomacies[other][country] = diplomacy
            self._pairs.append(diplomacy)
        self.countries.append(country)
        if start_cell is not None:
            if start_cell.country is not None:
                raise ValueError(f"{start_cell} is already claimed.")
            self.set_cell_owner(start_cell, country)
            self.update_known_cells_and_countries(country)

    # -- queries ----------------------------------------------------------

    @property
    def alive_countries(self) -> list[Country]:
        return [c for c in self.countries if c.alive]

    @property
    def finished(self) -> bool:
        return len(self.alive_countries) <= 1

    @property
    def diplomacies(self) -> list[Diplomacy]:
        """Every diplomacy in the world, each listed once."""
        return self._pairs

    def get_diplomacy(self, country_a: Country, country_b: Country) -> Diplomacy:
        if country_a == country_b:
            raise ValueError("A country cannot have diplomacy with itself.")
        try:
            return self._diplomacies[country_a][country_b]
        except KeyError:
            raise ValueError(
                f"diplomacy between {country_a.name} and {country_b.name} does not exist."
            ) from None

    def get_diplomacies(self, country: Country) -> Mapping[Country, Diplomacy]:
        """Every diplomacy `country` takes part in, keyed by the other country."""
        return self._diplomacies[country]

    def get_country_cells(self, country: Country) -> list[Cell]:
        return country.sorted_cells()

    def unclaimed_cells(self) -> list[Cell]:
        return [cell for cell in self.map if cell.country is None]

    def neighbouring_countries(self, country: Country) -> set[Country]:
        return {
            neighbor.country
            for cell in country.cells
            for neighbor in self.map.get_cell_neighbors(cell)
            if neighbor.country is not None and neighbor.country != country
        }

    def share_border(self, country_a: Country, country_b: Country) -> bool:
        # Walking the smaller country's border gives the same answer for less
        # work, and this is asked repeatedly while resolving a battle.
        smaller, larger = sorted((country_a, country_b), key=lambda c: c.territory)
        return any(
            neighbor.country == larger
            for cell in smaller.cells
            for neighbor in self.map.get_cell_neighbors(cell)
        )

    def has_pact(self, country_a: Country, country_b: Country, pact: Pact) -> bool:
        return pact in self.get_diplomacy(country_a, country_b).pacts

    def trade_partners(self, country: Country) -> int:
        return sum(
            1
            for other, diplomacy in self.get_diplomacies(country).items()
            if other.alive and Pact.TRADE_AGREEMENT in diplomacy.pacts
        )

    # -- population -------------------------------------------------------

    def capacity(self, country: Country) -> float:
        """How many people the controlled area can feed.

        Territory sets the ceiling; trade agreements ("food sharing") raise it
        a little, which is the only role food plays in the model.
        """
        cfg = self.config
        partners = min(self.trade_partners(country), cfg.max_trade_partners_counted)
        return cfg.cell_capacity * country.territory * (
            1 + cfg.trade_capacity_bonus * partners
        )

    def update_country_population(self, country: Country) -> None:
        """Logistic growth towards the carrying capacity of the territory."""
        cfg = self.config
        capacity = self.capacity(country)
        population = country.population
        if capacity <= 0:
            country.population = 0.0
            return
        if population > capacity:
            # The land cannot feed everyone; the surplus starves off gradually.
            country.population = max(capacity, population * (1 - cfg.famine_rate))
            return
        growth = cfg.growth_rate * population * (1 - population / capacity)
        country.population = min(capacity, population + growth)

    # -- war --------------------------------------------------------------

    def compute_country_power(self, country: Country) -> float:
        """A country's own strength, before any allies join in."""
        if not country.alive or country.territory == 0 or country.population <= 0:
            return 0.0
        return country.population / (
            country.territory**self.config.power_territory_exponent
        )

    def battle_power(
        self, country: Country, opponent: Country
    ) -> tuple[float, dict[Country, float]]:
        """Strength `country` brings against `opponent`, and who contributed.

        Alliances are deliberately *not* transitive: an ally that is also
        allied to the opponent stays out of it.
        """
        cfg = self.config
        own = self.compute_country_power(country)
        contributions: dict[Country, float] = {country: own}
        total = own
        for ally, diplomacy in self.get_diplomacies(country).items():
            if ally == opponent or not ally.alive:
                continue
            if Pact.MILITARY_ALLIANCE not in diplomacy.pacts:
                continue
            if Pact.MILITARY_ALLIANCE in self.get_diplomacy(ally, opponent).pacts:
                continue  # allied to both sides -> stays neutral
            if cfg.alliance_requires_border and not self.share_border(ally, opponent):
                continue  # too far away to help
            help_power = self.compute_country_power(ally) * cfg.ally_power_contribution
            if help_power <= 0:
                continue
            contributions[ally] = help_power
            total += help_power
        return total, contributions

    def estimate_win_chance(self, attacker: Country, defender: Country) -> float:
        """The odds the battle would actually be drawn with.

        Strategies call this before deciding to attack, so a country looks at
        exactly the same numbers the fight will use -- there is no hidden
        information and no misjudgement in the model.
        """
        attack_power, _ = self.battle_power(attacker, defender)
        defence_power, _ = self.battle_power(defender, attacker)
        defence_power *= self.config.defender_multiplier
        if attack_power + defence_power <= 0:
            return 0.0
        return attack_power / (attack_power + defence_power)

    def apply_casualties(
        self, contributions: Mapping[Country, float], total_losses: float
    ) -> None:
        """Split losses over everyone who fought, proportional to their share."""
        total_power = sum(contributions.values())
        if total_power <= 0:
            return
        for country, share in contributions.items():
            losses = total_losses * (share / total_power)
            country.population = max(0.0, country.population - losses)
            self.metrics.record_casualties(country, losses)

    # -- territory --------------------------------------------------------

    def set_cell_owner(
        self, cell: Cell, owner: Country | None, death_cause: str = "conquered"
    ) -> None:
        previous = cell.country
        if previous is not None:
            previous.cells.discard(cell)
        cell.country = owner
        if owner is not None:
            owner.cells.add(cell)
            owner.known_cells.add(cell)
        if previous is not None and previous.alive and not previous.cells:
            self.kill(previous, death_cause)

    def kill(self, country: Country, cause: str) -> None:
        """Remove a country; its land goes back to being unclaimed.

        Land is not inherited by whoever caused the death, so a collapse
        reopens territory for anybody to settle.
        """
        country.death_turn = self.turn
        country.death_cause = cause
        country.population = 0.0
        for cell in list(country.cells):
            self.set_cell_owner(cell, None)
        self.metrics.record_death(country, self.turn, cause)

    # -- knowledge and contact -------------------------------------------

    def establish_contact(self, country_a: Country, country_b: Country) -> None:
        """First contact: the two exchange what they know of the world."""
        diplomacy = self.get_diplomacy(country_a, country_b)
        if diplomacy.established:
            return
        diplomacy.established = True
        shared = country_a.known_cells | country_b.known_cells
        country_a.known_cells = set(shared)
        country_b.known_cells = set(shared)
        self.metrics.record_contact(country_a, country_b)

    def update_known_cells_and_countries(self, country: Country) -> None:
        """Learn the surroundings, and meet whoever is on the other side.

        Contact needs a shared border; knowledge of a *third* country's land
        can arrive second-hand through the exchange above, but a relationship
        with that third country still requires meeting it directly.
        """
        met: list[Country] = []
        for cell in country.sorted_cells():
            country.known_cells.add(cell)
            for neighbor in self.map.get_cell_neighbors(cell):
                country.known_cells.add(neighbor)
                owner = neighbor.country
                if owner is not None and owner != country and owner not in met:
                    if not self.get_diplomacy(country, owner).established:
                        met.append(owner)
        # Look around first, then hand over the finished map to whoever is met.
        for other in met:
            self.establish_contact(country, other)

    # -- diplomacy upkeep -------------------------------------------------

    def update_diplomacy(self) -> None:
        """Once per turn, for every pair: decay, lapse, and pact goodwill."""
        for diplomacy in self._pairs:
            if not (diplomacy.country_a.alive and diplomacy.country_b.alive):
                continue
            diplomacy.decay()
            for pact in sorted(diplomacy.pacts, key=lambda p: p.value):
                threshold = PACT_THRESHOLDS[pact] - self.config.pact_tolerance
                if diplomacy.mutual_score < threshold:
                    # The pact quietly lapses; nobody broke their word.
                    diplomacy.pacts.discard(pact)
                    self.metrics.record_pact_end(
                        diplomacy.country_a, diplomacy.country_b, pact, "lapsed"
                    )
                    continue
                diplomacy.update_both(PACT_BONUSES[pact])

    # -- turn loop --------------------------------------------------------

    def turn_order(self) -> list[Country]:
        """Countries act one after another, in a fresh random order each turn,
        so nobody enjoys a permanent first-mover advantage."""
        # `alive_countries` builds a new list, so shuffling it here leaves
        # `self.countries` -- and with it every report's column order -- alone.
        order = self.alive_countries
        self.rng.shuffle(order)
        return order

    def step(self) -> None:
        """One turn: upkeep for everybody, one action each, then the deaths."""
        self.turn += 1

        # Upkeep happens for everyone before anybody acts, so the random order
        # of play below decides who moves first, not who grows or meets first.
        for country in self.alive_countries:
            self.update_country_population(country)
            self.update_known_cells_and_countries(country)
        self.update_diplomacy()

        for country in self.turn_order():
            if not country.alive:
                continue  # eliminated earlier in this very turn
            action = country.strategy.choose_action(self, country)
            # Re-checked because the countries that acted earlier this turn
            # may already have taken the cell this one had in mind.
            if action is not None and action.is_possible(self):
                action.execute(self)

        # Battles take people off a few at a time, so a country can be left
        # standing with nobody in it.  That is settled once, at the end.
        for country in self.alive_countries:
            if country.population < 1:
                self.kill(country, "collapsed")

        self.metrics.update(self)

    def run(self, turns: int | None = None) -> None:
        for _ in range(turns if turns is not None else self.config.turns):
            # A run can end early, when only one country is left standing;
            # the summaries record the turn it stopped on either way.
            if self.finished:
                break
            self.step()

    # -- debugging --------------------------------------------------------

    MAP_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def map_letters(self) -> str:
        """The letter `render` uses for each country, in country order."""
        return "".join(
            self.MAP_LETTERS[i % 26] for i in range(len(self.countries))
        )

    def render(self) -> str:
        """ASCII picture of the map -- one letter per country, '.' unclaimed."""
        symbols = dict(zip(self.countries, self.map_letters()))
        rows = [
            "".join(
                "." if cell.country is None else symbols[cell.country] for cell in row
            )
            for row in self.map.cells
        ]
        return "\n".join(rows)

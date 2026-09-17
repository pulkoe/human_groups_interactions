"""What a country can do on its turn, and what each move does to the world.

Every action is created by a strategy, validated with `is_possible`, and then
executed.  `World.step` re-checks `is_possible` immediately before executing,
because countries act one after another and the world may have moved on since
the action was chosen.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from config import PACT_THRESHOLDS, PEACE_PACTS, Pact
from model import Cell, Country, World


class Action(ABC):
    @abstractmethod
    def is_possible(self, world: World) -> bool: ...

    @abstractmethod
    def execute(self, world: World) -> None: ...


class ExploreCell(Action):
    """Explore an unclaimed area next to the country and settle it.

    Two countries may pick the same cell in the same turn.  Because they act
    one after another, the one that acts first simply gets it; the other finds
    the cell taken and its action lapses.
    """

    def __init__(self, country: Country, cell: Cell):
        self.country = country
        self.cell = cell

    def is_possible(self, world: World) -> bool:
        if not self.country.alive or self.cell.country is not None:
            return False
        return any(
            neighbor.country == self.country
            for neighbor in world.map.get_cell_neighbors(self.cell)
        )

    def execute(self, world: World) -> None:
        world.set_cell_owner(self.cell, self.country)
        world.metrics.record_exploration(self.country)

    def __repr__(self) -> str:
        return f"Explore({self.country.name} -> {self.cell.row},{self.cell.col})"


class AttackCell(Action):
    """Attack one cell of a neighbouring country.

    War is fought cell by cell rather than between whole populations at once,
    so a war is simply a run of these actions over several turns.
    """

    def __init__(self, attacker: Country, defender: Country, cell: Cell):
        self.attacker = attacker
        self.defender = defender
        self.cell = cell

    def is_possible(self, world: World) -> bool:
        if not (self.attacker.alive and self.defender.alive):
            return False
        if self.cell.country != self.defender:
            return False
        return any(
            neighbor.country == self.attacker
            for neighbor in world.map.get_cell_neighbors(self.cell)
        )

    def execute(self, world: World) -> None:
        config = world.config
        attacker, defender = self.attacker, self.defender
        diplomacy = world.get_diplomacy(attacker, defender)

        # The insult lands whether or not the attack succeeds, and it is what
        # a retaliating country remembers.
        diplomacy.update_relationship(defender, config.attack_penalty)
        defender.grudges[attacker] = world.turn
        self._break_pacts(world, diplomacy)

        attack_power, attack_side = world.battle_power(attacker, defender)
        defence_power, defence_side = world.battle_power(defender, attacker)
        defence_power *= config.defender_multiplier

        # Whoever joined in is resented by the other side, which is how a war
        # spreads beyond the two countries that started it.
        self._blame_allies(world, attack_side, defender, attacker)
        self._blame_allies(world, defence_side, attacker, defender)

        # The stronger side is likelier to win but never certain to: the
        # outcome is drawn with probability attack / (attack + defence).
        total = attack_power + defence_power
        attacker_wins = total > 0 and world.rng.random() < attack_power / total

        # Everyone living in the contested cell is at stake.  People are not
        # tracked cell by cell, so the stake is the defender's average cell.
        stake = defender.population / max(1, defender.territory)
        # The defender's own losses are settled separately below -- it loses
        # the whole stake when the cell falls -- so only the allies are billed
        # through the shared casualty split.
        defence_allies = {c: p for c, p in defence_side.items() if c != defender}

        if attacker_wins:
            world.apply_casualties(attack_side, stake * config.winner_casualty_rate)
            world.apply_casualties(defence_allies, stake * config.loser_casualty_rate)
            # Part of the conquered cell's population joins the conqueror,
            # the rest is lost.
            defender.population = max(0.0, defender.population - stake)
            world.metrics.record_casualties(
                defender, stake * (1 - config.assimilation_rate)
            )
            attacker.population += stake * config.assimilation_rate
            diplomacy.update_relationship(defender, config.conquest_penalty)
            world.metrics.record_conquest(attacker, defender)
            world.set_cell_owner(self.cell, attacker)
        else:
            world.apply_casualties(attack_side, stake * config.loser_casualty_rate)
            world.apply_casualties(defence_side, stake * config.winner_casualty_rate)

        world.metrics.record_attack(attacker, defender, attacker_wins)

    def _break_pacts(self, world: World, diplomacy) -> None:
        """An attack breaks every peace pact, and costs the attacker its
        reputation with everyone else it has promised peace to."""
        broken = diplomacy.pacts & PEACE_PACTS
        if not broken:
            return
        config = world.config
        diplomacy.pacts -= PEACE_PACTS
        diplomacy.update_relationship(self.defender, config.break_pact_penalty)
        for pact in sorted(broken, key=lambda p: p.value):
            world.metrics.record_pact_end(
                self.attacker, self.defender, pact, "broken"
            )
        for other, other_diplomacy in world.get_diplomacies(self.attacker).items():
            if other == self.defender or not other.alive:
                continue
            if other_diplomacy.pacts & PEACE_PACTS:
                other_diplomacy.update_relationship(
                    other, config.break_pact_reputation_penalty
                )

    @staticmethod
    def _blame_allies(world: World, side, victim: Country, main: Country) -> None:
        """Resent everyone who fought for the other side, and remember it.

        The grudge matters as much as the attitude: it is what lets a
        retaliating country strike back at an intervening ally, not only at
        whoever attacked it directly.
        """
        for ally in side:
            if ally == main or not ally.alive:
                continue
            world.get_diplomacy(victim, ally).update_relationship(
                victim, world.config.ally_intervention_penalty
            )
            victim.grudges[ally] = world.turn

    def __repr__(self) -> str:
        return (
            f"Attack({self.attacker.name} -> {self.defender.name} "
            f"@ {self.cell.row},{self.cell.col})"
        )


class OfferPact(Action):
    """Offer one component of a pact to a neighbour, who may refuse.

    A pact is symmetrical, so both sides must feel well enough about each
    other for it to be on the table at all.
    """

    def __init__(self, sender: Country, receiver: Country, pact: Pact):
        self.sender = sender
        self.receiver = receiver
        self.pact = pact

    def is_possible(self, world: World) -> bool:
        if not (self.sender.alive and self.receiver.alive):
            return False
        diplomacy = world.get_diplomacy(self.sender, self.receiver)
        if not diplomacy.established or self.pact in diplomacy.pacts:
            return False
        if diplomacy.mutual_score < PACT_THRESHOLDS[self.pact]:
            return False
        return world.share_border(self.sender, self.receiver)

    def execute(self, world: World) -> None:
        # The receiver may simply decline.  The sender spent its turn either
        # way, which is the cost of trying diplomacy at all.
        if not self.receiver.strategy.accepts_pact(
            world, self.receiver, self.sender, self.pact
        ):
            return
        world.get_diplomacy(self.sender, self.receiver).pacts.add(self.pact)
        world.metrics.record_pact_start(self.sender, self.receiver, self.pact)

    def __repr__(self) -> str:
        return f"OfferPact({self.sender.name} -> {self.receiver.name}: {self.pact})"


class ProposeUnion(Action):
    """Propose a consolidation: two allied populations become one.

    This is the deepest commitment in the model, so it needs a standing
    military alliance and a very high mutual regard.  The larger population
    absorbs the smaller one.
    """

    def __init__(self, proposer: Country, partner: Country):
        self.proposer = proposer
        self.partner = partner

    def is_possible(self, world: World) -> bool:
        if not (self.proposer.alive and self.partner.alive):
            return False
        diplomacy = world.get_diplomacy(self.proposer, self.partner)
        if not diplomacy.established:
            return False
        if Pact.MILITARY_ALLIANCE not in diplomacy.pacts:
            return False
        if diplomacy.mutual_score < world.config.union_threshold:
            return False
        return world.share_border(self.proposer, self.partner)

    def execute(self, world: World) -> None:
        if not self.partner.strategy.accepts_union(world, self.partner, self.proposer):
            return
        # Who proposed is irrelevant to the outcome: the larger population
        # absorbs the smaller, so a union is never a way to take someone over.
        absorber, absorbed = self.proposer, self.partner
        if absorbed.population > absorber.population:
            absorber, absorbed = absorbed, absorber
        merge_countries(world, absorber, absorbed)

    def __repr__(self) -> str:
        return f"ProposeUnion({self.proposer.name} + {self.partner.name})"


def merge_countries(world: World, absorber: Country, absorbed: Country) -> None:
    """Fold `absorbed` into `absorber`: people, land, knowledge and contacts."""
    absorber.population += absorbed.population
    absorbed.population = 0.0
    absorber.known_cells |= absorbed.known_cells

    for third, absorbed_diplomacy in world.get_diplomacies(absorbed).items():
        if third == absorber or not third.alive:
            continue
        absorber_diplomacy = world.get_diplomacy(absorber, third)
        if absorbed_diplomacy.established:
            absorber_diplomacy.established = True
        # The successor inherits the average of the two attitudes, in both
        # directions, and every pact either of them held (a pact the new
        # relationship cannot support lapses on the next turn).
        #
        # The two pairs below are those two directions: first what each of the
        # merging countries felt about the third one, then what the third one
        # felt about each of them.  `update_relationship` takes a change
        # rather than a value, hence the subtraction.
        for viewer, other in ((absorber, absorbed), (third, third)):
            target = (
                absorber_diplomacy.score(viewer) + absorbed_diplomacy.score(other)
            ) // 2
            absorber_diplomacy.update_relationship(
                viewer, target - absorber_diplomacy.score(viewer)
            )
        absorber_diplomacy.pacts |= absorbed_diplomacy.pacts

    # Handing over the last cell kills the absorbed country by itself, which
    # is why the cause has to be passed down: without it the merge would be
    # recorded as a conquest.
    for cell in absorbed.sorted_cells():
        world.set_cell_owner(cell, absorber, death_cause="union")
    if absorbed.alive:  # had no land to hand over
        world.kill(absorbed, "union")
    world.metrics.record_union(absorber, absorbed)


# --- enumerating what is available --------------------------------------
#
# Strategies pick from these lists rather than inventing moves, so the rules
# of what is legal live in one place.  All of them work outwards from the
# country's own cells, because everything in this model is local: you can
# only settle, attack or sign with somebody you touch.


def possible_explore_actions(world: World, country: Country) -> list[ExploreCell]:
    actions = []
    # Two of the country's own cells can border the same free one; offer it once.
    seen: set[tuple[int, int]] = set()
    for cell in country.sorted_cells():
        for neighbor in world.map.get_cell_neighbors(cell):
            key = (neighbor.row, neighbor.col)
            if neighbor.country is None and key not in seen:
                seen.add(key)
                actions.append(ExploreCell(country, neighbor))
    return actions


def possible_attack_actions(world: World, country: Country) -> list[AttackCell]:
    # One action per bordering enemy *cell*, so a long shared border offers
    # several ways into the same country.
    actions = []
    seen: set[tuple[int, int]] = set()
    for cell in country.sorted_cells():
        for neighbor in world.map.get_cell_neighbors(cell):
            key = (neighbor.row, neighbor.col)
            owner = neighbor.country
            if owner is not None and owner != country and key not in seen:
                seen.add(key)
                action = AttackCell(country, owner, neighbor)
                if action.is_possible(world):
                    actions.append(action)
    return actions


def possible_pact_actions(world: World, country: Country) -> list[OfferPact]:
    # Each component is offered separately, so a full pact is built up over
    # three turns and a relationship can stop at any depth.
    actions = []
    for other in world.get_diplomacies(country):
        for pact in Pact:
            action = OfferPact(country, other, pact)
            if action.is_possible(world):
                actions.append(action)
    return actions


def possible_union_actions(world: World, country: Country) -> list[ProposeUnion]:
    actions = []
    for other in world.get_diplomacies(country):
        action = ProposeUnion(country, other)
        if action.is_possible(world):
            actions.append(action)
    return actions


def possible_actions(world: World, country: Country) -> list[Action]:
    """Everything `country` could legally do right now."""
    return [
        *possible_explore_actions(world, country),
        *possible_attack_actions(world, country),
        *possible_pact_actions(world, country),
        *possible_union_actions(world, country),
    ]

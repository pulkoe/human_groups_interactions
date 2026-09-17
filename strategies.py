"""How a population decides what to do.

A strategy is stateless: it reads the world and the country, and returns one
action.  Each strategy is described by three trait probabilities (the
diplomacy / peacefulness / union tendency of the assignment) plus the rules
that make it recognisable -- who it is willing to attack and what it is
willing to sign.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from actions import (
    Action,
    AttackCell,
    possible_actions,
    possible_attack_actions,
    possible_explore_actions,
    possible_pact_actions,
    possible_union_actions,
)
from config import PEACE_PACTS, Pact
from model import Country, World


@dataclass(frozen=True)
class Traits:
    """Probabilities that shape a country's turn.

    `aggression` is the assignment's "peacefulness" under a name that matches
    its meaning: the probability of using an attack that is on the table.
    """

    diplomacy: float = 0.5
    """Probability of proposing or accepting a non-aggression or trade pact."""
    aggression: float = 0.3
    """Probability of attacking when an acceptable target exists."""
    union_tendency: float = 0.2
    """Probability of proposing or accepting an alliance or a consolidation."""
    min_win_chance: float = 0.35
    """Odds below which an attack is not considered worth it."""


def hostility(world: World, viewer: Country, diplomacy) -> float:
    """How much `viewer` dislikes the other side, as 0.0 to 1.0."""
    score = diplomacy.score(viewer)
    if score >= 0:
        return 0.0
    return min(1.0, -score / abs(world.config.relationship_min))


class Strategy(ABC):
    name: str = "abstract"
    traits: Traits = Traits()

    # -- the turn ---------------------------------------------------------

    def choose_action(self, world: World, me: Country) -> Action | None:
        """One action per turn, picked by rolling the traits in order of
        commitment: union, war, diplomacy, and otherwise expansion.

        The order matters as much as the probabilities: a country that rolls
        badly on war still gets to try diplomacy in the same turn, so a low
        aggression does not mean a wasted turn.
        """
        rng = world.rng

        unions = possible_union_actions(world, me)
        if unions and rng.random() < self.traits.union_tendency:
            return rng.choice(unions)

        attacks = [
            action
            for action in possible_attack_actions(world, me)
            if self.wants_attack(world, me, action)
        ]
        if attacks and rng.random() < self.traits.aggression:
            return self.pick_attack(world, me, attacks)

        offers = [
            action
            for action in possible_pact_actions(world, me)
            if self.accepts_pact(world, me, action.receiver, action.pact)
        ]
        if offers and rng.random() < self.traits.diplomacy:
            return rng.choice(offers)

        # Free land is always worth taking, so exploring is the default move.
        explorations = possible_explore_actions(world, me)
        if explorations:
            return rng.choice(explorations)
        # Boxed in, with every roll above failed: doing the second-choice
        # thing still beats standing still for a turn.
        if offers:
            return rng.choice(offers)
        if attacks:
            return self.pick_attack(world, me, attacks)
        return None

    # -- the decisions a strategy is defined by ---------------------------

    def wants_attack(self, world: World, me: Country, action: AttackCell) -> bool:
        """Default: attack a promising target, but keep your word.

        Dislike makes an attack likelier, as the assignment asks: the odds a
        country insists on before striking shrink towards zero the more it
        resents its neighbour.
        """
        diplomacy = world.get_diplomacy(me, action.defender)
        if diplomacy.pacts & PEACE_PACTS:
            return False
        # At maximum resentment the requirement reaches zero, which is how a
        # war can start between two countries the numbers say should not fight.
        required = self.traits.min_win_chance * (1 - hostility(world, me, diplomacy))
        return world.estimate_win_chance(me, action.defender) >= required

    def pick_attack(
        self, world: World, me: Country, attacks: list[AttackCell]
    ) -> AttackCell:
        """Default: hit wherever the odds are best."""
        return max(
            attacks, key=lambda a: world.estimate_win_chance(me, a.defender)
        )

    def accepts_pact(
        self, world: World, me: Country, other: Country, pact: Pact
    ) -> bool:
        """Used both when offering and when answering an offer.

        The same test on both sides is deliberate: a strategy that will not
        sign something never proposes it either.
        """
        chance = (
            self.traits.union_tendency
            if pact is Pact.MILITARY_ALLIANCE
            else self.traits.diplomacy
        )
        return world.rng.random() < chance

    def accepts_union(self, world: World, me: Country, other: Country) -> bool:
        return world.rng.random() < self.traits.union_tendency

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class PeaceStrategy(Strategy):
    """Never attacks anyone, and is happy to sign anything."""

    name = "peace"
    traits = Traits(diplomacy=0.9, aggression=0.0, union_tendency=0.5)

    def wants_attack(self, world: World, me: Country, action: AttackCell) -> bool:
        return False


class HegemonyStrategy(Strategy):
    """Attacks every population it meets, as long as the odds are not hopeless.

    It refuses anything that would tie its hands, but trades happily.
    """

    name = "hegemony"
    traits = Traits(
        diplomacy=0.2, aggression=0.95, union_tendency=0.0, min_win_chance=0.3
    )

    # `wants_attack` is the default one: hegemony never signs a peace pact, so
    # the only thing holding it back is the odds -- and resentment lowers even
    # those.

    def accepts_pact(
        self, world: World, me: Country, other: Country, pact: Pact
    ) -> bool:
        if pact is not Pact.TRADE_AGREEMENT:
            return False
        return world.rng.random() < self.traits.diplomacy

    def accepts_union(self, world: World, me: Country, other: Country) -> bool:
        return False


class SwitzerlandStrategy(Strategy):
    """Neutral: talks to everyone, but never promises military help.

    It differs from `peace` only in what it signs -- which is exactly the
    point of the comparison, since an alliance costs casualties when the
    side it joined loses a battle.
    """

    name = "switzerland"
    traits = Traits(diplomacy=0.9, aggression=0.0, union_tendency=0.0)

    def wants_attack(self, world: World, me: Country, action: AttackCell) -> bool:
        return False

    def accepts_pact(
        self, world: World, me: Country, other: Country, pact: Pact
    ) -> bool:
        if pact is Pact.MILITARY_ALLIANCE:
            return False
        return world.rng.random() < self.traits.diplomacy

    def accepts_union(self, world: World, me: Country, other: Country) -> bool:
        return False


class RetaliationStrategy(Strategy):
    """Never starts a war, but strikes back at whoever attacked it recently.

    Retaliation ignores the odds -- that is what makes the threat credible --
    and the memory is deliberately short (`SimConfig.retaliation_window`), so
    a war it did not start can still end.
    """

    name = "retaliation"
    # High aggression with no minimum odds: it almost never has a target, but
    # when it does, it goes regardless of whether it can win.
    traits = Traits(
        diplomacy=0.7, aggression=0.95, union_tendency=0.3, min_win_chance=0.0
    )

    def _has_grudge(self, world: World, me: Country, other: Country) -> bool:
        last_attack = me.grudges.get(other)
        if last_attack is None:
            return False
        return world.turn - last_attack <= world.config.retaliation_window

    def wants_attack(self, world: World, me: Country, action: AttackCell) -> bool:
        return self._has_grudge(world, me, action.defender)

    def pick_attack(
        self, world: World, me: Country, attacks: list[AttackCell]
    ) -> AttackCell:
        """Hit the most recent offender first."""
        return max(attacks, key=lambda a: me.grudges.get(a.defender, -1))


class RandomStrategy(Strategy):
    """Baseline: picks uniformly among everything it could legally do."""

    name = "random"
    traits = Traits(diplomacy=0.5, aggression=0.5, union_tendency=0.5, min_win_chance=0.0)

    def choose_action(self, world: World, me: Country) -> Action | None:
        options = possible_actions(world, me)
        return world.rng.choice(options) if options else None


# The registry the CLI, the scenarios and the tests all look names up in.
STRATEGIES: dict[str, type[Strategy]] = {
    strategy.name: strategy
    for strategy in (
        PeaceStrategy,
        HegemonyStrategy,
        SwitzerlandStrategy,
        RetaliationStrategy,
        RandomStrategy,
    )
}


def make_strategy(name: str) -> Strategy:
    try:
        return STRATEGIES[name]()
    except KeyError:
        raise ValueError(
            f"unknown strategy {name!r}; available: {', '.join(sorted(STRATEGIES))}"
        ) from None

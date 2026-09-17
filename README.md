# Human group interaction simulation

A grid world in which populations explore, fight, and make pacts.  The point
of the model is to compare *strategies*: does it pay to attack everyone you
meet, to never attack anyone, to stay out of every alliance, or to always
strike back?

The simulation itself uses the standard library. The report workflow adds
Matplotlib for publication-quality figures.

```sh
uv run tests.py                                    # self-checks
uv run main.py --list                              # scenarios and strategies
uv run main.py --scenario all_strategies --runs 20 # one comparison
uv run main.py --all --runs 20 --csv-dir out       # every condition, with CSV
uv run main.py --scenario duel:peace,hegemony --runs 50
uv run main.py --set defender_multiplier=3 --set growth_rate=0.1
uv run analysis.py collect --runs 100 --seed 0 --output results
uv run analysis.py plot --input results/data --output results/figures
uv run analysis.py all --runs 100 --seed 0 --output results
```

The report analysis deliberately has two phases. `collect` runs every built-in
scenario and the approved parameter sweeps, then stores the raw observations
under `results/data`. `plot` reads only those files, so visual changes do not
rerun the stochastic simulation. `all` is a convenience command for both.
Collection reports each completed condition as `[current/total] label`, so a
full default run advances from `[ 1/25]` to `[25/25]` without another package.

After generating the figures, compile the English report with:

```sh
cd report
pdflatex -interaction=nonstopmode -halt-on-error report.tex
pdflatex -interaction=nonstopmode -halt-on-error report.tex
```

## Modules

| File | Contents |
|---|---|
| `config.py` | `SimConfig` -- every tunable parameter; pact thresholds and bonuses |
| `model.py` | `Cell`, `Map`, `Country`, `Diplomacy`, `World`, the turn loop |
| `actions.py` | `ExploreCell`, `AttackCell`, `OfferPact`, `ProposeUnion` |
| `strategies.py` | Traits and the five strategies |
| `metrics.py` | Time series, per-run summaries, aggregation, CSV, text tables |
| `experiment.py` | Scenarios, the multi-seed runner, report formatting |
| `main.py` | Command line interface |
| `analysis.py` | Repeated scenarios and sweeps, persisted as CSV/JSON |
| `plots.py` | Six report figures generated only from saved data |
| `report/report.tex` | English semester-project report |
| `tests.py` | Self-checks, run directly (no test framework) |

## Report outputs

Collection writes combined files for scenario runs, scenario statistics,
parameter-sweep runs and statistics, representative time series, final maps,
and a machine-readable manifest. Plotting creates these stable figure pairs:

1. `01_final_maps.pdf` / `.png`
2. `02_baseline_outcomes.pdf` / `.png`
3. `03_scenario_heatmaps.pdf` / `.png`
4. `04_parameter_sweeps.pdf` / `.png`
5. `05_strategic_context.pdf` / `.png`
6. `06_sample_dynamics.pdf` / `.png`

PDF versions are included by LaTeX; PNG versions are convenient for visual
inspection. Seed 0 supplies only the representative maps and dynamics. All
comparative conclusions use repeated runs.

## The world

A square grid.  One cell is one unit of area, produces one unit of food, and
feeds up to `cell_capacity` people.  A population grows logistically towards
the carrying capacity of the territory it controls and starves back down when
it loses land.  Everyone starts at the same technological level.

A country holds a **population**, a set of **controlled cells**, a set of
**known cells**, and a **strategy**.  A strategy is described by three trait
probabilities -- diplomacy, aggression (the assignment's "peacefulness"), and
union tendency -- plus the rules that make it recognisable.

Each turn every living country, in a freshly shuffled order, takes **one**
action: explore an unclaimed neighbouring cell, attack one cell of a
neighbour, offer one component of a pact, or propose a consolidation.

### Relationships

Attitudes are **directional**: how A feels about B need not match how B feels
about A.  They run from -100 to +100, drift one point back towards neutral
every turn, and drop sharply when attacked (-50), when a cell is lost (-10),
when a pact is broken (-50), and when a third party joins a war against you
(-20).  Breaking a pact also costs the oathbreaker 20 points with every other
country it has promised peace to.

Pacts are **symmetrical** and have three independent components:

| Pact | Needs mutual attitude | Effect |
|---|---|---|
| Trade agreement | 0 | Raises carrying capacity by 10% per partner |
| Non-aggression | 30 | Attacking breaks it, at a heavy cost |
| Military alliance | 50 | The ally joins your battles -- and shares the casualties |

Trade sits at neutral deliberately: it is the only thing two strangers can
agree on, and the goodwill a standing pact generates (+2 to +5 per turn) is
what makes the deeper pacts reachable at all.  A pact whose relationship sinks
more than 10 below its threshold simply **lapses**, which is not the same as
breaking it.

A negative attitude also makes an attack likelier: the odds a country insists
on before striking shrink in proportion to how much it resents the target, so
resentment alone can start a war the numbers would not justify.

Alliances are **not transitive**: an ally of both sides stays out of the
fight, and an ally that shares no border with the opponent cannot help.

### War

Strength is `population / territory ** 0.5`: a larger population is stronger,
but with diminishing returns, because force has to be projected across more
cells.  The defender's strength is multiplied by 1.5.  The winner is drawn at
random with probability `attack / (attack + defence)`.

The people living in the contested cell are the stake.  If the attacker wins
it takes the cell, half of those people join the conqueror and the rest are
lost; if it loses, it pays 40% of the stake in casualties.  Casualties are
split over everyone who fought on that side, which is what an ally actually
risks by signing.

A country is eliminated when it loses its last cell (`conquered`), when its
population reaches zero (`collapsed`), or when it is absorbed by a union
(`union`).  Land left behind by a collapse returns to being unclaimed.

## Strategies

| Strategy | Attacks | Signs |
|---|---|---|
| `peace` | never | anything |
| `switzerland` | never | anything except a military alliance or a union |
| `hegemony` | anyone it meets, unless the odds are hopeless | trade only |
| `retaliation` | only whoever attacked it in the last 10 turns, regardless of odds | most things |
| `random` | baseline: picks uniformly among all legal moves | coin flip |

## Measures of success

Every run produces, per country: survival (did it last, and for how many
turns, and what killed it), final and peak population, final and peak
territory and its share of the map, and whether it ended up the largest
country (`dominant`).  Alongside those: attacks made and suffered, battles
won, cells conquered, lost and explored, casualties, contacts made, pacts
formed, broken and lapsed, and the number of turns spent inside each kind of
pact.  These are aggregated per strategy over the seeds, with mean, median and
standard deviation of the final population.

One country in one run is one observation, so a scenario fielding two
hegemonies contributes two observations for that strategy.

## Design decisions

The assignment left several questions open.  The answers chosen here, all of
them deliberately the simplest defensible rule:

1. **Order of action.** Sequential, in a fresh random order every turn, so
   nobody has a permanent first-mover advantage.
2. **Does part of a conquered population join the conqueror?** Yes -- half of
   the cell's inhabitants; the rest are lost.
3. **Several populations attacking the same one.** Nothing special: attacks
   resolve one after another against the current state, so a weakened
   defender really is easier to finish off.
4. **Two populations exploring the same cell.** Whoever acts first gets it;
   the other finds the cell taken and its action lapses.  No fight over
   unclaimed land.
5. **When does a war end?** There is no explicit state of war.  Attacks are
   per-turn decisions, and because attitudes drift back towards neutral, the
   hostility that drives them fades on its own.
6. **If A helps B against C and B loses?** A pays a share of the casualties,
   proportional to the strength it committed, and C resents it afterwards.
7. **Should the food system be removed?** Yes.  Food is already implicit in
   the carrying capacity of a cell, so an explicit food stock and an "ask for
   food" action would add state without adding behaviour.  Food sharing
   survives as the trade agreement, which raises the carrying capacity.

## Limitations

- One action per country per turn, so a large empire acts no more often than
  a single-cell one; the `population / territory ** 0.5` power rule is the
  only counterweight to that.
- Territory is a flat grid: no terrain, no distance costs, no capital, and
  cells are worth the same everywhere.
- Populations are homogeneous -- no internal cohesion, no split into
  providers, warriors and scientists, and no technological progress.
- Strategies are fixed for the whole run.  A country cannot learn, change
  its mind, or read another country's strategy.
- A consolidation is a clean merge: the larger population absorbs the
  smaller, and the successor inherits the average of the two attitudes
  towards everyone else.  Nothing models the union falling apart later.
- "Dominance" is measured at the turn limit, which favours whoever happens to
  be ahead when the clock stops; runs that end early (one survivor) are not
  distinguished from those that hit the limit.

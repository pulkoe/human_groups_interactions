# Experiment, Plotting, and Report Design

**Date:** 2026-09-16

**Project:** Human Groups Strategies

**Author:** Ekaterina Pulko

## Purpose

Extend the existing human-group interaction simulation with a reproducible
analysis pipeline and an English semester-project report. The pipeline will
first run every experiment and persist its raw observations, then create all
figures exclusively from those saved observations. This separation makes it
possible to revise figures and prose without rerunning the stochastic model
and keeps every conclusion traceable to a CSV row.

The report will follow the supplied LaTeX template and the scientific pattern
of the example report: introduce the question, define the model and
parameters, document the experiment design, present quantitative figures,
interpret those figures, and state limitations. The example report is a
layout and depth reference only; the final report will be written in English
and will analyze this project's own results.

## Scope

The work includes:

- a command-line analysis entry point with separate `collect`, `plot`, and
  `all` commands;
- repeated runs of all ten existing scenarios;
- controlled sweeps of map size, defender advantage, and population growth;
- combined raw and aggregated CSV datasets;
- six stable, publication-ready figure groups in vector PDF and preview PNG;
- an English LaTeX report and compiled PDF;
- tests for data collection, aggregation, and figure generation;
- README instructions for reproducing the data, plots, and report.

The simulation rules, strategy definitions, and existing scenario definitions
will not be changed. No animated output, interactive dashboard, notebook, or
new strategy is included.

## Architecture

The existing flow remains the source of truth:

```text
Scenario -> run_experiment() -> ExperimentResult -> metrics records
```

The new flow adds a persistence boundary before visualization:

```text
all scenarios and sweeps
          |
          v
analysis.py collect
          |
          v
results/data/*.csv + manifest.json
          |
          v
analysis.py plot
          |
          v
results/figures/*.pdf and *.png
          |
          v
report/report.tex -> report/report.pdf
```

`analysis.py` will coordinate experiments and file output. `plots.py` will
contain CSV readers, small statistical helpers, and the six plotting
functions. Keeping plotting independent of live `World` objects is the key
interface: deleting Python state after `collect` must not prevent any figure
from being regenerated.

Only Matplotlib will be added as a runtime dependency. CSV and JSON handling,
grouping, summary statistics, argument parsing, and paths will continue to use
the Python standard library. Pandas, Seaborn, SciPy, Jupyter, and a report
generation framework are intentionally excluded.

## Experiment Design

### Repeated built-in scenarios

Every scenario in `experiment.SCENARIOS` will run for 100 seeds by default,
using seeds 0 through 99 and each scenario's existing 300-turn configuration.
The run count and base seed remain configurable from the analysis CLI.

The scenarios divide naturally into two analytical families:

1. **Balanced environmental comparisons:** `all_strategies`, `crowded`,
   `spacious`, `strong_defence`, `weak_defence`, and `slow_growth`. Each fields
   one country per core strategy and can therefore compare strategies under
   altered world conditions.
2. **Strategic-composition comparisons:** `one_aggressor`,
   `many_aggressors`, `deterrence`, and `neutrals`. These test how a strategy's
   outcome changes with its neighbors. Because some strategies occur more
   than once in these scenarios, the report will state the number of country
   observations represented by every aggregate.

### Controlled parameter sweeps

Each sweep uses the `all_strategies` composition, changes one configuration
parameter, leaves every other default unchanged, and runs the same seed range
for every value.

| Sweep | Values |
|---|---|
| Map width and height | 8, 12, 16, 20, 26 |
| Defender multiplier | 1.0, 1.5, 2.0, 2.5, 3.0 |
| Population growth rate | 0.02, 0.035, 0.05, 0.075, 0.10 |

Using the same seed range at every value reduces avoidable differences between
conditions while preserving the model's stochastic variation. These sweeps
are descriptive sensitivity analyses, not causal estimates.

### Measures

The primary strategy outcomes are:

- survival rate;
- dominance rate;
- mean final territory share;
- final territory distribution.

Secondary outcomes explain how those results arose:

- final population and survival time;
- attacks made and suffered;
- casualties;
- pacts and alliance participation;
- cells explored, conquered, and lost.

All repeated observations contribute to conclusions. Seed 0 supplies the
representative final maps and time series, and these figures will be labeled
as illustrations rather than population estimates.

For line plots, the center is the arithmetic mean and the band is a 95%
normal-approximation confidence interval, `mean +/- 1.96 * standard error`.
Distribution plots will show the underlying spread directly. Rates in the
report will include both the numerator and observation count where space
allows. No hypothesis-testing threshold will be used.

## Persisted Data Contract

`analysis.py collect --runs 100 --output results` creates `results/data` and
writes the following stable files:

| File | One row represents |
|---|---|
| `scenario_runs.csv` | One country in one built-in scenario run |
| `scenario_stats.csv` | One strategy aggregated within one scenario |
| `sweep_runs.csv` | One country at one sweep value in one run |
| `sweep_stats.csv` | One strategy aggregated at one sweep value |
| `sample_country_turns.csv` | One country at one turn of a representative scenario run |
| `sample_world_turns.csv` | One world-level turn of a representative scenario run |
| `sample_final_maps.csv` | One grid cell in a representative scenario's final state |
| `manifest.json` | Run counts, seeds, scenario descriptions, configurations, sweep values, and schema version |

Combined files are preferred over one directory per scenario because all
report plots compare conditions. Rows will include explicit `scenario`,
`seed`, and strategy identifiers. Sweep rows additionally include `sweep` and
numeric `parameter_value` columns. Map rows include `row`, `column`, country,
strategy, and alive status; unclaimed cells use empty country and strategy
fields.

Collection will write headers even if a table is empty and will reject a
non-positive run count. Plotting will fail with a clear message naming any
missing or empty required data file. Output directories are created as
needed, and rerunning a phase deterministically replaces files with the same
stable names.

## Figures

Every plotting function will save the same Matplotlib figure twice: vector
PDF for LaTeX and 180-DPI PNG for inspection. Colors for the five strategies
will be defined once and reused in every chart. Labels, units, seed counts,
and legends will be explicit; color will not be the sole distinction where
lines overlap.

1. **`01_final_maps` - representative spatial outcomes.** A 2-by-2 panel of
   final maps for `all_strategies`, `one_aggressor`, `many_aggressors`, and
   `deterrence`. Cells are colored by strategy, unclaimed cells are light
   gray, and country borders are visually separable. The caption states that
   these are seed-0 examples.
2. **`02_baseline_outcomes` - baseline strategy distributions.** Three panels
   for final territory share, final population, and survival turns in the
   `all_strategies` scenario. Box plots show the run-to-run distribution and
   overlaid mean markers make strategy comparison direct.
3. **`03_scenario_heatmaps` - strategy performance across environments.**
   Three aligned heatmaps show survival rate, dominance rate, and mean final
   territory share for the six balanced scenarios. Each cell includes its
   numeric value.
4. **`04_parameter_sweeps` - environmental sensitivity.** Three panels show
   mean final territory share by strategy as map size, defender multiplier,
   and growth rate change. Lines use markers and 95% confidence bands.
5. **`05_strategic_context` - dependence on neighboring strategies.** Two
   panels compare survival rate and mean final territory share across
   `one_aggressor`, `many_aggressors`, `deterrence`, and `neutrals`. Missing
   strategy/scenario combinations are left blank rather than displayed as
   zero.
6. **`06_sample_dynamics` - how the baseline outcome develops.** Two panels
   plot population and territory over time for each country in seed 0 of
   `all_strategies`. Dead countries remain at zero so disappearance is
   visible. The caption explicitly limits inference from a single run.

## Report

`report/report.tex` will use the supplied title, author, and date:

- **Title:** Human Groups Strategies
- **Author:** Ekaterina Pulko
- **Date:** September 2026

It will remain a conventional one-column `article`, matching the supplied
Overleaf template rather than copying the example report's journal-specific
two-column layout. The report will contain:

1. **Abstract** - question, model, experiment scale, main measured result, and
   principal limitation.
2. **Introduction** - motivation for agent-based modeling of group strategy
   and the report's research question.
3. **Model** - world, groups, turn order, population growth, exploration,
   diplomacy, pacts, war, consolidation, strategies, outcome measures, and
   experiment design.
4. **Results** - baseline comparison, environmental sensitivity, strategic
   composition, and representative dynamics, with all six figures referenced
   and interpreted.
5. **Discussion** - answer to "What does a group strategy mainly depend on?"
   based on the measured cross-condition results, including trade-offs rather
   than declaring a universally best strategy.
6. **Limitations** - abstraction of people into homogeneous populations,
   uniform terrain, fixed strategies, sequential actions, finite runs,
   stochastic uncertainty, and limits of illustrative single-run figures.
7. **Conclusions** - concise answer and defensible next extensions.
8. **References** - a small set of verified sources on agent-based modeling,
   cooperation, and strategy, formatted directly with `thebibliography` to
   avoid an unnecessary BibTeX build dependency.

The prose will be written only after the final datasets and figures exist, so
the abstract, Results, Discussion, and Conclusions report actual numerical
outcomes. Figure captions will explain what is measured, the number of runs,
and the intended interpretation. The report will not claim statistical
significance or real-world predictive validity.

The LaTeX source will include `graphicx`, `booktabs`, `amsmath`, `geometry`,
`microtype`, `caption`, `float`, and `hyperref`. Figures will be referenced
from `../results/figures`. The compiled `report/report.pdf` will be rendered
page by page and visually checked for clipped plots, illegible labels, table
overflow, bad page breaks, unresolved references, and blank pages.

## Command-Line Interface

The stable commands will be:

```sh
uv run analysis.py collect --runs 100 --seed 0 --output results
uv run analysis.py plot --input results/data --output results/figures
uv run analysis.py all --runs 100 --seed 0 --output results
```

`all` is convenience composition: it runs `collect` and then `plot` with the
same paths. `plot` never imports or executes the simulation. Existing
`main.py` commands remain unchanged.

## Testing and Verification

Development will follow the existing plain-assert test style.

- A collection test will run a tiny scenario and one-value sweep in a
  temporary directory, then verify required files, headers, row counts,
  scenario identifiers, seeds, and manifest values.
- A statistical-helper test will verify means and confidence interval behavior
  for zero, one, and multiple observations.
- A plotting test will use the tiny collected fixture, run every applicable
  plot function with Matplotlib's non-interactive `Agg` backend, and verify
  that expected PDF and PNG files exist and are non-empty.
- Existing simulation tests will run unchanged to prove the analysis work did
  not alter model behavior.
- The full 100-seed collection will be checked for expected scenario/sweep
  coverage, valid rates, and plausible row counts before the report is
  written.
- Every final PNG and every rendered report page will receive visual review.

## Files

Planned source changes are deliberately small:

- **Create `analysis.py`:** CLI, experiment collection, CSV contracts, and
  manifest writing.
- **Create `plots.py`:** CSV loading, confidence intervals, consistent plot
  styling, and six figure functions.
- **Create `report/report.tex`:** English report using generated figures.
- **Modify `pyproject.toml`:** add Matplotlib.
- **Modify `tests.py`:** add focused analysis and plot checks.
- **Modify `README.md`:** document the reproducible workflow and outputs.
- **Generate `results/data/*`:** final raw and aggregated observations.
- **Generate `results/figures/*`:** final PDF and PNG figures.
- **Generate `report/report.pdf`:** visually verified compiled report.

No existing simulation module needs a new abstraction. Small serialization
helpers may be added to `analysis.py`; plotting-specific code will not be put
into `experiment.py` or `metrics.py`.

# Experiment, Plotting, and Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible two-phase experiment and plotting pipeline, generate the complete result dataset and six publication figures, and write and verify the English LaTeX semester report.

**Architecture:** `analysis.py collect` runs existing scenarios and controlled parameter sweeps into stable CSV/JSON files. `plots.py` reads only those persisted files and creates vector PDF plus PNG figures. The report is authored after the final data exists and references those figures directly.

**Tech Stack:** Python 3.14, standard-library `argparse`/`csv`/`json`/`statistics`, Matplotlib with the `Agg` backend, existing plain-assert tests, LaTeX/pdfLaTeX, Poppler visual verification.

**Spec:** `docs/superpowers/specs/2026-09-16-experiment-plots-report-design.md`

## Global Constraints

- Do not change simulation rules, strategies, metrics semantics, or existing scenario definitions.
- The report language is English; title is `Human Groups Strategies`, author is `Ekaterina Pulko`, and date is `September 2026`.
- Collection and plotting remain separate; plotting may not run simulations or depend on live `World` objects.
- Run all ten built-in scenarios and the three approved five-value sweeps.
- Default to 100 runs and seeds 0 through 99; keep `--runs` and `--seed` configurable.
- Save every figure as vector PDF and 180-DPI PNG with stable names `01` through `06`.
- Add Matplotlib only; do not add pandas, seaborn, scipy, a notebook, or a report-generation framework.
- Treat seed-0 maps and dynamics as illustrative; base report conclusions on repeated runs.
- Preserve the user's unrelated untracked files. Stage only files created or modified for this work.

---

### Task 0: Record the existing simulation baseline

**Files:**
- Stage without modification: `.gitignore`, `.python-version`, `README.md`,
  `actions.py`, `config.py`, `experiment.py`, `main.py`, `metrics.py`,
  `model.py`, `pyproject.toml`, `strategies.py`, `tests.py`, `uv.lock`
- Leave untracked: `Session.vim`

**Interfaces:**
- Produces: a reproducible Git baseline for the model that Tasks 1-6 extend.

- [ ] **Step 1: Verify the untouched baseline**

Run:

```sh
uv run tests.py
git status --short
```

Expected: all existing tests pass; the listed project files and `Session.vim`
are untracked; the approved spec is already committed.

- [ ] **Step 2: Stage only the project baseline**

Run:

```sh
git add .gitignore .python-version README.md actions.py config.py experiment.py main.py metrics.py model.py pyproject.toml strategies.py tests.py uv.lock
git diff --cached --stat
```

Expected: the staged set contains only the simulation, its tests, package
metadata, and project documentation. It does not contain `Session.vim` or the
implementation plan.

- [ ] **Step 3: Commit the baseline**

Run:

```sh
git commit -m "chore: record simulation baseline"
```

Expected: the model can be checked out from Git and `Session.vim` remains
untracked.

### Task 1: Persist complete scenario and sweep datasets

**Files:**
- Create: `analysis.py`
- Modify: `tests.py:8-16`, append tests before `main()`

**Interfaces:**
- Consumes: `experiment.SCENARIOS`, `experiment.CORE_STRATEGIES`, `experiment.run_experiment`, `dataclasses.replace`, and existing dataclass metric records.
- Produces: `SWEEPS`, `collect_results(output_dir: Path, runs: int = 100, base_seed: int = 0, scenarios: Mapping[str, Scenario] = SCENARIOS, sweeps: Mapping[str, tuple[str, tuple[float, ...]]] = SWEEPS) -> list[Path]`.
- Produces: the eight files defined by the spec in `output_dir`.

- [ ] **Step 1: Read the good-test rules before changing tests**

Run:

```sh
cat /Users/pavelyanushonak/.codex/plugins/cache/claude-plugins-official/superpowers/6.3.0/skills/test-driven-development/writing-good-tests.md
```

Expected: rules emphasize observable behavior, a named production change that breaks the test, and real files rather than mocks.

- [ ] **Step 2: Write the failing collection test**

Add imports for `csv`, `json`, `tempfile`, `Path`, `collect_results`, and `Scenario`. Add a test using a short two-country scenario and a one-value sweep:

```python
def test_collection_persists_complete_reproducible_inputs():
    tiny = Scenario(
        "tiny",
        "Test fixture.",
        ("peace", "hegemony"),
        replace(SimConfig(), map_width=5, turns=4),
    )
    with tempfile.TemporaryDirectory() as directory:
        paths = collect_results(
            Path(directory),
            runs=2,
            base_seed=7,
            scenarios={tiny.name: tiny},
            sweeps={"map_width": ("map_width", (5,))},
        )
        assert {path.name for path in paths} == {
            "scenario_runs.csv",
            "scenario_stats.csv",
            "sweep_runs.csv",
            "sweep_stats.csv",
            "sample_country_turns.csv",
            "sample_world_turns.csv",
            "sample_final_maps.csv",
            "manifest.json",
        }
        with (Path(directory) / "scenario_runs.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 4
        assert {int(row["seed"]) for row in rows} == {7, 8}
        assert {row["scenario"] for row in rows} == {"tiny"}
        with (Path(directory) / "sample_final_maps.csv").open(newline="") as handle:
            maps = list(csv.DictReader(handle))
        assert len(maps) == 25
        assert {row["scenario"] for row in maps} == {"tiny"}
        manifest = json.loads((Path(directory) / "manifest.json").read_text())
        assert manifest["schema_version"] == 1
        assert manifest["runs"] == 2
        assert manifest["base_seed"] == 7
        assert manifest["sweeps"]["map_width"]["values"] == [5]
```

Add a second minimal behavior test:

```python
def test_collection_rejects_non_positive_runs():
    with tempfile.TemporaryDirectory() as directory:
        try:
            collect_results(Path(directory), runs=0, scenarios={}, sweeps={})
        except ValueError as error:
            assert str(error) == "runs must be positive"
        else:
            assert False, "zero runs were accepted"
```

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```sh
uv run tests.py
```

Expected: import failure because `analysis.py` or `collect_results` does not exist; existing tests remain discoverable.

- [ ] **Step 4: Implement minimal deterministic collection**

Create `analysis.py` with:

```python
from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields, replace
from pathlib import Path

from experiment import CORE_STRATEGIES, SCENARIOS, Scenario, run_experiment
from metrics import CountrySummary, StrategyStats

SWEEPS = {
    "map_width": ("map_width", (8, 12, 16, 20, 26)),
    "defender_multiplier": ("defender_multiplier", (1.0, 1.5, 2.0, 2.5, 3.0)),
    "growth_rate": ("growth_rate", (0.02, 0.035, 0.05, 0.075, 0.10)),
}
```

Implement `_write_dicts(path, rows, fieldnames)` using `csv.DictWriter`, always writing a header. Implement `collect_results` so it:

1. rejects `runs <= 0`;
2. runs each supplied scenario once through `run_experiment`;
3. stores every `CountrySummary` via `asdict`;
4. prepends `scenario` to every `StrategyStats` row;
5. stores seed-0 country/world turns with explicit scenario and seed;
6. serializes every final map cell with scenario, seed, row, column, country, strategy, and alive;
7. constructs each sweep scenario by replacing only the named `SimConfig` field on `SCENARIOS["all_strategies"]`, assigns a stable scenario name such as `sweep_map_width_8`, and prepends sweep metadata to summary and stats rows;
8. writes the seven CSVs with explicit field orders derived from dataclass fields plus metadata columns;
9. writes `manifest.json` with schema version, run count, base seed, ordered scenario metadata/config dictionaries, and ordered sweep definitions;
10. returns the eight written paths in the table order from the specification.

Do not add plotting or CLI behavior yet.

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```sh
uv run tests.py
```

Expected: every existing and new test passes with no warning or traceback.

- [ ] **Step 6: Commit the collection boundary**

Run:

```sh
git add analysis.py tests.py
git commit -m "feat: persist scenario and sweep results"
```

Expected: only `analysis.py` and `tests.py` are included in the commit.

### Task 2: Add plotting dependency and statistical/IO helpers

**Files:**
- Modify: `pyproject.toml:7`
- Modify: `uv.lock`
- Create: `plots.py`
- Modify: `tests.py`, append tests before `main()`

**Interfaces:**
- Consumes: CSV contracts from Task 1.
- Produces: `mean_ci(values: Sequence[float]) -> tuple[float, float]`, `read_csv(path: str | Path) -> list[dict[str, str]]`, `save_figure(figure, output_dir: Path, stem: str) -> list[Path]`, and shared `STRATEGY_COLORS`/`STRATEGY_MARKERS`.

- [ ] **Step 1: Write failing helper tests**

```python
def test_mean_ci_handles_small_and_variable_samples():
    assert mean_ci([]) == (0.0, 0.0)
    assert mean_ci([4.0]) == (4.0, 0.0)
    mean, half_width = mean_ci([1.0, 2.0, 3.0])
    assert mean == 2.0
    assert half_width > 0


def test_plot_reader_names_missing_and_empty_inputs():
    with tempfile.TemporaryDirectory() as directory:
        missing = Path(directory) / "missing.csv"
        try:
            read_csv(missing)
        except ValueError as error:
            assert "missing.csv" in str(error)
        else:
            assert False, "missing input was accepted"
```

- [ ] **Step 2: Run tests and verify RED**

Run `uv run tests.py`.

Expected: import failure for `plots.mean_ci`/`plots.read_csv`.

- [ ] **Step 3: Add Matplotlib through the project package manager**

Run:

```sh
uv add matplotlib
```

Expected: `pyproject.toml` gains one Matplotlib dependency and `uv.lock` resolves its transitive packages for Python 3.14.

- [ ] **Step 4: Implement minimal plotting helpers**

Create `plots.py` and select the non-interactive backend before importing `pyplot`:

```python
from __future__ import annotations

import csv
import math
import statistics
from collections.abc import Sequence
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
```

Implement:

```python
def mean_ci(values: Sequence[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = statistics.fmean(values)
    half_width = 0.0 if len(values) == 1 else 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    return mean, half_width


def read_csv(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists():
        raise ValueError(f"missing plot input: {path}")
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty plot input: {path}")
    return rows
```

Add shared strategy order, accessible color palette, line markers, `_style_axes`, and `save_figure`. `save_figure` creates the output directory, calls `tight_layout`, writes `<stem>.pdf` and `<stem>.png` at 180 DPI, closes the figure, and returns both paths.

- [ ] **Step 5: Run tests and verify GREEN**

Run `uv run tests.py`.

Expected: all tests pass and Matplotlib uses `Agg` without opening a window.

- [ ] **Step 6: Commit helper layer**

```sh
git add pyproject.toml uv.lock plots.py tests.py
git commit -m "feat: add report plotting foundation"
```

### Task 3: Generate all six figure groups from CSV only

**Files:**
- Modify: `plots.py`
- Modify: `tests.py`, append plotting integration test before `main()`

**Interfaces:**
- Consumes: `results/data/*.csv` contract, never simulation modules.
- Produces: `plot_all(data_dir: Path, output_dir: Path) -> list[Path]` and twelve files from stems `01_final_maps` through `06_sample_dynamics`.

- [ ] **Step 1: Write the failing plotting integration test**

Extend the Task 1 fixture to use all five strategies, six balanced scenario names, four contextual scenario names, and one value for every sweep so each figure has valid input. Keep each scenario at `turns=2`, `map_width=5`, and `runs=1` to stay fast. Then assert:

```python
written = plot_all(data_dir, figure_dir)
expected = {
    f"{stem}.{suffix}"
    for stem in (
        "01_final_maps",
        "02_baseline_outcomes",
        "03_scenario_heatmaps",
        "04_parameter_sweeps",
        "05_strategic_context",
        "06_sample_dynamics",
    )
    for suffix in ("pdf", "png")
}
assert {path.name for path in written} == expected
assert all(path.stat().st_size > 1_000 for path in written)
```

- [ ] **Step 2: Run tests and verify RED**

Run `uv run tests.py`.

Expected: failure because `plot_all` and the figure functions do not exist.

- [ ] **Step 3: Implement the six plots minimally**

Add constants for balanced/contextual scenario order and implement:

```python
def plot_final_maps(data_dir: Path, output_dir: Path) -> list[Path]: ...
def plot_baseline_outcomes(data_dir: Path, output_dir: Path) -> list[Path]: ...
def plot_scenario_heatmaps(data_dir: Path, output_dir: Path) -> list[Path]: ...
def plot_parameter_sweeps(data_dir: Path, output_dir: Path) -> list[Path]: ...
def plot_strategic_context(data_dir: Path, output_dir: Path) -> list[Path]: ...
def plot_sample_dynamics(data_dir: Path, output_dir: Path) -> list[Path]: ...
def plot_all(data_dir: str | Path, output_dir: str | Path) -> list[Path]: ...
```

Implementation requirements:

- Final maps: reconstruct rectangular arrays from row/column fields; use a discrete colormap with light gray for unclaimed cells; make four panels and one figure-level legend.
- Baseline outcomes: group `scenario_runs.csv` rows from `all_strategies`; make box plots for territory share, population, and survival turns in fixed strategy order; overlay white-edged mean diamonds.
- Heatmaps: derive final territory share means from raw scenario rows, because existing `StrategyStats` has only cell counts; use `scenario_stats.csv` for survival/dominance; annotate each cell; render missing combinations as light gray.
- Sweeps: group raw `sweep_runs.csv` by sweep/value/strategy; calculate mean and CI of territory share; one panel per sweep, consistent strategy color plus unique marker, numeric x axis, and shared legend.
- Context: group raw contextual scenario rows for mean territory share and use stats for survival; grouped bars, no bar for a missing combination, and observation counts in a note under the axes.
- Dynamics: filter sample turn rows to `all_strategies`; plot population and territory by country, with the strategy determining color and country name in the legend.
- Every plot has English title, axis labels, units, readable 9-12 point text, restrained grid lines, and no duplicated legend.

- [ ] **Step 4: Run tests and verify GREEN**

Run `uv run tests.py`.

Expected: all tests pass and twelve non-empty files are produced in the temporary directory.

- [ ] **Step 5: Commit the figure pipeline**

```sh
git add plots.py tests.py
git commit -m "feat: plot strategy experiments from saved data"
```

### Task 4: Add the analysis CLI and reproducibility documentation

**Files:**
- Modify: `analysis.py`
- Modify: `README.md:8-33`
- Modify: `tests.py`, append CLI parsing test before `main()`

**Interfaces:**
- Produces: `build_parser() -> argparse.ArgumentParser` and `main(argv: list[str] | None = None) -> None`.
- `collect`: `--runs`, `--seed`, `--output`.
- `plot`: `--input`, `--output`.
- `all`: `--runs`, `--seed`, `--output`.

- [ ] **Step 1: Write a failing parser behavior test**

```python
def test_analysis_cli_has_separate_collect_plot_and_all_phases():
    parser = build_analysis_parser()
    collect_args = parser.parse_args(["collect", "--runs", "3", "--seed", "5", "--output", "x"])
    assert (collect_args.command, collect_args.runs, collect_args.seed, collect_args.output) == ("collect", 3, 5, "x")
    plot_args = parser.parse_args(["plot", "--input", "x/data", "--output", "x/figures"])
    assert (plot_args.command, plot_args.input, plot_args.output) == ("plot", "x/data", "x/figures")
```

- [ ] **Step 2: Run tests and verify RED**

Run `uv run tests.py`.

Expected: missing `build_parser` failure.

- [ ] **Step 3: Implement CLI behavior**

Use argparse subparsers with `required=True`. `collect` calls `collect_results(Path(output) / "data", ...)`; `plot` calls `plots.plot_all`; `all` collects to `<output>/data` and plots to `<output>/figures`. Print one `wrote <path>` line per artifact. Add `if __name__ == "__main__": main()`.

- [ ] **Step 4: Update README**

Replace “No dependencies” and “nothing draws a chart” with:

```sh
uv run tests.py
uv run analysis.py collect --runs 100 --seed 0 --output results
uv run analysis.py plot --input results/data --output results/figures
uv run analysis.py all --runs 100 --seed 0 --output results
```

Document the two-phase rationale, dataset filenames, figure filenames, report compilation command, and add `analysis.py`, `plots.py`, and `report/report.tex` to the module/artifact table. Preserve existing model documentation.

- [ ] **Step 5: Run tests and CLI help**

Run:

```sh
uv run tests.py
uv run analysis.py --help
uv run analysis.py collect --help
uv run analysis.py plot --help
```

Expected: tests pass; help names the three commands and their correct options.

- [ ] **Step 6: Commit CLI and docs**

```sh
git add analysis.py README.md tests.py
git commit -m "docs: document reproducible report workflow"
```

### Task 5: Run and validate the complete experiment suite

**Files:**
- Generate: `results/data/*.csv`
- Generate: `results/data/manifest.json`
- Generate: `results/figures/*.pdf`
- Generate: `results/figures/*.png`

**Interfaces:**
- Consumes: final Task 4 CLI.
- Produces: report-ready evidence and all twelve figure artifacts.

- [ ] **Step 1: Benchmark one run without changing outputs**

Run:

```sh
time uv run main.py --scenario all_strategies --runs 1 --no-map
```

Use the measured runtime to state an estimate before the full run. Keep the approved 100 runs unless it would exceed 30 minutes; if it would, report the estimate and ask before reducing the sample size.

- [ ] **Step 2: Run all scenarios and sweeps, then plot saved data**

Run:

```sh
uv run analysis.py all --runs 100 --seed 0 --output results
```

Expected: eight data files and twelve figure files, with one write line per path and no traceback.

- [ ] **Step 3: Validate coverage and numeric ranges**

Run a read-only Python check that asserts:

- manifest lists 10 scenarios, 3 sweeps, 5 values per sweep, 100 runs, and seed 0;
- `scenario_runs.csv` seeds are exactly 0-99 and contains each built-in scenario;
- `sweep_runs.csv` contains every sweep/value/strategy combination;
- `survived` and `dominant` values are 0 or 1;
- `territory_share` values are in `[0, 1]`;
- survival and dominance rates are in `[0, 1]`;
- all figure PDFs and PNGs exceed 1 KB.

Expected: print row counts and `validation passed`.

- [ ] **Step 4: Visually inspect all six PNG figures**

Open every PNG with the image-inspection tool. Check for clipped labels, unreadable annotations, overlapping legends, misleading axes, inconsistent strategy colors, excessive whitespace, and missing combinations shown as zeros. If any defect exists, add a failing regression assertion where practical, fix `plots.py`, rerun tests, then rerun only `analysis.py plot`.

- [ ] **Step 5: Record exact report results**

Use a read-only standard-library Python command to print, with observation counts:

- baseline survival, dominance, mean territory share, population, and survival time by strategy;
- best and worst strategy for each balanced scenario and primary metric;
- sweep endpoints and largest changes by strategy;
- contextual results for each strategy present;
- sample seed-0 country outcomes.

Save no interpretation yet; use this output as the numerical source for Task 6.

### Task 6: Write, compile, and visually verify the English report

**Files:**
- Create: `report/report.tex`
- Generate: `report/report.pdf`

**Interfaces:**
- Consumes: approved spec, README model details, validated numeric output, and `results/figures/*.pdf`.
- Produces: Overleaf-compatible source and final submission PDF.

- [ ] **Step 1: Verify references from primary sources**

Find 3-5 appropriate primary or authoritative sources for agent-based modeling, cooperation/evolutionary strategy, and Schelling-style spatial interaction. Record exact author, title, venue/publisher, year, and DOI or stable URL. Do not cite the example report as evidence about this model.

- [ ] **Step 2: Mark PDF artifact creation once**

Immediately before creating `report/report.tex`/`report.pdf`, run:

```sh
node container_tools/mark_artifact_operation_started.mjs --operation-kind create --expected-output-count 1 --output-format pdf
```

Expected: success. Do not run this marker again for later report edits.

- [ ] **Step 3: Write the LaTeX report from measured results**

Create `report/report.tex` from the supplied template, with `graphicx`, `booktabs`, `amsmath`, `geometry`, `microtype`, `caption`, `float`, and `hyperref`. Use `\graphicspath{{../results/figures/}}`. Include:

- title, author, date, and a results-based abstract;
- Introduction with research question and verified citations;
- Model subsections for World, Group, Population dynamics, Inter-group interactions, Strategies, Metrics, and Experimental design;
- Results subsections for Baseline outcomes, Environmental conditions, Strategic composition, and Representative dynamics;
- all six figures in numerical order, each with self-contained caption, 100-run sample size where relevant, and seed-0 caveat where relevant;
- Discussion answering what strategy mainly depends on, using actual measured contrasts;
- Limitations matching the implemented abstractions and statistical design;
- Conclusions with no unmeasured claim;
- direct `thebibliography` entries with stable URLs/DOIs.

Use ASCII hyphens in source prose. Escape LaTeX special characters in strategy/scenario names. Do not include placeholders, `TODO`, unsupported significance claims, or claims that the model predicts real societies.

- [ ] **Step 4: Compile twice and fail on warnings that affect output**

Run from `report/`:

```sh
pdflatex -interaction=nonstopmode -halt-on-error report.tex
pdflatex -interaction=nonstopmode -halt-on-error report.tex
```

Expected: `report.pdf` exists; no undefined references/citations, overfull boxes, missing figures, or fatal warnings in `report.log`.

- [ ] **Step 5: Check PDF structure and extracted text**

Run `pdfinfo report/report.pdf` and `pdftotext report/report.pdf -`. Confirm A4 pages, nonzero page count, title/author, Abstract through Conclusions, six figure captions, and References.

- [ ] **Step 6: Render and visually inspect every page**

Render with Poppler to a temporary QA directory and inspect every page image. Verify margins, page numbers, section hierarchy, figure readability, caption placement, table width, hyperlinks, and page breaks. Fix source and repeat compile/render until there are zero visual defects.

- [ ] **Step 7: Run final regression verification**

Run:

```sh
uv run tests.py
uv run analysis.py plot --input results/data --output results/figures
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=report report/report.tex
```

Expected: all tests pass, all twelve figures regenerate from CSV without simulation, and the final PDF compiles successfully.

- [ ] **Step 8: Commit report source and generated evidence**

Stage only requested artifacts and source changes; do not stage editor files:

```sh
git add analysis.py plots.py tests.py README.md pyproject.toml uv.lock results report/report.tex report/report.pdf
git commit -m "feat: add reproducible experiment report"
```

Expected: the commit contains the pipeline, tests, final datasets, figures, LaTeX source, and verified report PDF, but not `Session.vim` or unrelated user files.

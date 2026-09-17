"""Publication figures built only from persisted experiment CSV files.

Every figure function takes the directory `analysis.py collect` wrote and the
directory the figures go into, and returns the files it produced.  Nothing
here touches the simulation: a number that was not collected cannot appear in
a figure, which is what makes the report reproducible from the CSV files alone.
"""

from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

# One colour and one marker per strategy, shared by every figure, so that a
# strategy keeps the same identity throughout the report.
STRATEGY_ORDER = ("peace", "switzerland", "hegemony", "retaliation", "random")
STRATEGY_COLORS = {
    "peace": "#4C78A8",
    "switzerland": "#59A14F",
    "hegemony": "#E15759",
    "retaliation": "#F28E2B",
    "random": "#B07AA1",
}
STRATEGY_MARKERS = {
    "peace": "o",
    "switzerland": "s",
    "hegemony": "^",
    "retaliation": "D",
    "random": "X",
}
# Scenarios that field exactly one country per strategy.  Only these support a
# fair ranking, so they are the ones the heatmaps compare.
BALANCED_SCENARIOS = (
    "all_strategies",
    "crowded",
    "spacious",
    "strong_defence",
    "weak_defence",
    "slow_growth",
)
# Scenarios built around a deliberately lopsided composition.  The question
# there is how a strategy fares against particular neighbours, not who wins
# overall, so they stay out of the ranking and get a figure of their own.
CONTEXT_SCENARIOS = (
    "one_aggressor",
    "many_aggressors",
    "deterrence",
    "neutrals",
)
SCENARIO_LABELS = {
    "all_strategies": "Baseline",
    "crowded": "Crowded",
    "spacious": "Spacious",
    "strong_defence": "Strong defence",
    "weak_defence": "Weak defence",
    "slow_growth": "Slow growth",
    "one_aggressor": "One aggressor",
    "many_aggressors": "Many aggressors",
    "deterrence": "Deterrence",
    "neutrals": "Neutrals",
}


def mean_ci(values: Sequence[float]) -> tuple[float, float]:
    """Return the arithmetic mean and normal 95% CI half-width.

    Every value comes from an independent seed and the report collects a
    hundred of them, so the normal approximation is good enough here; a
    single run has no uncertainty to report at all.
    """
    if not values:
        return 0.0, 0.0
    mean = statistics.fmean(values)
    half_width = (
        0.0
        if len(values) == 1
        else 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    )
    return mean, half_width


def read_csv(path: str | Path) -> list[dict[str, str]]:
    """Read a required plotting input and name missing or empty files clearly."""
    path = Path(path)
    if not path.exists():
        raise ValueError(f"missing plot input: {path}")
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty plot input: {path}")
    return rows


def style_axes(axis) -> None:
    """The shared look: a faint horizontal grid behind the data, no frame."""
    axis.grid(axis="y", color="#D9D9D9", linewidth=0.6, alpha=0.7)
    axis.set_axisbelow(True)
    axis.spines[["top", "right"]].set_visible(False)


def save_figure(figure, output_dir: str | Path, stem: str) -> list[Path]:
    """Save one figure for LaTeX and one preview, then release its memory."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = [output_dir / f"{stem}.pdf", output_dir / f"{stem}.png"]
    figure.savefig(paths[0], bbox_inches="tight")
    figure.savefig(paths[1], dpi=180, bbox_inches="tight")
    plt.close(figure)
    return paths


def _strategy_handles() -> list[Patch]:
    return [
        Patch(facecolor=STRATEGY_COLORS[strategy], label=strategy.title())
        for strategy in STRATEGY_ORDER
    ]


def plot_final_maps(data_dir: Path, output_dir: Path) -> list[Path]:
    """Figure 1: what the map looks like when the clock stops, for one seed.

    Cells are coloured by strategy rather than by country, so two hegemonies
    come out in the same red; the white lines drawn below are what still
    tells them apart.
    """
    rows = read_csv(data_dir / "sample_final_maps.csv")
    # The baseline, then the three lopsided compositions -- four panels fit.
    scenarios = ("all_strategies", *CONTEXT_SCENARIOS[:3])
    # Index 0 is unclaimed land, then one index per strategy.
    colors = ["#EEEEEE", *(STRATEGY_COLORS[s] for s in STRATEGY_ORDER)]
    strategy_index = {strategy: index + 1 for index, strategy in enumerate(STRATEGY_ORDER)}
    figure, axes = plt.subplots(2, 2, figsize=(10, 9))

    for axis, scenario in zip(axes.flat, scenarios):
        selected = [row for row in rows if row["scenario"] == scenario]
        if not selected:
            raise ValueError(f"sample map missing scenario: {scenario}")
        height = max(int(row["row"]) for row in selected) + 1
        width = max(int(row["column"]) for row in selected) + 1
        matrix = [[0 for _ in range(width)] for _ in range(height)]
        countries: dict[tuple[int, int], str] = {}
        for row in selected:
            row_index, column_index = int(row["row"]), int(row["column"])
            matrix[row_index][column_index] = strategy_index.get(row["strategy"], 0)
            countries[(row_index, column_index)] = row["country"]
        axis.imshow(
            matrix,
            cmap=ListedColormap(colors),
            vmin=-0.5,
            vmax=len(colors) - 0.5,
            interpolation="nearest",
        )
        # Draw a white line wherever two different countries meet, including
        # two that play the same strategy and therefore share a colour.
        for row_index in range(height):
            for column_index in range(width):
                country = countries[(row_index, column_index)]
                if column_index + 1 < width and country != countries[(row_index, column_index + 1)]:
                    axis.plot(
                        [column_index + 0.5, column_index + 0.5],
                        [row_index - 0.5, row_index + 0.5],
                        color="white",
                        linewidth=0.7,
                    )
                if row_index + 1 < height and country != countries[(row_index + 1, column_index)]:
                    axis.plot(
                        [column_index - 0.5, column_index + 0.5],
                        [row_index + 0.5, row_index + 0.5],
                        color="white",
                        linewidth=0.7,
                    )
        axis.set_title(SCENARIO_LABELS[scenario])
        axis.set_xticks([])
        axis.set_yticks([])
        axis.set_aspect("equal")

    handles = [Patch(facecolor="#EEEEEE", label="Unclaimed"), *_strategy_handles()]
    figure.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.01),
        ncol=6,
        frameon=False,
    )
    figure.suptitle("Representative final territories (seed 0)", fontsize=14)
    figure.subplots_adjust(bottom=0.10, top=0.92, hspace=0.10, wspace=0.08)
    return save_figure(figure, output_dir, "01_final_maps")


def plot_baseline_outcomes(data_dir: Path, output_dir: Path) -> list[Path]:
    """Figure 2: the three success measures of the assignment, on the baseline.

    Box plots rather than bars, because the spread over seeds is the whole
    story: in a stochastic model a single run says almost nothing, and two
    strategies with the same mean can behave quite differently.
    """
    rows = [
        row
        for row in read_csv(data_dir / "scenario_runs.csv")
        if row["scenario"] == "all_strategies"
    ]
    metrics = (
        ("territory_share", "Final territory share (%)", lambda value: 100 * float(value)),
        ("final_population", "Final population", float),
        ("survival_turns", "Survival time (turns)", float),
    )
    figure, axes = plt.subplots(1, 3, figsize=(14, 4.8))
    labels = [strategy.title() for strategy in STRATEGY_ORDER]

    for axis, (column, title, convert) in zip(axes, metrics):
        values = [
            [convert(row[column]) for row in rows if row["strategy"] == strategy]
            for strategy in STRATEGY_ORDER
        ]
        boxes = axis.boxplot(
            values,
            tick_labels=labels,
            patch_artist=True,
            showfliers=True,
            medianprops={"color": "#222222", "linewidth": 1.4},
            flierprops={"markersize": 2.5, "alpha": 0.35},
        )
        for box, strategy in zip(boxes["boxes"], STRATEGY_ORDER):
            box.set_facecolor(STRATEGY_COLORS[strategy])
            box.set_alpha(0.75)
        # The box already shows the median; the mean is worth drawing next to
        # it, because a handful of runaway runs pulls the two far apart.
        means = [statistics.fmean(group) for group in values]
        axis.scatter(
            range(1, len(means) + 1),
            means,
            marker="D",
            s=34,
            color="white",
            edgecolor="#222222",
            linewidth=0.8,
            zorder=3,
            label="Mean",
        )
        axis.set_title(title)
        axis.tick_params(axis="x", rotation=28)
        style_axes(axis)
    figure.text(0.5, 0.015, "White diamonds denote arithmetic means.", ha="center", fontsize=9)
    figure.suptitle("Baseline outcomes across repeated runs", fontsize=14)
    figure.tight_layout(rect=(0, 0.06, 1, 0.93))
    return save_figure(figure, output_dir, "02_baseline_outcomes")


def plot_scenario_heatmaps(data_dir: Path, output_dir: Path) -> list[Path]:
    """Figure 3: strategy against environment, one cell per combination.

    All three metrics live on a 0-1 scale, so one colour scale serves all of
    them and the three panels can be read side by side.
    """
    stats = read_csv(data_dir / "scenario_stats.csv")
    runs = read_csv(data_dir / "scenario_runs.csv")
    stats_lookup = {
        (row["scenario"], row["strategy"]): row
        for row in stats
        if row["scenario"] in BALANCED_SCENARIOS
    }
    # Territory is re-averaged from the raw runs as a *share* of the map.
    # `scenario_stats.csv` reports mean cell counts, and those cannot be
    # compared across scenarios whose maps differ in size (crowded is 8x8,
    # spacious 26x26).
    territory: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in runs:
        if row["scenario"] in BALANCED_SCENARIOS:
            territory[(row["scenario"], row["strategy"])].append(
                float(row["territory_share"])
            )

    metrics = (
        ("survival_rate", "Survival rate"),
        ("dominance_rate", "Dominance rate"),
        ("territory_share", "Mean final territory share"),
    )
    figure, axes = plt.subplots(1, 3, figsize=(15, 5.8), sharey=True)
    colormap = matplotlib.colormaps["Blues"].copy()
    # Grey marks a combination that never occurred, which is not the same
    # thing as a strategy that scored zero.
    colormap.set_bad("#EEEEEE")

    for axis, (metric, title) in zip(axes, metrics):
        matrix: list[list[float]] = []
        for scenario in BALANCED_SCENARIOS:
            line = []
            for strategy in STRATEGY_ORDER:
                if metric == "territory_share":
                    values = territory.get((scenario, strategy), [])
                    line.append(statistics.fmean(values) if values else math.nan)
                else:
                    row = stats_lookup.get((scenario, strategy))
                    line.append(float(row[metric]) if row else math.nan)
            matrix.append(line)
        image = axis.imshow(matrix, cmap=colormap, vmin=0, vmax=1, aspect="auto")
        for row_index, line in enumerate(matrix):
            for column_index, value in enumerate(line):
                # Empty cells stay blank; the rest are labelled in light text
                # on the dark end of the scale and dark text on the light end.
                if not math.isnan(value):
                    axis.text(
                        column_index,
                        row_index,
                        f"{value:.0%}",
                        ha="center",
                        va="center",
                        fontsize=8,
                        color="white" if value > 0.58 else "#222222",
                    )
        axis.set_xticks(range(len(STRATEGY_ORDER)), [s.title() for s in STRATEGY_ORDER])
        axis.set_yticks(
            range(len(BALANCED_SCENARIOS)),
            [SCENARIO_LABELS[s] for s in BALANCED_SCENARIOS],
        )
        axis.tick_params(axis="x", rotation=35)
        axis.tick_params(labelleft=True)
        axis.set_title(title)
        figure.colorbar(image, ax=axis, fraction=0.046, pad=0.04, format="{x:.0%}")
    figure.suptitle("Strategy performance across environmental conditions", fontsize=14)
    figure.tight_layout(rect=(0, 0, 1, 0.94))
    return save_figure(figure, output_dir, "03_scenario_heatmaps")


def plot_parameter_sweeps(data_dir: Path, output_dir: Path) -> list[Path]:
    """Figure 4: one parameter varied at a time, everything else at baseline.

    Because only one setting moves along a panel, a line that bends is a real
    sensitivity to that parameter rather than a side effect of another one.
    """
    rows = read_csv(data_dir / "sweep_runs.csv")
    sweep_order = ("map_width", "defender_multiplier", "growth_rate")
    sweep_titles = {
        "map_width": ("Map size", "Map width (cells)"),
        "defender_multiplier": ("Defender advantage", "Defender multiplier"),
        "growth_rate": ("Population growth", "Growth rate"),
    }
    grouped: dict[tuple[str, float, str], list[float]] = defaultdict(list)
    for row in rows:
        grouped[(row["sweep"], float(row["parameter_value"]), row["strategy"])].append(
            100 * float(row["territory_share"])
        )

    figure, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    for axis, sweep in zip(axes, sweep_order):
        x_values = sorted(
            {float(row["parameter_value"]) for row in rows if row["sweep"] == sweep}
        )
        for strategy in STRATEGY_ORDER:
            points = [mean_ci(grouped.get((sweep, value, strategy), [])) for value in x_values]
            means = [point[0] for point in points]
            intervals = [point[1] for point in points]
            axis.plot(
                x_values,
                means,
                color=STRATEGY_COLORS[strategy],
                marker=STRATEGY_MARKERS[strategy],
                linewidth=1.7,
                markersize=5,
                label=strategy.title(),
            )
            # The band is the 95% confidence interval of the mean, not the
            # spread of the runs: it says how firmly the mean is pinned down.
            axis.fill_between(
                x_values,
                [mean - interval for mean, interval in points],
                [mean + interval for mean, interval in points],
                color=STRATEGY_COLORS[strategy],
                alpha=0.14,
                linewidth=0,
            )
        title, x_label = sweep_titles[sweep]
        axis.set_title(title)
        axis.set_xlabel(x_label)
        axis.set_ylabel("Mean final territory share (%)")
        axis.set_ylim(bottom=0)
        style_axes(axis)
    axes[-1].legend(frameon=False, bbox_to_anchor=(1.02, 1), loc="upper left")
    figure.suptitle("Sensitivity to world parameters (mean and 95% CI)", fontsize=14)
    figure.tight_layout(rect=(0, 0, 0.90, 0.94))
    return save_figure(figure, output_dir, "04_parameter_sweeps")


def plot_strategic_context(data_dir: Path, output_dir: Path) -> list[Path]:
    """Figure 5: the same strategies in deliberately unbalanced company.

    These scenarios field several countries of one strategy and none of
    another, so a bar answers "how does this strategy do against *these*
    neighbours" rather than "which strategy is best".
    """
    rows = [
        row
        for row in read_csv(data_dir / "scenario_runs.csv")
        if row["scenario"] in CONTEXT_SCENARIOS
    ]
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["scenario"], row["strategy"])].append(row)

    figure, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    width = 0.15
    metrics = (
        ("survived", "Survival rate (%)"),
        ("territory_share", "Mean final territory share (%)"),
    )
    for axis, (metric, y_label) in zip(axes, metrics):
        for strategy_index, strategy in enumerate(STRATEGY_ORDER):
            for scenario_index, scenario in enumerate(CONTEXT_SCENARIOS):
                selected = grouped.get((scenario, strategy), [])
                if not selected:
                    continue
                values = [100 * float(row[metric]) for row in selected]
                # Five bars per scenario, centred on the tick: the middle
                # strategy sits on it and the others fan out either side.
                x_position = scenario_index + (strategy_index - 2) * width
                axis.bar(
                    x_position,
                    statistics.fmean(values),
                    width=width,
                    color=STRATEGY_COLORS[strategy],
                    label=strategy.title() if scenario_index == 0 else None,
                )
                # The sample size differs per bar here -- many_aggressors has
                # four hegemonies and one peace -- so every bar carries its own.
                if metric == "survived":
                    axis.text(
                        x_position,
                        min(statistics.fmean(values) + 2, 101),
                        f"n={len(values)}",
                        ha="center",
                        va="bottom",
                        fontsize=6,
                        rotation=90,
                    )
        axis.set_xticks(
            range(len(CONTEXT_SCENARIOS)),
            [SCENARIO_LABELS[s] for s in CONTEXT_SCENARIOS],
            rotation=22,
        )
        axis.set_ylabel(y_label)
        axis.set_ylim(0, 110 if metric == "survived" else None)
        style_axes(axis)
    axes[-1].legend(handles=_strategy_handles(), frameon=False, bbox_to_anchor=(1.02, 1), loc="upper left")
    figure.text(
        0.5,
        0.01,
        "One country in one run is one observation; n varies with scenario composition.",
        ha="center",
        fontsize=8,
    )
    figure.suptitle("Performance depends on neighboring strategies", fontsize=14)
    figure.subplots_adjust(bottom=0.16)
    return save_figure(figure, output_dir, "05_strategic_context")


def plot_sample_dynamics(data_dir: Path, output_dir: Path) -> list[Path]:
    """Figure 6: a single run, turn by turn.

    The aggregate figures average all of this away, and the shape of a run --
    quiet expansion while there is free land, collisions once there is none --
    cannot be guessed from the summary numbers.
    """
    rows = [
        row
        for row in read_csv(data_dir / "sample_country_turns.csv")
        if row["scenario"] == "all_strategies"
    ]
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["country"]].append(row)

    figure, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    for country, country_rows in sorted(grouped.items()):
        country_rows.sort(key=lambda row: int(row["turn"]))
        strategy = country_rows[0]["strategy"]
        turns = [int(row["turn"]) for row in country_rows]
        # Dead countries keep producing rows until the run ends; pin them to
        # zero rather than trusting whatever was last recorded for them.
        population = [
            float(row["population"]) if int(row["alive"]) else 0.0
            for row in country_rows
        ]
        territory = [
            float(row["territory"]) if int(row["alive"]) else 0.0
            for row in country_rows
        ]
        axes[0].plot(turns, population, color=STRATEGY_COLORS[strategy], label=country)
        axes[1].plot(turns, territory, color=STRATEGY_COLORS[strategy], label=country)
    axes[0].set_title("Population")
    axes[0].set_ylabel("People")
    axes[1].set_title("Controlled territory")
    axes[1].set_ylabel("Cells")
    for axis in axes:
        axis.set_xlabel("Turn")
        axis.set_ylim(bottom=0)
        style_axes(axis)
    axes[0].legend(frameon=False, fontsize=8, loc="best")
    figure.suptitle("Representative baseline dynamics (seed 0)", fontsize=14)
    figure.tight_layout(rect=(0, 0, 1, 0.93))
    return save_figure(figure, output_dir, "06_sample_dynamics")


def plot_all(data_dir: str | Path, output_dir: str | Path) -> list[Path]:
    """Generate every report figure from persisted data, in report order."""
    data_dir, output_dir = Path(data_dir), Path(output_dir)
    written = []
    for plot in (
        plot_final_maps,
        plot_baseline_outcomes,
        plot_scenario_heatmaps,
        plot_parameter_sweeps,
        plot_strategic_context,
        plot_sample_dynamics,
    ):
        written.extend(plot(data_dir, output_dir))
    return written

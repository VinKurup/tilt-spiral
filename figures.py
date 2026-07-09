#!/usr/bin/env python3
"""
Figures for WRITEUP.md, computed straight from tilt.db.

  fig1_population.png  population deviation vs streak state, with SEs
  fig2_tiers.png       deaths deviation, tier x streak heatmap
  fig3_slopes.png      per-player streak-response slopes vs their permutation null
  fig4_requeue.png     per-player requeue-time delta (after loss - after win)

  python figures.py            # writes into figures/
"""

import random
import sqlite3
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import analyze
import ingest
import traits

OUT = Path(__file__).resolve().parent / "figures"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
BLUE = "#2a78d6"

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"],
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "text.color": INK, "axes.edgecolor": BASELINE,
    "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 1.0,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.spines.left": False, "axes.axisbelow": True,
    "xtick.labelsize": 9, "ytick.labelsize": 9, "axes.labelsize": 10,
})

METRIC_LABEL = {"deaths": "deaths", "cs_min": "CS per minute"}


def collect_slopes(conn, puuids):
    """Sign-adjusted (positive = tilt) observed and pooled-null slopes per metric."""
    rng = random.Random(traits.SEED)
    obs = {m: [] for m in traits.TILT_SIGN}
    null = {m: [] for m in traits.TILT_SIGN}
    for pu in puuids:
        devs = analyze.player_deviations(analyze.load_games(conn, pu))
        if len(devs) < traits.MIN_STREAK_GAMES:
            continue
        res = traits.player_slopes(devs, rng)
        if res is None:
            continue
        o, ns = res
        for m, sign in traits.TILT_SIGN.items():
            obs[m].append(sign * o[m])
            null[m].extend(sign * v for v in ns[m])
    return obs, null


def collect_requeue(conn, puuids):
    """Per-player median requeue delta (after loss - after win), minutes."""
    diffs = []
    for pu in puuids:
        games = analyze.load_games(conn, pu)
        if not games:
            continue
        gaps = {0: [], 1: []}
        for s in traits.sessions(games):
            for a, b in zip(s, s[1:]):
                gaps[a["win"]].append(
                    (b["start"] - (a["start"] + a["dur"] * 1000)) / 60000)
        if all(len(gaps[w]) >= traits.MIN_BEHAVIOR_N for w in (0, 1)):
            diffs.append(median(gaps[0]) - median(gaps[1]))
    return diffs


def fig_population(agg):
    from statistics import mean as _mean, stdev as _stdev
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.8))
    for ax, m, label in zip(axes, ("deaths", "cs_min"),
                            ("deaths", "CS per minute")):
        xs = range(len(analyze.BUCKETS))
        means = [_mean(agg[b][m]) for b in analyze.BUCKETS]
        ses = [_stdev(agg[b][m]) / (len(agg[b][m]) ** 0.5) for b in analyze.BUCKETS]
        ax.axhline(0, color=BASELINE, linewidth=1, zorder=1)
        ax.errorbar(xs, means, yerr=ses, fmt="o", color=BLUE, markersize=8,
                    markeredgecolor=SURFACE, markeredgewidth=2,
                    elinewidth=2, capsize=0, zorder=3)
        ax.set_xticks(list(xs), analyze.BUCKETS)
        ax.set_title(label, fontsize=11, color=SECONDARY, loc="left")
        ax.set_xlabel("streak carried into the game")
        ax.grid(visible=False, axis="x")
        ax.grid(visible=True, axis="y")
    axes[0].set_ylabel("deviation from own baseline")
    fig.suptitle("Flat everywhere: performance vs the streak entering the game "
                 "(32k games, mean ± SE)",
                 fontsize=12.5, fontweight="semibold", x=0.01, ha="left")
    fig.text(0.01, 0.885, "note the scale: a typical game has ~5.9 deaths and "
             "~6.0 CS/min — every deviation here is hundredths",
             fontsize=9.5, color=SECONDARY)
    fig.tight_layout(rect=(0, 0, 1, 0.87))
    fig.savefig(OUT / "fig1_population.png", dpi=200)


def fig_tiers(tier_deaths, tier_players, min_players=5):
    from statistics import mean as _mean
    from matplotlib.colors import LinearSegmentedColormap
    tiers = [t for t in analyze.TIER_ORDER if tier_players.get(t, 0) >= min_players]
    grid = [[_mean(tier_deaths[t][b]) if tier_deaths[t][b] else 0.0
             for b in analyze.BUCKETS] for t in tiers]
    lim = max(abs(v) for row in grid for v in row) * 1.05
    cmap = LinearSegmentedColormap.from_list("div", [BLUE, "#f0efec", "#e34948"])
    fig, ax = plt.subplots(figsize=(7.6, 0.55 * len(tiers) + 1.6))
    ax.imshow(grid, cmap=cmap, vmin=-lim, vmax=lim, aspect="auto")
    ax.set_xticks(range(len(analyze.BUCKETS)), analyze.BUCKETS)
    ax.set_yticks(range(len(tiers)), [t.title() for t in tiers])
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            ax.text(j, i, f"{v:+.2f}", ha="center", va="center", fontsize=8.5,
                    color=SURFACE if abs(v) > 0.7 * lim else INK)
    ax.grid(visible=False)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.suptitle("No tilt gradient by rank: deaths vs own baseline, by tier and streak",
                 fontsize=12.5, fontweight="semibold", x=0.01, ha="left")
    fig.text(0.01, 0.86, "red = more deaths than that player's average, "
             "blue = fewer; all values are noise-sized", fontsize=9.5,
             color=SECONDARY)
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    fig.savefig(OUT / "fig2_tiers.png", dpi=200)


def fig_slopes(obs, null):
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.8))
    for ax, m in zip(axes, traits.TILT_SIGN):
        lo = min(min(obs[m]), -max(obs[m]))
        hi = -lo
        bins = [lo + (hi - lo) * i / 40 for i in range(41)]
        ax.hist(null[m], bins=bins, density=True, color=GRID,
                label="permutation null", zorder=2)
        ax.hist(obs[m], bins=bins, density=True, histtype="step",
                color=BLUE, linewidth=2, label="observed players", zorder=3)
        ax.set_title(METRIC_LABEL[m], fontsize=11, color=SECONDARY, loc="left")
        ax.set_xlabel("streak-response slope  (positive = tilt direction)")
        ax.set_yticks([])
        ax.grid(visible=False)
    axes[0].legend(frameon=False, fontsize=9, labelcolor=SECONDARY,
                   loc="upper left")
    fig.suptitle("No hidden tilters: player slopes match shuffled data "
                 "(345 players, permutation p ≥ 0.32)",
                 fontsize=12.5, fontweight="semibold", x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(OUT / "fig3_slopes.png", dpi=200)


def fig_requeue(diffs):
    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    lim = 12
    shown = [max(-lim, min(lim, d)) for d in diffs]  # clamp tails into edge bins
    bins = [-lim + 2 * lim * i / 48 for i in range(49)]
    ax.hist(shown, bins=bins, color=BLUE, edgecolor=SURFACE, linewidth=0.8)
    ax.axvline(0, color=BASELINE, linewidth=1)
    med = median(diffs)
    ax.axvline(med, color=INK, linewidth=1)
    ax.text(med - 0.3, ax.get_ylim()[1] * 0.97, f"median {med:+.2f} min",
            ha="right", va="top", fontsize=9, color=INK)
    faster = sum(1 for d in diffs if d < 0)
    slower = sum(1 for d in diffs if d > 0)
    ax.text(-lim + 0.4, ax.get_ylim()[1] * 0.78,
            f"{faster} players requeue\nfaster after a loss",
            fontsize=9, color=SECONDARY)
    ax.text(lim - 0.4, ax.get_ylim()[1] * 0.78, f"{slower} slower",
            ha="right", fontsize=9, color=SECONDARY)
    ax.set_xlabel("requeue-time delta, minutes  (median after loss − median after win)")
    ax.set_ylabel("players")
    ax.grid(visible=False, axis="x")
    ax.grid(visible=True, axis="y")
    fig.suptitle("Loss-chasing: most players queue up again faster after a loss",
                 fontsize=12.5, fontweight="semibold", x=0.01, ha="left")
    fig.text(0.01, 0.885, f"per-player median requeue delta, n = {len(diffs)}, "
             f"sign test p < 0.001", fontsize=9.5, color=SECONDARY)
    fig.tight_layout(rect=(0, 0, 1, 0.87))
    fig.savefig(OUT / "fig4_requeue.png", dpi=200)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    conn = sqlite3.connect(ingest.DB)
    puuids = analyze._seed_puuids(conn)
    agg, _wins, tier_deaths, tier_players = analyze.run(conn)
    fig_population(agg)
    fig_tiers(tier_deaths, tier_players)
    obs, null = collect_slopes(conn, puuids)
    fig_slopes(obs, null)
    diffs = collect_requeue(conn, puuids)
    fig_requeue(diffs)
    conn.close()
    print(f"wrote {OUT / 'fig3_slopes.png'}")
    print(f"wrote {OUT / 'fig4_requeue.png'}")

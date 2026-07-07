#!/usr/bin/env python3
"""
Phase 2: the analysis. Does a player's own performance drift from their baseline
depending on whether they're on a losing OR winning streak inside a session?

Method, per player:
  1. Order their games by time, keep ranked (420) non-remake games.
  2. Split into sessions: a gap of more than SESSION_GAP minutes starts a new one.
  3. Inside a session, track a SIGNED streak entering each game: -2 means two
     straight losses just before this game, +2 means two straight wins, 0 means
     first game of the session. A win breaks a losing streak and vice versa.
  4. Baseline is per player and per role: their overall average for the metric.
     Deviations are measured against that, so a losing streak (does play get
     worse?) and a winning streak (does play get hotter?) are read on the same
     scale. Tracking both matters, otherwise post-win "hot" games leak into the
     baseline and bias the whole thing.

Then aggregate the deviations across all players by streak state.

  python analyze.py            # report from tilt.db
"""

import math
import os
import sqlite3
from collections import defaultdict
from statistics import mean, stdev

import ingest

SESSION_GAP_MS = int(os.environ.get("SESSION_GAP_MIN", "30")) * 60 * 1000
MIN_DURATION_S = 300           # drop remakes / early surrenders
MIN_ROLE_GAMES = 5             # games in a role needed for a stable baseline
MIN_GAMES = int(os.environ.get("MIN_GAMES", "20"))  # games needed to include a player
METRICS = ["deaths", "cs_min", "kda", "damage"]
BUCKETS = ["L3+", "L2", "L1", "0", "W1", "W2", "W3+"]
TIER_ORDER = ["GOLD", "PLATINUM", "EMERALD", "DIAMOND", "MASTER",
              "GRANDMASTER", "CHALLENGER"]


def load_games(conn, puuid):
    rows = conn.execute(
        "SELECT position, queue_id, win, kills, deaths, assists, cs, damage, "
        "duration_s, game_start FROM participants WHERE puuid=? ORDER BY game_start",
        (puuid,)).fetchall()
    games = []
    for pos, q, win, k, d, a, cs, dmg, dur, gs in rows:
        if q != 420 or dur < MIN_DURATION_S or not pos:
            continue
        games.append({
            "role": pos, "win": win, "deaths": d,
            "cs_min": cs / (dur / 60) if dur else 0.0,
            "kda": (k + a) / max(d, 1), "damage": dmg,
            "start": gs, "dur": dur,
        })
    return games


def tag_streaks(games):
    """Tag each game with the SIGNED streak entering it (negative = losses,
    positive = wins, 0 = first of session). Mutates and returns games."""
    prev_end, s = None, 0
    for g in games:
        if prev_end is None or (g["start"] - prev_end) > SESSION_GAP_MS:
            s = 0  # new session
        g["streak_before"] = s
        if g["win"]:
            s = s + 1 if s >= 0 else 1     # a win breaks a losing streak
        else:
            s = s - 1 if s <= 0 else -1    # a loss breaks a winning streak
        prev_end = g["start"] + g["dur"] * 1000
    return games


def player_deviations(games):
    """For one player, return (role, streak_before, {metric: deviation}, win) per
    game, measured against the player's per-role overall average. Same function
    powers the per-user lookup later."""
    tag_streaks(games)
    byrole = defaultdict(list)
    for g in games:
        byrole[g["role"]].append(g)
    baseline = {role: {m: mean(x[m] for x in gs) for m in METRICS}
                for role, gs in byrole.items() if len(gs) >= MIN_ROLE_GAMES}
    out = []
    for g in games:
        b = baseline.get(g["role"])
        if not b:
            continue
        out.append((g["role"], g["streak_before"],
                    {m: g[m] - b[m] for m in METRICS}, g["win"]))
    return out


def _bucket(s):
    if s <= -3:
        return "L3+"
    if s < 0:
        return f"L{-s}"
    if s == 0:
        return "0"
    if s >= 3:
        return "W3+"
    return f"W{s}"


def _tier_map(conn):
    try:
        return dict(conn.execute("SELECT puuid, tier FROM players").fetchall())
    except sqlite3.OperationalError:
        return {}


def run(conn):
    tier_of = _tier_map(conn)
    puuids = [r[0] for r in conn.execute(
        "SELECT puuid FROM participants WHERE queue_id=420 "
        "GROUP BY puuid HAVING COUNT(*)>=?", (MIN_GAMES,)).fetchall()]

    agg = {b: {m: [] for m in METRICS} for b in BUCKETS}
    wins = {b: [] for b in BUCKETS}
    tier_deaths = defaultdict(lambda: {b: [] for b in BUCKETS})
    tier_players = defaultdict(int)
    n_players = 0

    for pu in puuids:
        devs = player_deviations(load_games(conn, pu))
        if not devs:
            continue
        n_players += 1
        tier = tier_of.get(pu) or "(none)"
        tier_players[tier] += 1
        for _role, s, dev, win in devs:
            b = _bucket(s)
            for m in METRICS:
                agg[b][m].append(dev[m])
            wins[b].append(win)
            tier_deaths[tier][b].append(dev["deaths"])

    _print_report(agg, wins, n_players, len(puuids))
    _print_by_tier(tier_deaths, tier_players)


def _print_by_tier(tier_deaths, tier_players, min_players=5):
    ordered = [t for t in TIER_ORDER if tier_players.get(t, 0) >= min_players]
    ordered += [t for t in tier_deaths if t not in TIER_ORDER
                and tier_players.get(t, 0) >= min_players]
    if len(ordered) < 2:
        return
    print("deaths_dev by tier and streak (positive = more deaths than that")
    print("player's own average; read the L columns top-to-bottom for the trend):\n")
    print(f"{'tier':<12}{'players':>8}" + "".join(f"{b:>7}" for b in BUCKETS))
    for t in ordered:
        cells = "".join(
            (f"{mean(tier_deaths[t][b]):>+7.2f}" if tier_deaths[t][b] else f"{'-':>7}")
            for b in BUCKETS)
        print(f"{t:<12}{tier_players[t]:>8}{cells}")
    print()


def _fmt(vals):
    if not vals:
        return f"{'-':>16}"
    m = mean(vals)
    se = stdev(vals) / math.sqrt(len(vals)) if len(vals) > 1 else 0.0
    return f"{m:>+9.2f}{'(+/-' + format(se, '.2f') + ')':>7}"


def _print_report(agg, wins, n_players, n_eligible):
    print(f"\nplayers with >= {MIN_GAMES} ranked games: {n_eligible}")
    print(f"players analyzed:                    {n_players}\n")
    if n_players == 0:
        print("Not enough data yet. Gather more matches, or lower MIN_GAMES.\n")
        return
    print("deviation of a player's own stats vs their per-role average, by the")
    print("streak they carried INTO the game (L = losses behind them, W = wins):\n")
    print(f"{'streak':<8}{'games':>8}{'deaths_dev':>16}{'cs/min_dev':>16}{'winrate':>9}")
    for b in BUCKETS:
        n = len(agg[b]["deaths"])
        wr = f"{100 * mean(wins[b]):.0f}%" if wins[b] else "-"
        print(f"{b:<8}{n:>8}{_fmt(agg[b]['deaths'])}{_fmt(agg[b]['cs_min'])}{wr:>9}")
    print("\nspiral = deaths_dev climbs and cs/min_dev falls toward the L side;")
    print("'playing hot' = the mirror image on the W side.\n")


if __name__ == "__main__":
    conn = sqlite3.connect(ingest.DB)
    run(conn)
    conn.close()

#!/usr/bin/env python3
"""
Phase 2: the analysis. Does a player's own performance drift from their baseline
while they're on a losing streak inside a session?

Method, per player:
  1. Order their games by time, keep ranked (420) non-remake games.
  2. Split into sessions: a gap of more than SESSION_GAP minutes starts a new one.
  3. Inside a session, track the running loss streak. Each game is tagged with how
     many losses came right before it (streak_before: 0 = fresh or post-win).
  4. Baseline is per player and per role, built only from FRESH games
     (streak_before == 0). Comparing streak games to fresh games is the whole
     point: it isolates "playing worse while tilted" from the player's true level,
     and it doesn't get dragged down by the tilted games themselves.
  5. Each streak game's metrics are measured as a deviation from that baseline.

Then aggregate the deviations across all players by streak depth.

  python analyze.py            # report from tilt.db
"""

import math
import os
import sqlite3
import sys
from collections import defaultdict
from statistics import mean, stdev

import ingest

SESSION_GAP_MS = int(os.environ.get("SESSION_GAP_MIN", "30")) * 60 * 1000
MIN_DURATION_S = 300           # drop remakes / early surrenders
MIN_FRESH = 3                  # fresh games per (player, role) needed for a baseline
MIN_GAMES = int(os.environ.get("MIN_GAMES", "20"))  # games needed to bother with a player
METRICS = ["deaths", "cs_min", "kda", "damage"]


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
    """Split into sessions by time gap and tag each game with the loss streak
    that preceded it within its session. Mutates and returns games (time-ordered)."""
    prev_end, streak = None, 0
    for g in games:
        if prev_end is None or (g["start"] - prev_end) > SESSION_GAP_MS:
            streak = 0  # new session
        g["streak_before"] = streak
        streak = streak + 1 if not g["win"] else 0
        prev_end = g["start"] + g["dur"] * 1000
    return games


def player_deviations(games):
    """For one player, return (role, streak_before, {metric: deviation}, win) per
    game, using per-role fresh-game baselines. Games in a role without a stable
    baseline are dropped. This same function powers the per-user lookup later."""
    tag_streaks(games)
    fresh = defaultdict(list)
    for g in games:
        if g["streak_before"] == 0:
            fresh[g["role"]].append(g)
    baseline = {role: {m: mean(x[m] for x in gs) for m in METRICS}
                for role, gs in fresh.items() if len(gs) >= MIN_FRESH}
    out = []
    for g in games:
        b = baseline.get(g["role"])
        if not b:
            continue
        out.append((g["role"], g["streak_before"],
                    {m: g[m] - b[m] for m in METRICS}, g["win"]))
    return out


def _bucket(s):
    return "0" if s == 0 else "1" if s == 1 else "2" if s == 2 else "3+"


def run(conn):
    puuids = [r[0] for r in conn.execute(
        "SELECT puuid FROM participants WHERE queue_id=420 "
        "GROUP BY puuid HAVING COUNT(*)>=?", (MIN_GAMES,)).fetchall()]

    buckets = ["0", "1", "2", "3+"]
    agg = {b: {m: [] for m in METRICS} for b in buckets}
    wins = {b: [] for b in buckets}
    n_players = 0

    for pu in puuids:
        devs = player_deviations(load_games(conn, pu))
        if not devs:
            continue
        n_players += 1
        for _role, s, dev, win in devs:
            b = _bucket(s)
            for m in METRICS:
                agg[b][m].append(dev[m])
            wins[b].append(win)

    _print_report(agg, wins, n_players, len(puuids))


def _fmt(vals):
    if not vals:
        return f"{'-':>10}{'':>8}"
    m = mean(vals)
    se = stdev(vals) / math.sqrt(len(vals)) if len(vals) > 1 else 0.0
    return f"{m:>+10.2f}{'(+/-' + format(se, '.2f') + ')':>8}"


def _print_report(agg, wins, n_players, n_eligible):
    print(f"\nplayers with >= {MIN_GAMES} ranked games: {n_eligible}")
    print(f"players with a usable baseline:      {n_players}\n")
    if n_players == 0:
        print("Not enough data yet. Gather more matches, or lower MIN_GAMES.\n")
        return
    print("deviation of a player's own stats vs their fresh-game baseline, by")
    print("how many losses came right before the game (within a session):\n")
    print(f"{'streak':<8}{'games':>8}{'deaths_dev':>18}{'cs/min_dev':>18}{'winrate':>10}")
    for b in ["0", "1", "2", "3+"]:
        n = len(agg[b]["deaths"])
        wr = f"{100 * mean(wins[b]):.0f}%" if wins[b] else "-"
        note = "  (baseline)" if b == "0" else ""
        print(f"{b:<8}{n:>8}{_fmt(agg[b]['deaths'])}{_fmt(agg[b]['cs_min'])}{wr:>10}{note}")
    print("\npositive deaths_dev and negative cs/min_dev on higher streaks = the spiral.\n")


if __name__ == "__main__":
    conn = sqlite3.connect(ingest.DB)
    run(conn)
    conn.close()

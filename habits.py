#!/usr/bin/env python3
"""
Phase 5 scout: are HABIT effects alive in the cross-sectional data?

The tilt work measured a state (streaks). This asks about choices a player
repeats across games — the folk advice everyone gives and nobody has measured:
"shrink your pool", "don't first-time champs in ranked", "stop playing
autofill", "don't swap champs after a loss". Each is testable within-player,
which dodges the matchmaking-forces-50% trap the same way the requeue analysis
did: the comparison is the same player, same MMR, under two of their own
habits.

Analyses (all ranked 420, non-remake, done players only):

  A. Mastery curve: winrate by the number of PRIOR games on that champion
     within our observed window. Left-censored — a long-time main shows up as
     "0 prior" — which biases every familiarity effect TOWARD zero, so
     nonzero results here are lower bounds.
  B. First game on a champ: prior=0 vs prior>=1, paired per player.
  C. Off-role: modal position vs everything else, paired per player.
  D. Pool breadth: effective champ count (exp of Shannon entropy) vs overall
     winrate, within tier. Cross-player, so matchmaking DOES flatten this one;
     a null is expected even if breadth matters. Reported for completeness.
  E. Champ-swap after a loss: within a session, after a loss, is the next
     game better if you stay on the same champion? Paired per player.

  python habits.py             # report from tilt.db
"""

import math
import random
import sqlite3
from collections import Counter, defaultdict
from statistics import mean, median

import ingest
import analyze
from traits import sessions, sign_test

N_PERM = 2000
SEED = 7
MIN_SIDE_N = 3            # per-player games on each side of a paired contrast
PRIOR_BUCKETS = [(0, 0, "0"), (1, 2, "1-2"), (3, 5, "3-5"), (6, 10, "6-10"),
                 (11, 20, "11-20"), (21, 10 ** 9, "21+")]
LOW_PRIOR, HIGH_PRIOR = 2, 10   # paired contrast: prior<=2 vs prior>=10


def load_games(conn, puuid):
    """analyze.load_games plus the champion; same filters."""
    rows = conn.execute(
        "SELECT champion, position, queue_id, win, deaths, cs, duration_s, "
        "game_start FROM participants WHERE puuid=? ORDER BY game_start",
        (puuid,)).fetchall()
    games = []
    for champ, pos, q, win, d, cs, dur, gs in rows:
        if q != 420 or dur < analyze.MIN_DURATION_S or not pos:
            continue
        games.append({"champ": champ, "role": pos, "win": win, "deaths": d,
                      "cs_min": cs / (dur / 60) if dur else 0.0,
                      "start": gs, "dur": dur})
    return games


def tag_prior(games):
    """Prior games on this champion within the window, entering each game."""
    seen = Counter()
    for g in games:
        g["prior"] = seen[g["champ"]]
        seen[g["champ"]] += 1
    return games


def _bucket(prior):
    for lo, hi, name in PRIOR_BUCKETS:
        if lo <= prior <= hi:
            return name


def mastery_report(per_player):
    agg = {name: [] for _lo, _hi, name in PRIOR_BUCKETS}
    diffs = []                  # per player: wr(prior>=HIGH) - wr(prior<=LOW)
    for games in per_player:
        low = [g["win"] for g in games if g["prior"] <= LOW_PRIOR]
        high = [g["win"] for g in games if g["prior"] >= HIGH_PRIOR]
        for g in games:
            agg[_bucket(g["prior"])].append(g["win"])
        if len(low) >= MIN_SIDE_N and len(high) >= MIN_SIDE_N:
            diffs.append(mean(high) - mean(low))

    print("== A. mastery curve: winrate by prior games on the champion ==\n")
    print("left-censored (window starts mid-career), so every effect here is")
    print("biased toward zero; read these as lower bounds.\n")
    print(f"{'prior':<8}{'games':>8}{'winrate':>9}")
    for _lo, _hi, name in PRIOR_BUCKETS:
        if agg[name]:
            print(f"{name:<8}{len(agg[name]):>8}{100 * mean(agg[name]):>8.1f}%")
    if diffs:
        neg, pos, p = sign_test(diffs)
        print(f"\npaired per player, wr(prior>={HIGH_PRIOR}) - wr(prior<={LOW_PRIOR}), "
              f"n={len(diffs)}:")
        print(f"  mean {100 * mean(diffs):+.1f}pp  median {100 * median(diffs):+.1f}pp  "
              f"(worse on comfort: {neg}, better: {pos}, sign test p={p:.3f})")
    print()


def first_game_report(per_player):
    diffs = []                  # per player: wr(prior=0) - wr(prior>=1)
    n0 = []
    for games in per_player:
        first = [g["win"] for g in games if g["prior"] == 0]
        rest = [g["win"] for g in games if g["prior"] >= 1]
        if len(first) >= MIN_SIDE_N and len(rest) >= MIN_SIDE_N:
            diffs.append(mean(first) - mean(rest))
            n0.append(len(first))
    print("== B. first observed game on a champion vs the rest ==\n")
    if diffs:
        neg, pos, p = sign_test(diffs)
        print(f"paired per player, n={len(diffs)} "
              f"(median {median(n0):.0f} first-games each):")
        print(f"  mean {100 * mean(diffs):+.1f}pp  median {100 * median(diffs):+.1f}pp  "
              f"(worse on debuts: {neg}, better: {pos}, sign test p={p:.3f})")
    print()


def offrole_report(per_player):
    diffs = []                  # per player: wr(on modal role) - wr(off)
    share_off = []
    agg_on, agg_off = [], []
    for games in per_player:
        modal = Counter(g["role"] for g in games).most_common(1)[0][0]
        on = [g["win"] for g in games if g["role"] == modal]
        off = [g["win"] for g in games if g["role"] != modal]
        agg_on += on
        agg_off += off
        if off:
            share_off.append(len(off) / len(games))
        if len(on) >= MIN_SIDE_N and len(off) >= MIN_SIDE_N:
            diffs.append(mean(on) - mean(off))
    print("== C. modal role vs off-role ==\n")
    print(f"population: on-role {100 * mean(agg_on):.1f}% ({len(agg_on)} games), "
          f"off-role {100 * mean(agg_off):.1f}% ({len(agg_off)} games); "
          f"median off-role share {100 * median(share_off):.0f}%")
    if diffs:
        neg, pos, p = sign_test(diffs)
        print(f"paired per player, wr(on) - wr(off), n={len(diffs)}:")
        print(f"  mean {100 * mean(diffs):+.1f}pp  median {100 * median(diffs):+.1f}pp  "
              f"(better off-role: {neg}, on-role: {pos}, sign test p={p:.3f})")
    print()


def _effective_champs(games):
    counts = Counter(g["champ"] for g in games)
    total = sum(counts.values())
    h = -sum((c / total) * math.log(c / total) for c in counts.values())
    return math.exp(h)


def breadth_report(conn, per_player_pu):
    tier_of = analyze._tier_map(conn)
    by_tier = defaultdict(list)     # tier -> [(breadth, winrate)]
    for pu, games in per_player_pu:
        t = tier_of.get(pu)
        if t:
            by_tier[t].append((_effective_champs(games),
                               mean(g["win"] for g in games)))

    def corr(pairs):
        xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
        mx, my = mean(xs), mean(ys)
        sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
        sy = math.sqrt(sum((y - my) ** 2 for y in ys))
        if sx == 0 or sy == 0:
            return 0.0
        return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)

    tiers = [t for t in analyze.TIER_ORDER if len(by_tier.get(t, [])) >= 10]
    obs = mean(corr(by_tier[t]) for t in tiers)
    rng = random.Random(SEED)
    hits = 0
    for _ in range(N_PERM):
        rs = []
        for t in tiers:
            ys = [p[1] for p in by_tier[t]]
            rng.shuffle(ys)
            rs.append(corr([(p[0], y) for p, y in zip(by_tier[t], ys)]))
        if abs(mean(rs)) >= abs(obs):
            hits += 1
    print("== D. pool breadth (effective champs) vs winrate, within tier ==\n")
    print("cross-player, so matchmaking flattens real effects; null expected")
    print("even if breadth matters. The panel is the honest test for this one.\n")
    print(f"{'tier':<12}{'players':>8}{'med breadth':>12}{'r':>7}")
    for t in tiers:
        print(f"{t:<12}{len(by_tier[t]):>8}"
              f"{median(p[0] for p in by_tier[t]):>12.1f}{corr(by_tier[t]):>+7.2f}")
    print(f"\nmean r {obs:+.3f}, permutation p={(1 + hits) / (N_PERM + 1):.2f}")
    print()


def swap_report(per_player):
    diffs = []                  # per player: wr(stay after L) - wr(swap after L)
    agg_stay, agg_swap = [], []
    for games in per_player:
        stay, swap = [], []
        for s in sessions(games):
            for a, b in zip(s, s[1:]):
                if a["win"]:
                    continue
                (stay if b["champ"] == a["champ"] else swap).append(b["win"])
        agg_stay += stay
        agg_swap += swap
        if len(stay) >= MIN_SIDE_N and len(swap) >= MIN_SIDE_N:
            diffs.append(mean(stay) - mean(swap))
    print("== E. after an in-session loss: stay on the champ vs swap ==\n")
    print(f"population: stayed {100 * mean(agg_stay):.1f}% ({len(agg_stay)} games), "
          f"swapped {100 * mean(agg_swap):.1f}% ({len(agg_swap)} games)")
    if diffs:
        neg, pos, p = sign_test(diffs)
        print(f"paired per player, wr(stay) - wr(swap), n={len(diffs)}:")
        print(f"  mean {100 * mean(diffs):+.1f}pp  median {100 * median(diffs):+.1f}pp  "
              f"(better swapping: {neg}, staying: {pos}, sign test p={p:.3f})")
    print()


if __name__ == "__main__":
    conn = sqlite3.connect(ingest.DB)
    puuids = analyze._seed_puuids(conn)
    per_player_pu = []
    for pu in puuids:
        games = tag_prior(load_games(conn, pu))
        if games:
            per_player_pu.append((pu, games))
    per_player = [g for _pu, g in per_player_pu]
    print(f"\nplayers: {len(per_player)}, games: {sum(len(g) for g in per_player)}\n")
    mastery_report(per_player)
    first_game_report(per_player)
    offrole_report(per_player)
    breadth_report(conn, per_player_pu)
    swap_report(per_player)
    conn.close()

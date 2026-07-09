#!/usr/bin/env python3
"""
Phase 2b: is tilt a trait rather than a state?

analyze.py showed the POPULATION-average performance drift during streaks is
roughly zero. That's consistent with two very different worlds: (a) nobody
tilts, or (b) a minority tilts hard and the average washes it out. This script
separates them, two ways:

Performance tilt (per-player slopes):
  For each player, regress each game's deviation-from-own-baseline on the
  signed streak carried into the game. A "tilt direction" slope means playing
  worse the deeper the losing streak (more deaths / less cs as streak drops).
  Any player's slope is noisy, so each is compared against its own permutation
  null: shuffle which deviation goes with which streak, recompute the slope
  N_PERM times. If tilt is a real minority trait, more players land in the
  tail of their null than the ~5% chance predicts, and the spread of observed
  slopes exceeds the spread permutation noise produces.

Behavioral tilt (no performance stats involved, so no teammate confound):
  Within a session, how fast does a player queue again after a loss vs after
  a win, and how likely are they to stop playing? Both are paired against the
  same player's own behavior on the other outcome.

  python traits.py             # report from tilt.db
"""

import math
import random
import sqlite3
from statistics import mean, median, stdev

import ingest
import analyze

N_PERM = 200
SEED = 7
MIN_STREAK_GAMES = 10     # games with a defined baseline needed for a slope
MIN_BEHAVIOR_N = 3        # per-player samples per outcome for paired behavior
# slope sign that means "tilting" (playing worse as streak goes negative)
TILT_SIGN = {"deaths": -1, "cs_min": +1}


def slope(xs, ys):
    n = len(xs)
    mx, my = mean(xs), mean(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    if vx == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx


def player_slopes(devs, rng):
    """Observed slope per metric plus N_PERM permutation-null slopes.
    devs is analyze.player_deviations output: (role, streak, {metric: dev}, win)."""
    xs = [s for _r, s, _d, _w in devs]
    ys = {m: [d[m] for _r, _s, d, _w in devs] for m in TILT_SIGN}
    obs = {m: slope(xs, ys[m]) for m in TILT_SIGN}
    if any(v is None for v in obs.values()):
        return None
    idx = list(range(len(xs)))
    null = {m: [] for m in TILT_SIGN}
    for _ in range(N_PERM):
        rng.shuffle(idx)
        for m in TILT_SIGN:
            null[m].append(slope(xs, [ys[m][i] for i in idx]))
    return obs, null


def slope_report(conn, puuids):
    rng = random.Random(SEED)
    players = {m: [] for m in TILT_SIGN}  # (obs_slope, p_tilt, p_anti) per player
    skipped = 0
    for pu in puuids:
        devs = analyze.player_deviations(analyze.load_games(conn, pu))
        if len(devs) < MIN_STREAK_GAMES:
            skipped += 1
            continue
        res = player_slopes(devs, rng)
        if res is None:
            skipped += 1
            continue
        obs, null = res
        for m, sign in TILT_SIGN.items():
            o, ns = sign * obs[m], [sign * v for v in null[m]]
            p_tilt = (1 + sum(1 for v in ns if v >= o)) / (N_PERM + 1)
            p_anti = (1 + sum(1 for v in ns if v <= o)) / (N_PERM + 1)
            players[m].append((obs[m], p_tilt, p_anti, ns))

    print(f"\n== performance tilt: per-player slopes vs permutation null ==")
    print(f"players with a slope: {len(players['deaths'])} "
          f"(skipped {skipped}: too few games or no streak variation)\n")
    print("slope = change in deviation per +1 streak step; 'tilt' direction is")
    print("more deaths / less cs as the streak goes negative.\n")
    print(f"{'metric':<8}{'mean slope':>11}{'sd obs':>8}{'sd null':>8}"
          f"{'p(sd)':>7}{'tilt<.05':>9}{'anti<.05':>9}{'expected':>9}")
    for m in TILT_SIGN:
        rows = players[m]
        if len(rows) < 2:
            continue
        obs_sd = stdev(r[0] for r in rows)
        # null sd across players, one per permutation round
        null_sds = [stdev(rows[i][3][r] * 1.0 for i in range(len(rows)))
                    for r in range(N_PERM)]
        # rows[i][3] holds sign-adjusted nulls; sd is sign-invariant so fine
        p_sd = (1 + sum(1 for v in null_sds if v >= obs_sd)) / (N_PERM + 1)
        n_tilt = sum(1 for r in rows if r[1] < 0.05)
        n_anti = sum(1 for r in rows if r[2] < 0.05)
        print(f"{m:<8}{mean(r[0] for r in rows):>+11.3f}{obs_sd:>8.3f}"
              f"{mean(null_sds):>8.3f}{p_sd:>7.2f}"
              f"{n_tilt:>9}{n_anti:>9}{0.05 * len(rows):>9.1f}")
    print("\nsd obs > sd null (small p(sd)) = real player-to-player differences in")
    print("streak response. tilt/anti<.05 = players beating their own null in each")
    print("direction; 'expected' is the count chance alone would produce.\n")


def sessions(games):
    """Split load_games output into sessions by the same gap rule."""
    out, cur, prev_end = [], [], None
    for g in games:
        if prev_end is not None and (g["start"] - prev_end) > analyze.SESSION_GAP_MS:
            out.append(cur)
            cur = []
        cur.append(g)
        prev_end = g["start"] + g["dur"] * 1000
    if cur:
        out.append(cur)
    return out


def sign_test(diffs):
    """Two-sided sign test (normal approx). Returns (n_neg, n_pos, p)."""
    pos = sum(1 for d in diffs if d > 0)
    neg = sum(1 for d in diffs if d < 0)
    n = pos + neg
    if n == 0:
        return 0, 0, 1.0
    z = (pos - n / 2) / math.sqrt(n / 4)
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return neg, pos, p


def behavior_report(conn, puuids):
    requeue_diffs = []          # per player: median requeue after L - after W (min)
    quit_diffs = []             # per player: quit rate after L - after W
    quit_l = [0, 0]             # aggregate [ended session, total] after losses
    quit_w = [0, 0]
    for pu in puuids:
        games = analyze.load_games(conn, pu)
        if not games:
            continue
        sess = sessions(games)
        gaps = {0: [], 1: []}   # requeue minutes keyed by previous game's win
        ends = {0: [0, 0], 1: [0, 0]}
        for s in sess:
            for a, b in zip(s, s[1:]):
                gaps[a["win"]].append((b["start"] - (a["start"] + a["dur"] * 1000)) / 60000)
            last = s[-1]
            # the player's final recorded game is censored (crawl cutoff), skip it
            if not (s is sess[-1]):
                ends[last["win"]][0] += 1
            for g in (s if s is not sess[-1] else s[:-1]):
                ends[g["win"]][1] += 1
        quit_l[0] += ends[0][0]; quit_l[1] += ends[0][1]
        quit_w[0] += ends[1][0]; quit_w[1] += ends[1][1]
        if len(gaps[0]) >= MIN_BEHAVIOR_N and len(gaps[1]) >= MIN_BEHAVIOR_N:
            requeue_diffs.append(median(gaps[0]) - median(gaps[1]))
        if ends[0][1] >= MIN_BEHAVIOR_N and ends[1][1] >= MIN_BEHAVIOR_N:
            quit_diffs.append(ends[0][0] / ends[0][1] - ends[1][0] / ends[1][1])

    print("== behavioral tilt: same player, after a loss vs after a win ==\n")
    if requeue_diffs:
        neg, pos, p = sign_test(requeue_diffs)
        print(f"requeue time, per-player median diff (loss - win), n={len(requeue_diffs)}:")
        print(f"  median {median(requeue_diffs):+.2f} min  "
              f"(faster after loss: {neg}, slower: {pos}, sign test p={p:.3f})")
    if quit_l[1] and quit_w[1]:
        print(f"\nP(session ends on this game):")
        print(f"  after a loss: {quit_l[0] / quit_l[1]:.1%}  ({quit_l[0]}/{quit_l[1]})")
        print(f"  after a win:  {quit_w[0] / quit_w[1]:.1%}  ({quit_w[0]}/{quit_w[1]})")
    if quit_diffs:
        neg, pos, p = sign_test(quit_diffs)
        print(f"  per-player diff (loss - win), n={len(quit_diffs)}: "
              f"median {median(quit_diffs):+.3f}")
        print(f"  (quit more after wins: {neg}, after losses: {pos}, sign test p={p:.3f})")
    print()


if __name__ == "__main__":
    conn = sqlite3.connect(ingest.DB)
    puuids = analyze._seed_puuids(conn)
    slope_report(conn, puuids)
    behavior_report(conn, puuids)
    conn.close()

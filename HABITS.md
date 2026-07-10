# Comfort is worth four points of winrate

*Measuring the cost of champion and role habits across 706 ranked League of
Legends players — the folk advice, with numbers attached.*

> **Status: preliminary.** All numbers regenerate from the database
> (`habits.py`). Current dataset: **60,268 ranked matches, 714 fully-crawled
> players (119 per tier, Gold through Challenger), 706 analyzed** — doubled
> from the original 345-player study snapshot ([WRITEUP.md](WRITEUP.md)) by
> an expansion crawl completed 2026-07-10. A longitudinal panel (weekly rank
> snapshots + match top-ups) went live the same day. This document updates as
> the data does.

## TL;DR

- **Champion familiarity is real and monotone.** Winrate climbs from 50.3% on
  a champion's first observed game to ~55% past 10 games. Paired within
  player, comfort picks (10+ prior games) beat unfamiliar picks (≤2 prior) by
  **+4.0pp** (386 players better vs 237 worse, sign test p < 0.001). The
  crawl window censors long histories, so this is a **lower bound**.
- **First-timing a champion in ranked costs −5.0pp** (431 of 694 players do
  worse on debuts, p < 0.001) — the effect *grew* when the sample doubled.
  The median player debuts **18 different champions** per ~100 ranked games.
- **Off-role play costs −4.1pp** (on-role 53.9% vs off-role 51.1%; paired
  within player, 404 of 658 players do better on-role, p < 0.001) — and the
  median player spends **24% of their games off-role**. By volume, this is
  the biggest leak in the dataset.
- **Myth-bust: swapping champions after a loss doesn't matter.** Staying on
  the same champion for the next game within a session wins 52.9% vs 51.6%
  after a swap; paired per player the difference is noise (p = 0.29). Swap
  freely.
- **Champion-pool breadth vs winrate across players: borderline.** At n = 345
  this was a clean null; at n = 706 a weak negative correlation appears
  (broader pool ↔ lower winrate, mean within-tier r = −0.07, permutation
  p = 0.06). Cross-player winrate is flattened by matchmaking, so even this
  hint is notable — but the longitudinal panel is the honest test.

## 1. Why winrate works here when it didn't for tilt

The tilt study had to throw winrate out: matchmaking pushes every *player*
toward 50%, so cross-player winrate comparisons mostly measure matchmaking.
Habits dodge that trap, for the same reason the requeue analysis did: the
comparison is **the same player, at the same MMR, under two of their own
habits**. Matchmaking equalizes the player, not the pick. When a Diamond
mid-laner queues up on their 40-game main versus a champion they picked up
yesterday, the enemy team is drawn from the same pool either way — the
winrate difference between those two sets of games is attributable to the
pick, not the ladder.

Every headline number below is therefore a paired, within-player contrast
with a sign test across players, in the same style as the loss-chasing
results. Population-level tables are shown for shape, not inference.

## 2. Data

Same pipeline and filters as the tilt study ([WRITEUP.md §2](WRITEUP.md)):
rank-stratified players seeded directly from the NA ranked ladders, fully
crawled (~100 recent games each), ≥ 20 ranked solo/duo games to be analyzed,
remakes dropped. The expansion crawl grew every tier to exactly 119 crawled
players — Gold, Platinum, Emerald, Diamond, Master, Challenger — for 74,106
analyzed games across 706 players. Two fields do all the new work: the
champion and the assigned position of each game, ordered by time.

One definition used throughout: a player's **prior games** on a champion
counts only games inside the crawl window. A long-time main whose history
extends past the window edge shows up as "0 prior" while actually having
hundreds of games — which drags every familiarity estimate **toward zero**.
Read the familiarity numbers as floors, not point estimates.

## 3. The mastery curve

Winrate by prior games on the champion, population-level:

| prior games | games  | winrate |
|-------------|--------|---------|
| 0           | 13,914 | 50.3%   |
| 1–2         | 12,746 | 52.5%   |
| 3–5         | 9,959  | 51.9%   |
| 6–10        | 9,198  | 54.5%   |
| 11–20       | 9,574  | 55.4%   |
| 21+         | 18,715 | 54.6%   |

The curve is monotone up to ~10 games and flat after — consistent with a
learning effect that saturates. Paired within player (n = 626 with enough
games on both sides): comfort picks beat unfamiliar picks by **+4.0pp mean,
+4.3pp median**, 386 better vs 237 worse, p < 0.001.

An honest confound: this partially conflates "practice improves you" with
"players persist on champions that happen to be working." A player who wins
their first few games on a champion keeps playing it; one who loses drops it,
so high-prior games are enriched for champions that were already going well.
The within-player pairing does not remove this. Separating practice from
persistence needs the longitudinal panel (§6) — but for the practical
question ("do your unfamiliar-champ games cost you LP?") the paired number is
the right answer either way.

## 4. Debuts and off-role: the two taxes

**Debuts.** A debut — a champion's first game inside the window — runs
−5.0pp against the same player's other games (n = 694 players, 431 worse vs
257 better, p < 0.001). The striking part is the volume: the median player
debuts 18 champions per ~100 games. The folk rule "don't first-time champs in
ranked" is correct, and it's being violated constantly.

**Off-role.** Games off a player's most-common position run 51.1% vs 53.9%
on-role; paired within player, +4.1pp mean / +4.0pp median (n = 658, 404
better on-role, p < 0.001). The median player is off-role for **24% of their
games**. At a typical ~25 LP per game, a 4pp winrate gap on a quarter of your
games works out to roughly a division lost per 100 games played.

A limitation worth naming: the data can't distinguish autofill from choice.
Some off-role games are the queue's fault, not the player's. The off-role
share is therefore an upper bound on the *voluntary* leak — but the winrate
cost per off-role game is real regardless of who chose it.

## 5. One null, one opening

**Swapping champions after a loss.** Within a session, after a loss, the next
game wins 52.9% if the player stays on the same champion and 51.6% if they
swap (paired n = 512, p = 0.29). The advice "stick with your champ, you're
just tilted" has no support here — consistent with the tilt study's core
finding that post-loss games are played at baseline.

**Pool breadth across players.** At the original sample size this was a clean
null, which is what the method predicts: matchmaking absorbs persistent skill
differences into rank, leaving cross-player winrate ~flat. At n = 706 a weak
signal pokes through anyway — broader effective pools correlate with lower
winrate within tier (mean r = −0.07, permutation p = 0.06). Descriptively,
Diamond and Master run the narrowest pools (~6.8–7.0 effective champions vs
~8–10 below Diamond), though Challenger bucks the trend at 8.9 — likely a mix
of one-tricks and wide-pool professionals. Whether narrowing your pool
*causes* climbing is exactly the question the panel exists to answer.

## 6. What the panel adds

Everything above is one window per player. The longitudinal panel — live
since 2026-07-10 — re-visits every study player weekly, snapshotting their
current rank/LP (LEAGUE-V4) and topping up their match history. After a few
weeks this yields the two things the cross-section can't produce:

1. **Climb labels.** Which players actually gained LP over the period, at
   what starting rank.
2. **Natural experiments.** Players who *changed* a habit mid-panel — cut
   their pool, locked their role — with before/after LP trajectories and
   matched controls who didn't change.

That's the difference between "narrow pools correlate with high rank" and
"narrowing your pool precedes climbing." The panel infrastructure ships with
the observatory service (`PANEL_INTERVAL_H`).

## 7. Try it on your own account

The [observatory](observatory/) renders these as a personal leak panel: look
up a Riot ID and it shows your effective pool, debut share, off-role share —
each percentile-ranked against the study population — plus your own
comfort-vs-unfamiliar winrates. The author's account, for the record: 39
champions in 87 games (98th percentile), 45% debut rate (94th), 49% off-role
(87th), zero games in the comfort tier. The prescription writes itself;
whether following it moves LP is the next experiment, run on n = 1 in public.

## Caveats

- **Left-censoring** (window starts mid-career) biases familiarity effects
  toward zero; reported effects are lower bounds.
- **Persistence confound** in the mastery curve (§3): practice and
  keep-what-works are entangled until the panel separates them.
- **Autofill vs choice** is invisible in off-role games (§4).
- Cross-sectional, one region (NA), Gold and above, one patch era — same
  scope limits as the tilt study.

# Comfort is worth four points of winrate

*Measuring the cost of champion and role habits across 345 ranked League of
Legends players — the folk advice, with numbers attached.*

> **Status: preliminary.** All numbers regenerate from the database
> (`habits.py`) and reflect the cross-sectional dataset described in
> [WRITEUP.md](WRITEUP.md) (n = 345 players, 33,316 ranked games). The dataset
> is actively growing — the crawl is expanding beyond the original 345 and a
> longitudinal panel (weekly rank snapshots + match top-ups) started July
> 2026. This document updates as the data does.

## TL;DR

- **Champion familiarity is real and monotone.** Winrate climbs from 50.4% on
  a champion's first observed game to 54.8% past 20 games. Paired within
  player, comfort picks (10+ prior games) beat unfamiliar picks (≤2 prior) by
  **+4.3pp** (189 players better vs 114 worse, sign test p < 0.001). The
  crawl window censors long histories, so this is a **lower bound**.
- **First-timing a champion in ranked costs −4.1pp** (203 of 338 players do
  worse on debuts, p < 0.001). The median player debuts **17 different
  champions** per ~100 ranked games.
- **Off-role play costs −4.0pp** (on-role 53.8% vs off-role 50.6%; paired
  within player, 196 of 323 players do better on-role, p < 0.001) — and the
  median player spends **24% of their games off-role**. By volume, this is
  the biggest leak in the dataset.
- **Myth-bust: swapping champions after a loss doesn't matter.** Staying on
  the same champion for the next game within a session wins 52.0% vs 51.6%
  after a swap; paired per player the difference is noise (p = 0.47). Swap
  freely.
- **Champion-pool breadth vs winrate across players: null — as it must be.**
  Matchmaking flattens cross-player winrate, so this comparison can't detect
  a real effect (mean within-tier r = −0.03, permutation p = 0.55). The
  longitudinal panel is the honest test. One descriptive fact survives:
  Diamond/Master players run effective pools of ~6.3 champions vs ~10.6 in
  Gold/Platinum.

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

Same dataset and filters as the tilt study ([WRITEUP.md §2](WRITEUP.md)):
rank-stratified players from Gold through Challenger on NA, fully-crawled
seeds with ≥ 20 ranked solo/duo games, remakes dropped. Two fields do all the
new work: the champion and the assigned position of each game, ordered by
time.

One definition used throughout: a player's **prior games** on a champion
counts only games inside the crawl window (~100 games per player). A
long-time main whose history extends past the window edge shows up as "0
prior" while actually having hundreds of games — which drags every
familiarity estimate **toward zero**. Read the familiarity numbers as floors,
not point estimates.

## 3. The mastery curve

Winrate by prior games on the champion, population-level:

| prior games | games  | winrate |
|-------------|--------|---------|
| 0           | 6,603  | 50.4%   |
| 1–2         | 5,838  | 52.0%   |
| 3–5         | 4,503  | 51.8%   |
| 6–10        | 4,192  | 54.3%   |
| 11–20       | 4,371  | 54.8%   |
| 21+         | 7,809  | 54.8%   |

The curve is monotone up to ~10 games and flat after — consistent with a
learning effect that saturates. Paired within player (n = 304 with enough
games on both sides): comfort picks beat unfamiliar picks by **+4.3pp mean,
+4.3pp median**, 189 better vs 114 worse, p < 0.001.

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
−4.1pp against the same player's other games (n = 338 players, 203 worse vs
135 better, p < 0.001). The striking part is the volume: the median player
debuts 17 champions per ~100 games. The folk rule "don't first-time champs in
ranked" is correct, and it's being violated constantly.

**Off-role.** Games off a player's most-common position run 50.6% vs 53.8%
on-role; paired within player, +4.0pp mean / +3.7pp median (n = 323, 196
better on-role, p < 0.001). The median player is off-role for **24% of their
games**. At a typical ~25 LP per game, a 4pp winrate gap on a quarter of your
games works out to roughly a division lost per 100 games played.

A limitation worth naming: the data can't distinguish autofill from choice.
Some off-role games are the queue's fault, not the player's. The off-role
share is therefore an upper bound on the *voluntary* leak — but the winrate
cost per off-role game is real regardless of who chose it.

## 5. Two nulls

**Swapping champions after a loss.** Within a session, after a loss, the next
game wins 52.0% if the player stays on the same champion and 51.6% if they
swap (paired n = 237, p = 0.47). The advice "stick with your champ, you're
just tilted" has no support here — consistent with the tilt study's core
finding that post-loss games are played at baseline.

**Pool breadth across players.** Within every tier, the correlation between a
player's effective champion count and their winrate is indistinguishable from
zero (mean r = −0.03, permutation p = 0.55). This null is *expected under the
method*, not evidence that pools don't matter: matchmaking absorbs
persistent skill differences into rank, leaving cross-player winrate ~flat.
What the cross-section can say: better players run narrower pools
(Diamond/Master ~6.3 effective champions vs Gold/Platinum ~10.6). Whether
narrowing your pool *causes* climbing is exactly the question the panel
exists to answer.

## 6. What the panel adds

Everything above is one window per player. The longitudinal panel re-visits
every study player on a fixed cadence, snapshotting their current rank/LP
(LEAGUE-V4) and topping up their match history. After a few weeks this
yields the two things the cross-section can't produce:

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
champions in 87 games (98th percentile), 45% debut rate (93rd), 49% off-role,
zero games in the comfort tier. The prescription writes itself; whether
following it moves LP is the next experiment, run on n = 1 in public.

## Caveats

- **Left-censoring** (window starts mid-career) biases familiarity effects
  toward zero; reported effects are lower bounds.
- **Persistence confound** in the mastery curve (§3): practice and
  keep-what-works are entangled until the panel separates them.
- **Autofill vs choice** is invisible in off-role games (§4).
- Cross-sectional, one region (NA), Gold and above, one patch era — same
  scope limits as the tilt study.

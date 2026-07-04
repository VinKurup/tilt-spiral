# Tilt Spiral

A data project looking at whether a ranked League of Legends player's own
performance drops off during a losing session (the "tilt spiral"), built on the
official Riot API.

## The question

Players talk about a spiral: you lose a game, start playing worse, and lose more.
The problem is that win/loss is a bad way to measure it. Matchmaking pushes
everyone toward a 50% win rate, and any single game depends a lot on your four
teammates. So "you lose after losing" is partly just the ranking system doing its
job, not proof that you actually played worse.

The question this project actually tries to answer is narrower:

> Inside a play session, does a player's own performance (deaths, CS per minute,
> KDA, damage) get worse during a losing streak compared to that same player's
> normal baseline, and is there a point where it's a statistical mistake to keep
> queuing?

Comparing a player against their own baseline is the important part. It separates
tilt (actually playing worse) from matchmaking, which would drag your win rate
down regardless.

## How it works

Four stages:

1. Ingest. A rate-limited, resumable crawler starts from the ranked ladders and
   works outward through the other players in each match, pulling match history
   from the Riot API.
2. Store. Each match gets flattened into one row per participant. SQLite while
   gathering data locally, Postgres for the hosted service later.
3. Analyze. Group each player's games into sessions (games close together in
   time), find losing streaks, and compare performance during those streaks to
   the player's baseline.
4. Serve. A small web page where you enter your Riot ID and see your own profile:
   where your play tends to fall off, and where you should stop.

## Data and API use

Everything is read-only. It uses ACCOUNT-V1 (Riot ID to PUUID), MATCH-V5 (match
history and details), and LEAGUE-V4 (ladder sampling). It does not touch gameplay,
automate anything in the client, or resell data, and it stays within the published
rate limits. Non-commercial, personal project.

## Status

- [x] Phase 0: vertical slice, Riot ID to matches to SQLite (ingest.py)
- [ ] Phase 1: rate-limited resumable crawler, ladder seeding, dedup
- [ ] Phase 2: session reconstruction and baseline-relative analysis
- [ ] Phase 3: deployed lookup service (Postgres, hosted)
- [ ] Phase 4: writeup of method and findings

## Running the slice

```bash
pip install -r requirements.txt
cp .env.example .env        # add your Riot API key
python ingest.py "Name#TAG" 20
```

Prints the account's last N games and saves them locally. RIOT_REGION is the
routing cluster (americas, asia, or europe), not the platform code like na1.

## Disclaimer

Tilt Spiral isn't endorsed by Riot Games and doesn't reflect the views or opinions
of Riot Games or anyone officially involved in producing or managing Riot Games
properties. Riot Games and all associated properties are trademarks or registered
trademarks of Riot Games, Inc.

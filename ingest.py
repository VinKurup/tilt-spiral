#!/usr/bin/env python3
"""
Phase 0 vertical slice: prove the whole spine for ONE summoner.

  Riot ID -> PUUID -> recent match IDs -> match details -> SQLite.

This exists to shred the unknowns (auth, routing, the match-v5 shape, rate
limits) before Phase 1 builds a real crawler on top. Not the pipeline yet,
just the end-to-end path on your own account.

  pip install -r requirements.txt
  cp .env.example .env   # put your dev key in it
  python ingest.py "YourName#TAG" 20
"""

import os
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "tilt.db"


def _load_env():
    envf = HERE / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
KEY = os.environ.get("RIOT_API_KEY")
REGION = os.environ.get("RIOT_REGION", "americas")
BASE = f"https://{REGION}.api.riotgames.com"


def _get(path, **params):
    """GET with the crudest possible 429 handling, enough for a 20-match slice.
    The real token-bucket limiter is a Phase 1 concern."""
    import requests
    while True:
        r = requests.get(f"{BASE}{path}", headers={"X-Riot-Token": KEY},
                         params=params, timeout=10)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "5"))
            print(f"  429 - sleeping {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()


def puuid_for(riot_id):
    name, tag = riot_id.split("#", 1)
    return _get(f"/riot/account/v1/accounts/by-riot-id/{name}/{tag}")["puuid"]


def match_ids(puuid, count=20):
    return _get(f"/lol/match/v5/matches/by-puuid/{puuid}/ids", start=0, count=count)


def match(mid):
    return _get(f"/lol/match/v5/matches/{mid}")


def init_db():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS participants(
            match_id TEXT, puuid TEXT, champion TEXT, position TEXT,
            queue_id INT, win INT, kills INT, deaths INT, assists INT,
            cs INT, damage INT, duration_s INT, game_start INT,
            PRIMARY KEY(match_id, puuid))""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_participants_puuid ON participants(puuid)")


_PART_SQL = "INSERT OR REPLACE INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"


def participant_rows(m):
    """Flatten one match-v5 payload into participant row tuples."""
    info, mid = m["info"], m["metadata"]["matchId"]
    rows = []
    for p in info["participants"]:
        cs = p.get("totalMinionsKilled", 0) + p.get("neutralMinionsKilled", 0)
        rows.append((mid, p["puuid"], p.get("championName"), p.get("teamPosition") or "",
                     info.get("queueId"), 1 if p.get("win") else 0,
                     p.get("kills", 0), p.get("deaths", 0), p.get("assists", 0),
                     cs, p.get("totalDamageDealtToChampions", 0),
                     info.get("gameDuration", 0), info.get("gameStartTimestamp", 0)))
    return rows


def insert_participants(conn, rows):
    conn.executemany(_PART_SQL, rows)


def store(m):
    """Flatten and persist one match on its own connection. Idempotent (upsert)."""
    rows = participant_rows(m)
    with sqlite3.connect(DB) as c:
        insert_participants(c, rows)
    return len(rows)


def main():
    if not KEY:
        sys.exit("Set RIOT_API_KEY (copy .env.example -> .env).")
    if len(sys.argv) < 2:
        sys.exit('usage: python ingest.py "Name#TAG" [count]')
    riot_id, count = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 20

    init_db()
    puuid = puuid_for(riot_id)
    print(f"{riot_id} -> {puuid[:8]}...")
    ids = match_ids(puuid, count)
    print(f"{len(ids)} recent matches")

    total = 0
    for i, mid in enumerate(ids, 1):
        m = match(mid)
        total += store(m)
        me = next((p for p in m["info"]["participants"] if p["puuid"] == puuid), None)
        if me:
            res = "W" if me.get("win") else "L"
            print(f"  [{i}/{len(ids)}] {me.get('championName',''):12} {res}  "
                  f"{me.get('kills')}/{me.get('deaths')}/{me.get('assists')}")

    with sqlite3.connect(DB) as c:
        w, l = c.execute("SELECT COALESCE(SUM(win),0), COALESCE(SUM(1-win),0) "
                         "FROM participants WHERE puuid=?", (puuid,)).fetchone()
    print(f"\nstored {total} rows from {len(ids)} matches -> {DB.name}")
    print(f"{riot_id}: {w}W {l}L in this pull")


if __name__ == "__main__":
    main()

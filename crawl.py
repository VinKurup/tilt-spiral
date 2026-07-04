#!/usr/bin/env python3
"""
Phase 1: the crawler. Turns the one-shot slice into a real dataset gatherer.

Seeds from the ranked ladders, then snowballs outward: every match brings 9 more
players into the frontier. Rate-limited so it stays under the Riot limits, and
fully resumable, all crawl state lives in the same SQLite file, so a kill and
restart picks up exactly where it left off.

  python crawl.py            # seed if empty, then crawl toward the target
  python crawl.py status     # print progress without crawling

Config (env / .env):
  RIOT_API_KEY               required
  RIOT_PLATFORM   na1        ladder + summoner routing (platform)
  RIOT_REGION     americas   match routing (regional cluster)
  RIOT_QUEUE      420        ranked solo/duo
  RIOT_RPS        15         request/sec cap (a safety net; 429s are still honored)
  CRAWL_TARGET_MATCHES        20000
  CRAWL_MATCHES_PER_PLAYER    20
"""

import os
import sqlite3
import sys
import time

import ingest  # reuse the schema, env loading, and match flattening

KEY = os.environ.get("RIOT_API_KEY")
PLATFORM = os.environ.get("RIOT_PLATFORM", "na1")
REGION = os.environ.get("RIOT_REGION", "americas")
QUEUE = int(os.environ.get("RIOT_QUEUE", "420"))
RATE = float(os.environ.get("RIOT_RPS", "15"))
TARGET = int(os.environ.get("CRAWL_TARGET_MATCHES", "20000"))
PER_PLAYER = int(os.environ.get("CRAWL_MATCHES_PER_PLAYER", "20"))

PLATFORM_BASE = f"https://{PLATFORM}.api.riotgames.com"
REGION_BASE = f"https://{REGION}.api.riotgames.com"
_MIN_INTERVAL = 1.0 / RATE if RATE > 0 else 0.0
_last = [0.0]


# --- HTTP with rate limiting + backoff ------------------------------------

def _get(base, path, **params):
    import requests
    wait = _MIN_INTERVAL - (time.monotonic() - _last[0])
    if wait > 0:
        time.sleep(wait)
    while True:
        r = requests.get(base + path, headers={"X-Riot-Token": KEY},
                         params=params, timeout=15)
        _last[0] = time.monotonic()
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "2")))
            continue
        if r.status_code in (500, 502, 503, 504):
            time.sleep(2)
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


def match_ids(puuid):
    return _get(REGION_BASE, f"/lol/match/v5/matches/by-puuid/{puuid}/ids",
                start=0, count=PER_PLAYER, queue=QUEUE) or []


def match(mid):
    return _get(REGION_BASE, f"/lol/match/v5/matches/{mid}")


# --- crawl state ----------------------------------------------------------

def init_crawl_db(conn):
    ingest.init_db()  # participants table
    conn.execute("""CREATE TABLE IF NOT EXISTS players(
        puuid TEXT PRIMARY KEY, tier TEXT, status TEXT DEFAULT 'pending')""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_status ON players(status)")
    conn.execute("""CREATE TABLE IF NOT EXISTS seen_matches(
        match_id TEXT PRIMARY KEY, fetched INT DEFAULT 0)""")
    conn.commit()


def seed_from_ladders(conn):
    """Seed the frontier from the apex ladders. One call per tier.
    Relies on puuid being present on league entries (current API). If a chunk
    comes back without puuids, it warns rather than firing thousands of
    summoner-v4 lookups."""
    tiers = [("challengerleagues", "CHALLENGER"),
             ("grandmasterleagues", "GRANDMASTER"),
             ("masterleagues", "MASTER")]
    added, missing = 0, 0
    for endpoint, tier in tiers:
        data = _get(PLATFORM_BASE, f"/lol/league/v4/{endpoint}/by-queue/RANKED_SOLO_5x5")
        if not data:
            continue
        for e in data.get("entries", []):
            puuid = e.get("puuid")
            if not puuid:
                missing += 1
                continue
            added += conn.execute(
                "INSERT OR IGNORE INTO players(puuid, tier, status) VALUES(?,?,'pending')",
                (puuid, tier)).rowcount
        conn.commit()
        print(f"  seeded {tier}: +{added} total")
    if missing:
        print(f"  note: {missing} entries had no puuid; if this is most of them, "
              f"the league DTO shape changed and needs a summoner-v4 fallback.")
    return added


def _counts(conn):
    fetched = conn.execute("SELECT COUNT(*) FROM seen_matches WHERE fetched=1").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM players WHERE status='pending'").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM players WHERE status='done'").fetchone()[0]
    return fetched, pending, done


# --- main loop ------------------------------------------------------------

def crawl():
    if not KEY:
        sys.exit("Set RIOT_API_KEY (copy .env.example -> .env).")
    conn = sqlite3.connect(ingest.DB)
    init_crawl_db(conn)

    if conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 0:
        print("seeding from ladders...")
        seed_from_ladders(conn)

    stored, pending, _ = _counts(conn)
    print(f"resuming: {stored} matches fetched, {pending} players pending, target {TARGET}")
    t0, start_stored = time.monotonic(), stored

    try:
        while stored < TARGET:
            row = conn.execute(
                "SELECT puuid FROM players WHERE status='pending' LIMIT 1").fetchone()
            if not row:
                print("frontier empty; nothing left to crawl.")
                break
            puuid = row[0]
            for mid in match_ids(puuid):
                seen = conn.execute(
                    "SELECT fetched FROM seen_matches WHERE match_id=?", (mid,)).fetchone()
                if seen and seen[0]:
                    continue
                conn.execute("INSERT OR IGNORE INTO seen_matches(match_id) VALUES(?)", (mid,))
                m = match(mid)
                if not m:
                    continue
                ingest.insert_participants(conn, ingest.participant_rows(m))
                conn.execute("UPDATE seen_matches SET fetched=1 WHERE match_id=?", (mid,))
                for p in m["info"]["participants"]:
                    conn.execute(
                        "INSERT OR IGNORE INTO players(puuid, status) VALUES(?, 'pending')",
                        (p["puuid"],))
                stored += 1
                if stored % 50 == 0:
                    conn.commit()
                    rate = (stored - start_stored) / max(time.monotonic() - t0, 1e-9)
                    _, pend, _ = _counts(conn)
                    print(f"  {stored}/{TARGET} matches | {pend} pending | {rate:.1f}/s")
                if stored >= TARGET:
                    break
            conn.execute("UPDATE players SET status='done' WHERE puuid=?", (puuid,))
            conn.commit()
    except KeyboardInterrupt:
        print("\ninterrupted; state saved, safe to re-run.")
    finally:
        conn.commit()
        conn.close()
    print(f"stopped at {stored} matches.")


def status():
    conn = sqlite3.connect(ingest.DB)
    init_crawl_db(conn)
    fetched, pending, done = _counts(conn)
    parts = conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0]
    conn.close()
    print(f"matches fetched: {fetched}")
    print(f"participant rows: {parts}")
    print(f"players: {done} done, {pending} pending")


if __name__ == "__main__":
    (status if len(sys.argv) > 1 and sys.argv[1] == "status" else crawl)()

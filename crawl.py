#!/usr/bin/env python3
"""
Phase 1: the crawler. Gathers a rank-stratified dataset for the tilt study.

Seed-driven: it seeds a capped set of players per tier from the ranked ladders,
then pulls each seed's deep match history. It only crawls known-tier seeds, and
it picks the next player from whichever tier is currently behind, so the tiers
grow evenly instead of finishing one before starting the next. Rate-limited and
fully resumable; all state is in the SQLite file.

  python crawl.py seed       # add seeds for the configured tiers (safe to re-run)
  python crawl.py            # seed if empty, then crawl toward the target
  python crawl.py status     # progress by tier, no crawling

Config (env / .env):
  RIOT_API_KEY               required
  RIOT_PLATFORM   na1        ladder routing (platform)
  RIOT_REGION     americas   match routing (regional cluster)
  RIOT_QUEUE      420         ranked solo/duo
  RIOT_RPS        0.8         request/sec cap (0.83 = the 100-per-2-min ceiling)
  SEED_TIERS      GOLD,PLATINUM,EMERALD,DIAMOND,MASTER
  CRAWL_TIERS     (= SEED_TIERS)   which tiers to actually crawl
  SEED_PER_TIER   500
  CRAWL_TARGET_MATCHES        30000
  CRAWL_MATCHES_PER_PLAYER    100
"""

import os
import sqlite3
import sys
import time

import ingest

KEY = os.environ.get("RIOT_API_KEY")
PLATFORM = os.environ.get("RIOT_PLATFORM", "na1")
REGION = os.environ.get("RIOT_REGION", "americas")
QUEUE = int(os.environ.get("RIOT_QUEUE", "420"))
RATE = float(os.environ.get("RIOT_RPS", "0.8"))
TARGET = int(os.environ.get("CRAWL_TARGET_MATCHES", "30000"))
PER_PLAYER = int(os.environ.get("CRAWL_MATCHES_PER_PLAYER", "100"))
SEED_TIERS = os.environ.get("SEED_TIERS", "GOLD,PLATINUM,EMERALD,DIAMOND,MASTER")
CRAWL_TIERS = os.environ.get("CRAWL_TIERS", SEED_TIERS)
SEED_PER_TIER = int(os.environ.get("SEED_PER_TIER", "500"))

PLATFORM_BASE = f"https://{PLATFORM}.api.riotgames.com"
REGION_BASE = f"https://{REGION}.api.riotgames.com"
DIVISIONS = ["I", "II", "III", "IV"]
APEX = {"MASTER": "masterleagues", "GRANDMASTER": "grandmasterleagues",
        "CHALLENGER": "challengerleagues"}
_MIN_INTERVAL = 1.0 / RATE if RATE > 0 else 0.0
_last = [0.0]


def _tiers(csv):
    return [t.strip().upper() for t in csv.split(",") if t.strip()]


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
    ingest.init_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS players(
        puuid TEXT PRIMARY KEY, tier TEXT, status TEXT DEFAULT 'pending')""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_status ON players(status)")
    conn.execute("""CREATE TABLE IF NOT EXISTS seen_matches(
        match_id TEXT PRIMARY KEY, fetched INT DEFAULT 0)""")
    conn.commit()


# --- seeding --------------------------------------------------------------

def _apex_puuids(tier, cap):
    data = _get(PLATFORM_BASE, f"/lol/league/v4/{APEX[tier]}/by-queue/RANKED_SOLO_5x5")
    if not data:
        return []
    return [e["puuid"] for e in data.get("entries", []) if e.get("puuid")][:cap]


def _entry_puuids(tier, cap):
    out = []
    for div in DIVISIONS:
        page = 1
        while len(out) < cap:
            data = _get(PLATFORM_BASE,
                        f"/lol/league/v4/entries/RANKED_SOLO_5x5/{tier}/{div}", page=page)
            if not data:
                break
            out.extend(e["puuid"] for e in data if e.get("puuid"))
            page += 1
        if len(out) >= cap:
            break
    return out[:cap]


def seed(conn=None):
    own = conn is None
    if own:
        conn = sqlite3.connect(ingest.DB)
        init_crawl_db(conn)
    for t in _tiers(SEED_TIERS):
        puuids = _apex_puuids(t, SEED_PER_TIER) if t in APEX else _entry_puuids(t, SEED_PER_TIER)
        added = 0
        for pu in puuids:
            added += conn.execute(
                "INSERT OR IGNORE INTO players(puuid, tier, status) VALUES(?,?,'pending')",
                (pu, t)).rowcount
        conn.commit()
        print(f"  seeded {t}: +{added} new (of {len(puuids)} fetched)")
    if own:
        conn.close()


# --- balanced player selection --------------------------------------------

def _next_player(conn):
    """Pending seed from whichever crawl tier has the fewest done players, so
    tiers grow evenly. Only known-tier seeds are ever selected."""
    tiers = _tiers(CRAWL_TIERS)
    ph = ",".join("?" * len(tiers))
    pend = [r[0] for r in conn.execute(
        f"SELECT DISTINCT tier FROM players WHERE status='pending' AND tier IN ({ph})",
        tiers)]
    if not pend:
        return None
    done = dict(conn.execute(
        f"SELECT tier, COUNT(*) FROM players WHERE status='done' AND tier IN ({ph}) "
        f"GROUP BY tier", tiers).fetchall())
    target = min(pend, key=lambda t: done.get(t, 0))
    row = conn.execute(
        "SELECT puuid FROM players WHERE status='pending' AND tier=? ORDER BY rowid LIMIT 1",
        (target,)).fetchone()
    return (row[0], target) if row else None


# --- main loop ------------------------------------------------------------

def crawl():
    if not KEY:
        sys.exit("Set RIOT_API_KEY (copy .env.example -> .env).")
    conn = sqlite3.connect(ingest.DB)
    init_crawl_db(conn)
    if conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 0:
        print("seeding from ladders...")
        seed(conn)

    stored = conn.execute("SELECT COUNT(*) FROM seen_matches WHERE fetched=1").fetchone()[0]
    print(f"resuming: {stored} matches fetched, target {TARGET}, tiers {CRAWL_TIERS}")
    t0, start = time.monotonic(), stored

    try:
        while stored < TARGET:
            nxt = _next_player(conn)
            if not nxt:
                print("no pending seeds left in crawl tiers; done.")
                break
            puuid, tier = nxt
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
                stored += 1
                if stored % 50 == 0:
                    conn.commit()
                    rate = (stored - start) / max(time.monotonic() - t0, 1e-9)
                    print(f"  {stored}/{TARGET} matches | on {tier} | {rate:.2f}/s")
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
    fetched = conn.execute("SELECT COUNT(*) FROM seen_matches WHERE fetched=1").fetchone()[0]
    parts = conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0]
    print(f"matches fetched: {fetched}   participant rows: {parts}\n")
    print(f"{'tier':<14}{'done':>8}{'pending':>9}")
    rows = conn.execute(
        "SELECT COALESCE(tier,'(none)'), "
        "SUM(status='done'), SUM(status='pending') FROM players GROUP BY tier "
        "ORDER BY SUM(status='done') DESC").fetchall()
    for tier, done, pend in rows:
        print(f"{tier:<14}{done or 0:>8}{pend or 0:>9}")
    conn.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "crawl"
    {"status": status, "seed": seed}.get(cmd, crawl)()

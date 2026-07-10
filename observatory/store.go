package main

// SQLite store over the SAME schema the Python pipeline uses (tilt.db), so
// analyze.py / traits.py keep working against data this service crawls.
// Storage stays behind this one type; swapping to Postgres at deploy time
// means reimplementing these methods, not touching callers.

import (
	"database/sql"
	"strings"
	"sync"
	"time"

	_ "modernc.org/sqlite"
)

const minGamesForPopulation = 20

type Store struct {
	db *sql.DB

	popMu   sync.Mutex
	popVals []float64 // cached population requeue deltas
	popAt   time.Time

	habitsMu  sync.Mutex
	habitsPop *HabitsPop // cached population habit distributions
	habitsAt  time.Time
}

// HabitsPop holds the study players' habit values for percentile ranking.
type HabitsPop struct {
	OffRoleShare []float64
	DebutShare   []float64
	Breadth      []float64
}

func OpenStore(path string) (*Store, error) {
	// _pragma busy_timeout: the Python tools may hold the file briefly.
	db, err := sql.Open("sqlite", path+"?_pragma=busy_timeout(5000)")
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1) // sqlite: one writer, keep it simple
	s := &Store{db: db}
	return s, s.init()
}

func (s *Store) init() error {
	stmts := []string{
		`CREATE TABLE IF NOT EXISTS participants(
			match_id TEXT, puuid TEXT, champion TEXT, position TEXT,
			queue_id INT, win INT, kills INT, deaths INT, assists INT,
			cs INT, damage INT, duration_s INT, game_start INT,
			PRIMARY KEY(match_id, puuid))`,
		`CREATE INDEX IF NOT EXISTS idx_participants_puuid ON participants(puuid)`,
		`CREATE TABLE IF NOT EXISTS players(
			puuid TEXT PRIMARY KEY, tier TEXT, status TEXT DEFAULT 'pending')`,
		`CREATE TABLE IF NOT EXISTS seen_matches(
			match_id TEXT PRIMARY KEY, fetched INT DEFAULT 0)`,
		`CREATE TABLE IF NOT EXISTS accounts(
			riot_id TEXT PRIMARY KEY, puuid TEXT)`,
		// The longitudinal panel: periodic rank snapshots of study players,
		// so habit changes can be tied to LP trajectories later.
		`CREATE TABLE IF NOT EXISTS rank_history(
			puuid TEXT, at INT, tier TEXT, division TEXT, lp INT,
			wins INT, losses INT,
			PRIMARY KEY(puuid, at))`,
	}
	for _, q := range stmts {
		if _, err := s.db.Exec(q); err != nil {
			return err
		}
	}
	return nil
}

func (s *Store) Close() error { return s.db.Close() }

// SaveAccount remembers riotID -> puuid so profile reads don't hit the API.
func (s *Store) SaveAccount(riotID, puuid string) error {
	_, err := s.db.Exec(
		"INSERT OR REPLACE INTO accounts VALUES (?,?)",
		strings.ToLower(riotID), puuid)
	return err
}

func (s *Store) PuuidForAccount(riotID string) (string, error) {
	var p string
	err := s.db.QueryRow("SELECT puuid FROM accounts WHERE riot_id=?",
		strings.ToLower(riotID)).Scan(&p)
	if err == sql.ErrNoRows {
		return "", nil
	}
	return p, err
}

// MarkLookupPlayer records a looked-up player WITHOUT entering them into the
// study population (analyze.py selects status='done'; lookups are
// self-selected and would bias the sample).
func (s *Store) MarkLookupPlayer(puuid string) error {
	_, err := s.db.Exec(
		"INSERT INTO players(puuid, status) VALUES(?, 'lookup') "+
			"ON CONFLICT(puuid) DO NOTHING", puuid)
	return err
}

func (s *Store) HasMatch(matchID string) (bool, error) {
	var n int
	err := s.db.QueryRow(
		"SELECT COUNT(*) FROM seen_matches WHERE match_id=? AND fetched=1",
		matchID).Scan(&n)
	return n > 0, err
}

// SaveMatch flattens one match into participant rows, idempotently.
func (s *Store) SaveMatch(m *Match) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, p := range m.Info.Participants {
		_, err := tx.Exec(
			`INSERT OR REPLACE INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`,
			m.Metadata.MatchID, p.Puuid, p.ChampionName, p.TeamPosition,
			m.Info.QueueID, boolToInt(p.Win), p.Kills, p.Deaths, p.Assists,
			p.TotalMinionsKilled+p.NeutralMinions, p.DamageToChampions,
			m.Info.GameDuration, m.Info.GameStartTimestamp)
		if err != nil {
			return err
		}
	}
	if _, err := tx.Exec(
		"INSERT OR REPLACE INTO seen_matches VALUES (?,1)",
		m.Metadata.MatchID); err != nil {
		return err
	}
	return tx.Commit()
}

// LoadGames returns a player's ranked games ordered by start time, filtered
// the same way the study filters (queue 420, >= 5 minutes, known position).
func (s *Store) LoadGames(puuid string) ([]Game, error) {
	rows, err := s.db.Query(
		`SELECT win, game_start, duration_s, champion, position FROM participants
		 WHERE puuid=? AND queue_id=420 AND duration_s>=300 AND position!=''
		 ORDER BY game_start`, puuid)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Game
	for rows.Next() {
		var w int
		var g Game
		if err := rows.Scan(&w, &g.StartMs, &g.DurS, &g.Champ, &g.Role); err != nil {
			return nil, err
		}
		g.Win = w == 1
		out = append(out, g)
	}
	return out, rows.Err()
}

// seedPuuids returns the study population: fully crawled players with enough
// ranked games, the same selection analyze.py makes.
func (s *Store) seedPuuids() ([]string, error) {
	rows, err := s.db.Query(
		`SELECT p.puuid FROM players p JOIN
		 (SELECT puuid, COUNT(*) c FROM participants WHERE queue_id=420
		  GROUP BY puuid) g ON g.puuid=p.puuid
		 WHERE p.status='done' AND g.c>=?`, minGamesForPopulation)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var puuids []string
	for rows.Next() {
		var pu string
		if err := rows.Scan(&pu); err != nil {
			return nil, err
		}
		puuids = append(puuids, pu)
	}
	return puuids, rows.Err()
}

// PopulationRequeueDeltas returns the study players' requeue deltas for
// percentile ranking, cached for 10 minutes (the scan touches every seed).
func (s *Store) PopulationRequeueDeltas() ([]float64, error) {
	s.popMu.Lock()
	defer s.popMu.Unlock()
	if s.popVals != nil && time.Since(s.popAt) < 10*time.Minute {
		return s.popVals, nil
	}
	puuids, err := s.seedPuuids()
	if err != nil {
		return nil, err
	}
	var vals []float64
	for _, pu := range puuids {
		games, err := s.LoadGames(pu)
		if err != nil {
			return nil, err
		}
		p := BuildProfile(games)
		if p.RequeueSamples > 0 {
			vals = append(vals, p.RequeueDeltaMin)
		}
	}
	s.popVals, s.popAt = vals, time.Now()
	return vals, nil
}

// PopulationHabits returns the study players' habit distributions for
// percentile ranking, cached the same way as the requeue deltas.
func (s *Store) PopulationHabits() (*HabitsPop, error) {
	s.habitsMu.Lock()
	defer s.habitsMu.Unlock()
	if s.habitsPop != nil && time.Since(s.habitsAt) < 10*time.Minute {
		return s.habitsPop, nil
	}
	puuids, err := s.seedPuuids()
	if err != nil {
		return nil, err
	}
	pop := &HabitsPop{}
	for _, pu := range puuids {
		games, err := s.LoadGames(pu)
		if err != nil {
			return nil, err
		}
		if len(games) == 0 {
			continue
		}
		h := BuildHabits(games)
		pop.OffRoleShare = append(pop.OffRoleShare, h.OffRoleShare)
		pop.DebutShare = append(pop.DebutShare, h.DebutShare)
		pop.Breadth = append(pop.Breadth, h.EffectiveChamps)
	}
	s.habitsPop, s.habitsAt = pop, time.Now()
	return pop, nil
}

// DonePuuids returns every fully crawled study player: the panel population.
func (s *Store) DonePuuids() ([]string, error) {
	rows, err := s.db.Query("SELECT puuid FROM players WHERE status='done'")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var pu string
		if err := rows.Scan(&pu); err != nil {
			return nil, err
		}
		out = append(out, pu)
	}
	return out, rows.Err()
}

func (s *Store) SaveRankSnapshot(puuid string, at int64, e *LeagueEntry) error {
	if e == nil { // unranked this split: record the observation as empty tier
		_, err := s.db.Exec(
			"INSERT OR IGNORE INTO rank_history VALUES (?,?,'','',0,0,0)", puuid, at)
		return err
	}
	_, err := s.db.Exec(
		"INSERT OR IGNORE INTO rank_history VALUES (?,?,?,?,?,?,?)",
		puuid, at, e.Tier, e.Rank, e.LP, e.Wins, e.Losses)
	return err
}

// LatestSnapshotAt returns the most recent panel snapshot time (unix ms),
// or 0 if the panel has never run.
func (s *Store) LatestSnapshotAt() (int64, error) {
	var at sql.NullInt64
	err := s.db.QueryRow("SELECT MAX(at) FROM rank_history").Scan(&at)
	return at.Int64, err
}

func (s *Store) Counts() (matches, players int, err error) {
	if err = s.db.QueryRow("SELECT COUNT(*) FROM seen_matches WHERE fetched=1").
		Scan(&matches); err != nil {
		return
	}
	err = s.db.QueryRow("SELECT COUNT(*) FROM players").Scan(&players)
	return
}

func boolToInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

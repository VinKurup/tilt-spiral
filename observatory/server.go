package main

// The service: gotaskqueue does the job management (retries, backoff, DLQ,
// status); the crawl handler is written to be idempotent so a retried or
// redelivered task just skips the matches it already stored.

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/VinKurup/gotaskqueue"
)

//go:embed index.html
var indexHTML []byte

const (
	taskCrawlPlayer = "crawl-player"
	taskPanelPlayer = "panel-player"

	panelMatchCount = 100 // recent ids to list per sweep; existing ones skip
)

type crawlArgs struct {
	RiotID string `json:"riotId"`
	Count  int    `json:"count"` // recent matches to pull, <= 100
}

type panelArgs struct {
	Puuid string `json:"puuid"`
	At    int64  `json:"at"` // sweep timestamp (unix ms), shared by the batch
}

type progress struct {
	Done, Total int
	Stage       string
}

type Server struct {
	store *Store
	riot  *RiotClient
	queue gotaskqueue.Queue

	mu   sync.Mutex
	prog map[string]*progress // task id -> crawl progress (in-process, v1)
}

func NewServer(store *Store, riot *RiotClient, q gotaskqueue.Queue) *Server {
	s := &Server{store: store, riot: riot, queue: q, prog: map[string]*progress{}}
	q.Register(taskCrawlPlayer, s.handleCrawl)
	q.Register(taskPanelPlayer, s.handlePanel)
	return s
}

func (s *Server) setProgress(id, stage string, done, total int) {
	s.mu.Lock()
	s.prog[id] = &progress{Done: done, Total: total, Stage: stage}
	s.mu.Unlock()
}

// handleCrawl is the queue handler: resolve, list, fetch-if-new, store.
func (s *Server) handleCrawl(ctx context.Context, t gotaskqueue.Task) error {
	var args crawlArgs
	if err := json.Unmarshal(t.Data, &args); err != nil {
		return fmt.Errorf("bad task data: %w", err) // will dead-letter, correctly
	}
	name, tag, ok := splitRiotID(args.RiotID)
	if !ok {
		return fmt.Errorf("bad riot id %q", args.RiotID)
	}
	s.setProgress(t.ID, "resolving", 0, 0)
	puuid, err := s.riot.PuuidByRiotID(ctx, name, tag)
	if err != nil {
		return err
	}
	if err := s.store.SaveAccount(args.RiotID, puuid); err != nil {
		return err
	}
	if err := s.store.MarkLookupPlayer(puuid); err != nil {
		return err
	}
	if err := s.fetchNewMatches(ctx, t.ID, puuid, args.Count); err != nil {
		return err
	}
	return nil
}

// fetchNewMatches lists a player's recent matches and stores the ones we
// don't have yet. Idempotent: retries and panel re-sweeps skip stored games.
func (s *Server) fetchNewMatches(ctx context.Context, taskID, puuid string, count int) error {
	ids, err := s.riot.MatchIDs(ctx, puuid, count)
	if err != nil {
		return err
	}
	for i, id := range ids {
		if err := ctx.Err(); err != nil { // cooperative cancellation
			return err
		}
		s.setProgress(taskID, "fetching", i, len(ids))
		have, err := s.store.HasMatch(id)
		if err != nil {
			return err
		}
		if have {
			continue
		}
		m, err := s.riot.Match(ctx, id)
		if err != nil {
			return err
		}
		if err := s.store.SaveMatch(m); err != nil {
			return err
		}
	}
	s.setProgress(taskID, "done", len(ids), len(ids))
	return nil
}

// --- panel ------------------------------------------------------------------

// handlePanel is one panel-sweep unit: snapshot the player's current rank,
// then top up their match history since the last sweep.
func (s *Server) handlePanel(ctx context.Context, t gotaskqueue.Task) error {
	var args panelArgs
	if err := json.Unmarshal(t.Data, &args); err != nil {
		return fmt.Errorf("bad task data: %w", err)
	}
	entry, err := s.riot.SoloQueueEntry(ctx, args.Puuid)
	if err != nil {
		return err
	}
	if err := s.store.SaveRankSnapshot(args.Puuid, args.At, entry); err != nil {
		return err
	}
	return s.fetchNewMatches(ctx, t.ID, args.Puuid, panelMatchCount)
}

// StartPanel turns the one-time study crawl into a longitudinal panel: when
// the newest rank snapshot is older than interval, every done player gets a
// panel-player task (rank snapshot + match top-up). Enqueueing one task per
// player lets gotaskqueue's retry/backoff/DLQ apply per player.
func (s *Server) StartPanel(interval time.Duration) {
	poll := interval
	if poll > time.Hour {
		poll = time.Hour
	}
	go func() {
		for {
			last, err := s.store.LatestSnapshotAt()
			if err != nil {
				log.Printf("panel: latest snapshot: %v", err)
			} else if time.Since(time.UnixMilli(last)) >= interval {
				s.enqueuePanelSweep()
			}
			time.Sleep(poll)
		}
	}()
}

func (s *Server) enqueuePanelSweep() {
	puuids, err := s.store.DonePuuids()
	if err != nil {
		log.Printf("panel: list players: %v", err)
		return
	}
	at := time.Now().UnixMilli()
	n := 0
	for _, pu := range puuids {
		data, _ := json.Marshal(panelArgs{Puuid: pu, At: at})
		if _, err := s.queue.Enqueue(taskPanelPlayer, data); err != nil {
			log.Printf("panel: enqueue %s: %v", pu, err)
			continue
		}
		n++
	}
	log.Printf("panel: sweep enqueued for %d players", n)
}

// --- HTTP ------------------------------------------------------------------

func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /api/lookup", s.apiLookup)
	mux.HandleFunc("GET /api/tasks/{id}", s.apiTask)
	mux.HandleFunc("GET /api/profile", s.apiProfile)
	mux.HandleFunc("GET /api/stats", s.apiStats)
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	mux.HandleFunc("GET /{$}", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Write(indexHTML)
	})
	return mux
}

func (s *Server) apiLookup(w http.ResponseWriter, r *http.Request) {
	var req struct {
		RiotID string `json:"riotId"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		httpErr(w, http.StatusBadRequest, "invalid json body")
		return
	}
	if _, _, ok := splitRiotID(req.RiotID); !ok {
		httpErr(w, http.StatusBadRequest, `riotId must look like "Name#TAG"`)
		return
	}
	data, _ := json.Marshal(crawlArgs{RiotID: req.RiotID, Count: 100})
	id, err := s.queue.Enqueue(taskCrawlPlayer, data)
	if err != nil {
		httpErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusAccepted, map[string]string{"taskId": id})
}

func (s *Server) apiTask(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	t, ok, err := s.queue.GetTask(id)
	if err != nil {
		httpErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	if !ok {
		httpErr(w, http.StatusNotFound, "no such task")
		return
	}
	resp := map[string]any{
		"id": t.ID, "type": t.Type, "status": t.Status, "retries": t.Retries,
	}
	s.mu.Lock()
	if p, ok := s.prog[id]; ok {
		resp["progress"] = map[string]any{
			"stage": p.Stage, "done": p.Done, "total": p.Total,
		}
	}
	s.mu.Unlock()
	writeJSON(w, http.StatusOK, resp)
}

func (s *Server) apiProfile(w http.ResponseWriter, r *http.Request) {
	riotID := r.URL.Query().Get("riotId")
	if _, _, ok := splitRiotID(riotID); !ok {
		httpErr(w, http.StatusBadRequest, `pass ?riotId=Name%23TAG`)
		return
	}
	puuid, err := s.store.PuuidForAccount(riotID)
	if err != nil {
		httpErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	if puuid == "" {
		httpErr(w, http.StatusNotFound, "unknown account: POST /api/lookup first")
		return
	}
	games, err := s.store.LoadGames(puuid)
	if err != nil {
		httpErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	prof := BuildProfile(games)
	resp := map[string]any{"riotId": riotID, "profile": prof}
	if prof.RequeueSamples > 0 {
		pop, err := s.store.PopulationRequeueDeltas()
		if err == nil && len(pop) > 0 {
			resp["chasePercentile"] = chasePercentile(prof.RequeueDeltaMin, pop)
			resp["populationN"] = len(pop)
		}
	}
	if len(games) > 0 {
		habits := BuildHabits(games)
		resp["habits"] = habits
		pop, err := s.store.PopulationHabits()
		if err == nil && len(pop.Breadth) > 0 {
			resp["habitPercentiles"] = map[string]any{
				"offRoleShare":    percentileBelow(pop.OffRoleShare, habits.OffRoleShare),
				"debutShare":      percentileBelow(pop.DebutShare, habits.DebutShare),
				"effectiveChamps": percentileBelow(pop.Breadth, habits.EffectiveChamps),
				"populationN":     len(pop.Breadth),
			}
		}
	}
	writeJSON(w, http.StatusOK, resp)
}

func (s *Server) apiStats(w http.ResponseWriter, r *http.Request) {
	qs, err := s.queue.Stats()
	if err != nil {
		httpErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	matches, players, err := s.store.Counts()
	if err != nil {
		httpErr(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"queue": qs,
		"db":    map[string]int{"matches": matches, "players": players},
	})
}

func splitRiotID(s string) (name, tag string, ok bool) {
	name, tag, found := strings.Cut(s, "#")
	if !found || name == "" || tag == "" {
		return "", "", false
	}
	return name, tag, true
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func httpErr(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}

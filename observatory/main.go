package main

// Observatory: Phase 3 of tilt-spiral. Crawl-on-demand behind gotaskqueue,
// serving behavioral profiles over the study's database.
//
// Config (env):
//   RIOT_API_KEY     required
//   RIOT_REGION      americas (regional cluster, not platform)
//   RIOT_PLATFORM    na1 (platform host, league-v4 rank lookups)
//   TILT_DB          ../tilt.db
//   ADDR             :8080
//   WORKERS          2 (per queue: lookups and panel sweeps run separately)
//   QUEUE            memory | redis
//   REDIS_ADDR       localhost:6379 (QUEUE=redis only)
//   PANEL_INTERVAL_H 0 = off; e.g. 168 sweeps the longitudinal panel weekly
//                    (rank snapshot + match top-up for every done player)

import (
	"log"
	"net/http"
	"os"
	"os/signal"
	"time"

	"github.com/VinKurup/gotaskqueue"
	"github.com/redis/go-redis/v9"
)

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func main() {
	key := os.Getenv("RIOT_API_KEY")
	if key == "" {
		log.Fatal("RIOT_API_KEY is required")
	}

	store, err := OpenStore(env("TILT_DB", "../tilt.db"))
	if err != nil {
		log.Fatalf("open store: %v", err)
	}
	defer store.Close()

	var lookupQ, panelQ gotaskqueue.Queue
	if env("QUEUE", "memory") == "redis" {
		client := redis.NewClient(&redis.Options{Addr: env("REDIS_ADDR", "localhost:6379")})
		lookupQ = gotaskqueue.NewRedisQueue(client, "observatory")
		panelQ = gotaskqueue.NewRedisQueue(client, "observatory-panel")
	} else {
		lookupQ = gotaskqueue.NewMemoryQueue("observatory")
		panelQ = gotaskqueue.NewMemoryQueue("observatory-panel")
	}

	riot := NewRiotClient(key, env("RIOT_REGION", "americas"), env("RIOT_PLATFORM", "na1"))
	srv := NewServer(store, riot, lookupQ, panelQ)

	if h := os.Getenv("PANEL_INTERVAL_H"); h != "" {
		if n, err := parsePositive(h); err == nil {
			srv.StartPanel(time.Duration(n) * time.Hour)
			log.Printf("panel: sweeping every %dh", n)
		}
	}

	workers := 2
	if w := os.Getenv("WORKERS"); w != "" {
		if n, err := parsePositive(w); err == nil {
			workers = n
		}
	}
	lookupQ.Start(workers)
	defer lookupQ.Stop()
	panelQ.Start(workers)
	defer panelQ.Stop()

	httpSrv := &http.Server{Addr: env("ADDR", ":8080"), Handler: srv.Routes()}
	go func() {
		log.Printf("observatory listening on %s", httpSrv.Addr)
		if err := httpSrv.ListenAndServe(); err != http.ErrServerClosed {
			log.Fatalf("http: %v", err)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt)
	<-stop
	log.Print("shutting down")
	httpSrv.Close()
}

func parsePositive(s string) (int, error) {
	n := 0
	for _, c := range s {
		if c < '0' || c > '9' {
			return 0, os.ErrInvalid
		}
		n = n*10 + int(c-'0')
	}
	if n == 0 {
		return 0, os.ErrInvalid
	}
	return n, nil
}

package main

// Rate-limited Riot API client. gotaskqueue deliberately doesn't rate-limit,
// so the token discipline lives here: a dual sliding window matching the dev
// key limits (20 req / 1 s AND 100 req / 120 s), shared by every worker, plus
// 429 Retry-After handling as the backstop for anything the windows miss.

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"sync"
	"time"
)

type window struct {
	span  time.Duration
	limit int
	hits  []time.Time
}

func (w *window) prune(now time.Time) {
	i := 0
	for i < len(w.hits) && now.Sub(w.hits[i]) >= w.span {
		i++
	}
	w.hits = w.hits[i:]
}

type rateLimiter struct {
	mu      sync.Mutex
	windows []*window
}

func newDevKeyLimiter() *rateLimiter {
	return &rateLimiter{windows: []*window{
		{span: time.Second, limit: 20},
		{span: 2 * time.Minute, limit: 100},
	}}
}

// wait blocks until every window has room, then records the hit.
func (r *rateLimiter) wait(ctx context.Context) error {
	for {
		r.mu.Lock()
		now := time.Now()
		var until time.Time
		ok := true
		for _, w := range r.windows {
			w.prune(now)
			if len(w.hits) >= w.limit {
				ok = false
				if free := w.hits[0].Add(w.span); free.After(until) {
					until = free
				}
			}
		}
		if ok {
			for _, w := range r.windows {
				w.hits = append(w.hits, now)
			}
			r.mu.Unlock()
			return nil
		}
		r.mu.Unlock()
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(time.Until(until) + 10*time.Millisecond):
		}
	}
}

type RiotClient struct {
	key    string
	base   string // regional cluster, e.g. https://americas.api.riotgames.com
	http   *http.Client
	lim    *rateLimiter
	maxTry int
}

func NewRiotClient(key, region string) *RiotClient {
	return &RiotClient{
		key:    key,
		base:   fmt.Sprintf("https://%s.api.riotgames.com", region),
		http:   &http.Client{Timeout: 15 * time.Second},
		lim:    newDevKeyLimiter(),
		maxTry: 4,
	}
}

func (c *RiotClient) get(ctx context.Context, path string, out any) error {
	for attempt := 0; ; attempt++ {
		if err := c.lim.wait(ctx); err != nil {
			return err
		}
		req, err := http.NewRequestWithContext(ctx, "GET", c.base+path, nil)
		if err != nil {
			return err
		}
		req.Header.Set("X-Riot-Token", c.key)
		resp, err := c.http.Do(req)
		if err != nil {
			if attempt+1 < c.maxTry {
				continue
			}
			return err
		}
		switch {
		case resp.StatusCode == http.StatusOK:
			err := json.NewDecoder(resp.Body).Decode(out)
			resp.Body.Close()
			return err
		case resp.StatusCode == http.StatusTooManyRequests:
			resp.Body.Close()
			wait := 5 * time.Second
			if s := resp.Header.Get("Retry-After"); s != "" {
				if n, err := strconv.Atoi(s); err == nil {
					wait = time.Duration(n) * time.Second
				}
			}
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(wait):
			}
			continue // 429 retries don't count against maxTry
		case resp.StatusCode >= 500 && attempt+1 < c.maxTry:
			resp.Body.Close()
			continue
		default:
			resp.Body.Close()
			return fmt.Errorf("riot api %s: status %d", path, resp.StatusCode)
		}
	}
}

func (c *RiotClient) PuuidByRiotID(ctx context.Context, name, tag string) (string, error) {
	var v struct {
		Puuid string `json:"puuid"`
	}
	p := fmt.Sprintf("/riot/account/v1/accounts/by-riot-id/%s/%s",
		url.PathEscape(name), url.PathEscape(tag))
	if err := c.get(ctx, p, &v); err != nil {
		return "", err
	}
	return v.Puuid, nil
}

func (c *RiotClient) MatchIDs(ctx context.Context, puuid string, count int) ([]string, error) {
	var ids []string
	p := fmt.Sprintf("/lol/match/v5/matches/by-puuid/%s/ids?start=0&count=%d", puuid, count)
	return ids, c.get(ctx, p, &ids)
}

// Match is the slice of match-v5 the store needs.
type Match struct {
	Metadata struct {
		MatchID string `json:"matchId"`
	} `json:"metadata"`
	Info struct {
		QueueID            int   `json:"queueId"`
		GameDuration       int64 `json:"gameDuration"`
		GameStartTimestamp int64 `json:"gameStartTimestamp"`
		Participants       []struct {
			Puuid              string `json:"puuid"`
			ChampionName       string `json:"championName"`
			TeamPosition       string `json:"teamPosition"`
			Win                bool   `json:"win"`
			Kills              int    `json:"kills"`
			Deaths             int    `json:"deaths"`
			Assists            int    `json:"assists"`
			TotalMinionsKilled int    `json:"totalMinionsKilled"`
			NeutralMinions     int    `json:"neutralMinionsKilled"`
			DamageToChampions  int    `json:"totalDamageDealtToChampions"`
		} `json:"participants"`
	} `json:"info"`
}

func (c *RiotClient) Match(ctx context.Context, id string) (*Match, error) {
	var m Match
	return &m, c.get(ctx, "/lol/match/v5/matches/"+id, &m)
}

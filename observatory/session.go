package main

// Session reconstruction and the behavioral profile, ported from analyze.py /
// traits.py. Pure functions over a player's ordered game list so they're
// trivially testable. Performance-tilt metrics are deliberately absent: the
// study found them null. The profile is behavior + the myth-check winrate.

import "sort"

const sessionGapMs = 30 * 60 * 1000

// Game is one ranked game from the participants table, ordered by StartMs.
type Game struct {
	Win     bool
	StartMs int64
	DurS    int64
	Champ   string
	Role    string
}

func (g Game) endMs() int64 { return g.StartMs + g.DurS*1000 }

// splitSessions groups games separated by <= sessionGapMs into sessions.
func splitSessions(games []Game) [][]Game {
	var out [][]Game
	var cur []Game
	for i, g := range games {
		if i > 0 && g.StartMs-games[i-1].endMs() > sessionGapMs {
			out = append(out, cur)
			cur = nil
		}
		cur = append(cur, g)
	}
	if len(cur) > 0 {
		out = append(out, cur)
	}
	return out
}

type Profile struct {
	RankedGames int `json:"rankedGames"`
	Sessions    int `json:"sessions"`

	// Requeue: median minutes from game end to next game start, within a
	// session, keyed by the previous game's result. Delta < 0 = loss-chasing.
	RequeueAfterLossMin float64 `json:"requeueAfterLossMin"`
	RequeueAfterWinMin  float64 `json:"requeueAfterWinMin"`
	RequeueDeltaMin     float64 `json:"requeueDeltaMin"`
	RequeueSamples      int     `json:"requeueSamples"`

	// Quit: probability a game ends the session, by its result. The player's
	// final recorded game is censored (the crawl cut it off, not the player).
	QuitAfterLoss float64 `json:"quitAfterLoss"`
	QuitAfterWin  float64 `json:"quitAfterWin"`

	// Myth check: your next game is a coin flip at your usual rate.
	Winrate            float64 `json:"winrate"`
	WinrateAfterL2Plus float64 `json:"winrateAfterL2Plus"`
	GamesAfterL2Plus   int     `json:"gamesAfterL2Plus"`
}

// BuildProfile computes the behavioral profile. Games must be sorted by
// StartMs ascending (LoadGames guarantees it).
func BuildProfile(games []Game) Profile {
	p := Profile{RankedGames: len(games)}
	if len(games) == 0 {
		return p
	}
	sessions := splitSessions(games)
	p.Sessions = len(sessions)

	var gapsLoss, gapsWin []float64
	quitN := map[bool]int{}   // session-ending games by result
	quitDen := map[bool]int{} // opportunities by result
	wins, winsL2, nL2 := 0, 0, 0

	for si, s := range sessions {
		final := si == len(sessions)-1
		streak := 0
		for i, g := range s {
			if g.Win {
				wins++
			}
			if streak <= -2 {
				nL2++
				if g.Win {
					winsL2++
				}
			}
			if g.Win {
				if streak >= 0 {
					streak++
				} else {
					streak = 1
				}
			} else {
				if streak <= 0 {
					streak--
				} else {
					streak = -1
				}
			}
			if i < len(s)-1 {
				gap := float64(s[i+1].StartMs-g.endMs()) / 60000
				if g.Win {
					gapsWin = append(gapsWin, gap)
				} else {
					gapsLoss = append(gapsLoss, gap)
				}
				quitDen[g.Win]++
			} else if !final { // last game of a non-final session = a quit
				quitN[g.Win]++
				quitDen[g.Win]++
			}
		}
	}

	p.Winrate = float64(wins) / float64(len(games))
	if nL2 > 0 {
		p.WinrateAfterL2Plus = float64(winsL2) / float64(nL2)
	}
	p.GamesAfterL2Plus = nL2
	if quitDen[false] > 0 {
		p.QuitAfterLoss = float64(quitN[false]) / float64(quitDen[false])
	}
	if quitDen[true] > 0 {
		p.QuitAfterWin = float64(quitN[true]) / float64(quitDen[true])
	}
	if len(gapsLoss) > 0 && len(gapsWin) > 0 {
		p.RequeueAfterLossMin = median(gapsLoss)
		p.RequeueAfterWinMin = median(gapsWin)
		p.RequeueDeltaMin = p.RequeueAfterLossMin - p.RequeueAfterWinMin
		p.RequeueSamples = len(gapsLoss) + len(gapsWin)
	}
	return p
}

func median(v []float64) float64 {
	s := append([]float64(nil), v...)
	sort.Float64s(s)
	n := len(s)
	if n%2 == 1 {
		return s[n/2]
	}
	return (s[n/2-1] + s[n/2]) / 2
}

// chasePercentile: the share of study players who loss-chase LESS than this
// delta (more negative delta = faster requeue after losses = more chasing).
// "You chase more than 83% of ladder players" reads from this directly.
func chasePercentile(delta float64, population []float64) float64 {
	if len(population) == 0 {
		return 0
	}
	n := 0
	for _, d := range population {
		if d > delta {
			n++
		}
	}
	return float64(n) / float64(len(population))
}

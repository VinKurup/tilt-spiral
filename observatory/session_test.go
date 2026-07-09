package main

import (
	"math"
	"testing"
)

// g builds a game: start in minutes from t0, 20 min long.
func g(startMin int64, win bool) Game {
	return Game{Win: win, StartMs: startMin * 60000, DurS: 20 * 60}
}

func TestSplitSessions(t *testing.T) {
	games := []Game{
		g(0, true),    // s1: ends 20
		g(25, false),  // gap 5  -> same session, ends 45
		g(80, true),   // gap 35 -> new session, ends 100
		g(130, false), // gap 30 -> SAME session (gap must EXCEED 30), ends 150
		g(181, true),  // gap 31 -> new session
	}
	s := splitSessions(games)
	if len(s) != 3 {
		t.Fatalf("want 3 sessions, got %d", len(s))
	}
	if len(s[0]) != 2 || len(s[1]) != 2 || len(s[2]) != 1 {
		t.Fatalf("wrong session sizes: %d %d %d", len(s[0]), len(s[1]), len(s[2]))
	}
}

func TestRequeueMedians(t *testing.T) {
	// One session: L (gap 2) W (gap 10) L (gap 4) end.
	games := []Game{
		g(0, false),  // ends 20, next starts 22  -> gap 2 after loss
		g(22, true),  // ends 42, next starts 52  -> gap 10 after win
		g(52, false), // ends 72, next starts 76  -> gap 4 after loss
		g(76, true),
	}
	p := BuildProfile(games)
	if want := 3.0; p.RequeueAfterLossMin != want { // median(2, 4)
		t.Errorf("loss requeue: want %v got %v", want, p.RequeueAfterLossMin)
	}
	if want := 10.0; p.RequeueAfterWinMin != want {
		t.Errorf("win requeue: want %v got %v", want, p.RequeueAfterWinMin)
	}
	if want := -7.0; p.RequeueDeltaMin != want {
		t.Errorf("delta: want %v got %v", want, p.RequeueDeltaMin)
	}
}

func TestQuitRatesCensorFinalGame(t *testing.T) {
	// Session 1: W L(quit). Session 2 (final): W W — final game censored.
	games := []Game{
		g(0, true), g(25, false),
		g(200, true), g(225, true),
	}
	p := BuildProfile(games)
	// Opportunities: s1 W (continued), s1 L (quit), s2 first W (continued).
	// Final W is censored entirely.
	if want := 1.0; p.QuitAfterLoss != want {
		t.Errorf("quit after loss: want %v got %v", want, p.QuitAfterLoss)
	}
	if want := 0.0; p.QuitAfterWin != want {
		t.Errorf("quit after win: want %v got %v", want, p.QuitAfterWin)
	}
}

func TestWinrateAfterL2Plus(t *testing.T) {
	// One session: L L W L L L W  -> games entered with streak <= -2:
	// game3 (after L,L: WIN), game6 (after L,L: LOSS), game7 (after L,L,L: WIN).
	games := []Game{
		g(0, false), g(25, false), g(50, true), g(75, false),
		g(100, false), g(125, false), g(150, true),
	}
	p := BuildProfile(games)
	if p.GamesAfterL2Plus != 3 {
		t.Fatalf("games after L2+: want 3 got %d", p.GamesAfterL2Plus)
	}
	if want := 2.0 / 3.0; math.Abs(p.WinrateAfterL2Plus-want) > 1e-9 {
		t.Errorf("winrate after L2+: want %v got %v", want, p.WinrateAfterL2Plus)
	}
}

func TestWinStreakDoesNotCountAsL2(t *testing.T) {
	// W W W W: no game entered on a losing streak.
	games := []Game{g(0, true), g(25, true), g(50, true), g(75, true)}
	if p := BuildProfile(games); p.GamesAfterL2Plus != 0 {
		t.Errorf("want 0 L2+ games, got %d", p.GamesAfterL2Plus)
	}
}

func TestChasePercentile(t *testing.T) {
	pop := []float64{-3, -1, 0, 1, 2}
	// delta -2: players chasing less (delta > -2) = {-1,0,1,2} = 4/5
	if got := chasePercentile(-2, pop); got != 0.8 {
		t.Errorf("want 0.8 got %v", got)
	}
}

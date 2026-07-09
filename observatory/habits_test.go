package main

import (
	"math"
	"testing"
)

// hg builds a game for habit tests; timing fields don't matter here.
func hg(champ, role string, win bool) Game {
	return Game{Win: win, Champ: champ, Role: role}
}

func TestModalRoleAndOffRole(t *testing.T) {
	games := []Game{
		hg("Ahri", "MIDDLE", true),
		hg("Ahri", "MIDDLE", false),
		hg("Ahri", "MIDDLE", true),
		hg("Jinx", "BOTTOM", false),
	}
	h := BuildHabits(games)
	if h.ModalRole != "MIDDLE" {
		t.Fatalf("modal role: want MIDDLE got %s", h.ModalRole)
	}
	if h.OffRoleGames != 1 || h.OffRoleShare != 0.25 {
		t.Errorf("off-role: want 1 game / 0.25 share, got %d / %v",
			h.OffRoleGames, h.OffRoleShare)
	}
	if want := 2.0 / 3.0; math.Abs(h.WinrateOnRole-want) > 1e-9 {
		t.Errorf("on-role wr: want %v got %v", want, h.WinrateOnRole)
	}
	if h.WinrateOffRole != 0 {
		t.Errorf("off-role wr: want 0 got %v", h.WinrateOffRole)
	}
}

func TestModalRoleTieBreaksFirstSeen(t *testing.T) {
	games := []Game{
		hg("Ahri", "MIDDLE", true), hg("Jinx", "BOTTOM", true),
		hg("Ahri", "MIDDLE", true), hg("Jinx", "BOTTOM", true),
	}
	if h := BuildHabits(games); h.ModalRole != "MIDDLE" {
		t.Errorf("tie should break to first-seen role, got %s", h.ModalRole)
	}
}

func TestDebutsAndFamiliarity(t *testing.T) {
	// 12 Ahri games (debut loss, rest wins), then a Jinx debut loss.
	var games []Game
	games = append(games, hg("Ahri", "MIDDLE", false))
	for i := 0; i < 11; i++ {
		games = append(games, hg("Ahri", "MIDDLE", true))
	}
	games = append(games, hg("Jinx", "MIDDLE", false))
	h := BuildHabits(games)
	if h.Debuts != 2 {
		t.Fatalf("debuts: want 2 got %d", h.Debuts)
	}
	if h.WinrateDebut != 0 {
		t.Errorf("debut wr: want 0 got %v", h.WinrateDebut)
	}
	if h.WinrateRepeat != 1 {
		t.Errorf("repeat wr: want 1 got %v", h.WinrateRepeat)
	}
	// Comfort = prior >= 10: Ahri games 11 and 12 (indexes 10, 11), both wins.
	if h.ComfortGames != 2 || h.WinrateComfort != 1 {
		t.Errorf("comfort: want 2 games wr 1, got %d wr %v",
			h.ComfortGames, h.WinrateComfort)
	}
	// Unfamiliar = prior <= 2: Ahri games 1-3 (L W W) + Jinx debut (L).
	if h.UnfamiliarGames != 4 {
		t.Fatalf("unfamiliar: want 4 got %d", h.UnfamiliarGames)
	}
	if want := 0.5; math.Abs(h.WinrateUnfamiliar-want) > 1e-9 {
		t.Errorf("unfamiliar wr: want %v got %v", want, h.WinrateUnfamiliar)
	}
}

func TestEffectiveChamps(t *testing.T) {
	// Uniform over 4 champs: entropy ln(4), effective = 4 exactly.
	games := []Game{
		hg("A", "MIDDLE", true), hg("B", "MIDDLE", true),
		hg("C", "MIDDLE", true), hg("D", "MIDDLE", true),
	}
	h := BuildHabits(games)
	if h.DistinctChamps != 4 {
		t.Fatalf("distinct: want 4 got %d", h.DistinctChamps)
	}
	if math.Abs(h.EffectiveChamps-4) > 1e-9 {
		t.Errorf("effective champs: want 4 got %v", h.EffectiveChamps)
	}
	// One-trick: effective pool is exactly 1.
	ot := BuildHabits([]Game{hg("A", "MIDDLE", true), hg("A", "MIDDLE", false)})
	if math.Abs(ot.EffectiveChamps-1) > 1e-9 {
		t.Errorf("one-trick effective champs: want 1 got %v", ot.EffectiveChamps)
	}
}

func TestPercentileBelow(t *testing.T) {
	pop := []float64{1, 2, 3, 4, 5}
	if got := percentileBelow(pop, 3.5); got != 0.6 {
		t.Errorf("want 0.6 got %v", got)
	}
	if got := percentileBelow(nil, 1); got != 0 {
		t.Errorf("empty population: want 0 got %v", got)
	}
}

func TestBuildHabitsEmpty(t *testing.T) {
	h := BuildHabits(nil)
	if h.ModalRole != "" || h.Debuts != 0 || h.EffectiveChamps != 0 {
		t.Errorf("empty input should give zero habits, got %+v", h)
	}
}

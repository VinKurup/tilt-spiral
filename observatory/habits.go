package main

// Habit metrics, ported from habits.py. Same within-player framing as the
// behavioral profile: the comparison is the same player at the same MMR under
// two of their own habits, which is what makes the winrates meaningful.
// Familiarity counts are left-censored at the crawl window edge (a long-time
// main shows up as "0 prior"), which biases these numbers toward zero — the
// study reads them as lower bounds and so should the UI.

import "math"

const (
	lowPrior  = 2  // "unfamiliar": at most this many prior games on the champ
	highPrior = 10 // "comfort": at least this many prior games on the champ
)

type Habits struct {
	ModalRole      string  `json:"modalRole"`
	OffRoleGames   int     `json:"offRoleGames"`
	OffRoleShare   float64 `json:"offRoleShare"`
	WinrateOnRole  float64 `json:"winrateOnRole"`
	WinrateOffRole float64 `json:"winrateOffRole"`

	// A debut is a champion's first game inside the crawl window.
	Debuts        int     `json:"debuts"`
	DebutShare    float64 `json:"debutShare"`
	WinrateDebut  float64 `json:"winrateDebut"`
	WinrateRepeat float64 `json:"winrateRepeat"`

	ComfortGames      int     `json:"comfortGames"`
	WinrateComfort    float64 `json:"winrateComfort"`
	UnfamiliarGames   int     `json:"unfamiliarGames"`
	WinrateUnfamiliar float64 `json:"winrateUnfamiliar"`

	DistinctChamps  int     `json:"distinctChamps"`
	EffectiveChamps float64 `json:"effectiveChamps"` // exp of Shannon entropy
}

// BuildHabits computes the habit profile. Games must be sorted by StartMs
// ascending (LoadGames guarantees it) so prior-game counts are correct.
func BuildHabits(games []Game) Habits {
	h := Habits{}
	if len(games) == 0 {
		return h
	}

	roleN := map[string]int{}
	champN := map[string]int{}
	for _, g := range games {
		roleN[g.Role]++
	}
	// Ties break toward the role seen first, matching Counter.most_common.
	for _, g := range games {
		if roleN[g.Role] > roleN[h.ModalRole] {
			h.ModalRole = g.Role
		}
	}

	var onW, onN, offW, offN int
	var debW, repW, comW, comN, unfW, unfN int
	for _, g := range games {
		prior := champN[g.Champ]
		champN[g.Champ]++
		win := 0
		if g.Win {
			win = 1
		}
		if g.Role == h.ModalRole {
			onW, onN = onW+win, onN+1
		} else {
			offW, offN = offW+win, offN+1
		}
		if prior == 0 {
			h.Debuts++
			debW += win
		} else {
			repW += win
		}
		if prior >= highPrior {
			comW, comN = comW+win, comN+1
		}
		if prior <= lowPrior {
			unfW, unfN = unfW+win, unfN+1
		}
	}

	n := len(games)
	h.OffRoleGames = offN
	h.OffRoleShare = float64(offN) / float64(n)
	h.WinrateOnRole = ratio(onW, onN)
	h.WinrateOffRole = ratio(offW, offN)
	h.DebutShare = float64(h.Debuts) / float64(n)
	h.WinrateDebut = ratio(debW, h.Debuts)
	h.WinrateRepeat = ratio(repW, n-h.Debuts)
	h.ComfortGames = comN
	h.WinrateComfort = ratio(comW, comN)
	h.UnfamiliarGames = unfN
	h.WinrateUnfamiliar = ratio(unfW, unfN)

	h.DistinctChamps = len(champN)
	entropy := 0.0
	for _, c := range champN {
		p := float64(c) / float64(n)
		entropy -= p * math.Log(p)
	}
	h.EffectiveChamps = math.Exp(entropy)
	return h
}

func ratio(num, den int) float64 {
	if den == 0 {
		return 0
	}
	return float64(num) / float64(den)
}

// percentileBelow: the share of the study population strictly below x.
// "more off-role than 86% of players" reads from this directly.
func percentileBelow(population []float64, x float64) float64 {
	if len(population) == 0 {
		return 0
	}
	n := 0
	for _, v := range population {
		if v < x {
			n++
		}
	}
	return float64(n) / float64(len(population))
}

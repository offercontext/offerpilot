package ai

import (
	"github.com/offercontext/offerpilot/internal/db"
)

// nearDuplicateThreshold is the character-bigram Jaccard similarity above which
// two questions are treated as the same (a reworded duplicate).
const nearDuplicateThreshold = 0.82

// dedupEntry caches a question's exact hash and bigram set for comparison.
type dedupEntry struct {
	hash    string
	bigrams map[string]struct{}
}

// DedupGenerated filters generated questions against the existing bank and
// against each other. It drops exact duplicates (normalized-hash match) and
// near-duplicates (character-bigram Jaccard >= threshold), returning the kept
// questions and the number skipped.
func DedupGenerated(existing []db.QuestionDigest, generated []GeneratedQuestion) (kept []GeneratedQuestion, skipped int) {
	hashes := make(map[string]struct{}, len(existing))
	entries := make([]dedupEntry, 0, len(existing)+len(generated))
	for _, d := range existing {
		h := d.Hash
		if h == "" {
			h = db.QuestionHash(d.Question)
		}
		hashes[h] = struct{}{}
		entries = append(entries, dedupEntry{hash: h, bigrams: bigramSet(db.NormalizeQuestion(d.Question))})
	}

	kept = make([]GeneratedQuestion, 0, len(generated))
	for _, g := range generated {
		norm := db.NormalizeQuestion(g.Question)
		if norm == "" {
			skipped++
			continue
		}
		h := db.QuestionHash(g.Question)
		if _, dup := hashes[h]; dup {
			skipped++
			continue
		}
		grams := bigramSet(norm)
		if isNearDuplicate(grams, entries) {
			skipped++
			continue
		}
		// Accept and register so later items in this batch also dedup against it.
		hashes[h] = struct{}{}
		entries = append(entries, dedupEntry{hash: h, bigrams: grams})
		kept = append(kept, g)
	}
	return kept, skipped
}

func isNearDuplicate(grams map[string]struct{}, entries []dedupEntry) bool {
	for _, e := range entries {
		if jaccard(grams, e.bigrams) >= nearDuplicateThreshold {
			return true
		}
	}
	return false
}

// bigramSet builds the set of adjacent character bigrams of a normalized
// string. Character bigrams work well for CJK text where whitespace tokenizing
// fails. Single-rune strings fall back to the rune itself.
func bigramSet(normalized string) map[string]struct{} {
	runes := []rune(normalized)
	set := make(map[string]struct{})
	if len(runes) == 0 {
		return set
	}
	if len(runes) == 1 {
		set[string(runes)] = struct{}{}
		return set
	}
	for i := 0; i < len(runes)-1; i++ {
		set[string(runes[i:i+2])] = struct{}{}
	}
	return set
}

func jaccard(a, b map[string]struct{}) float64 {
	if len(a) == 0 || len(b) == 0 {
		return 0
	}
	inter := 0
	// Iterate the smaller set for efficiency.
	small, large := a, b
	if len(b) < len(a) {
		small, large = b, a
	}
	for k := range small {
		if _, ok := large[k]; ok {
			inter++
		}
	}
	union := len(a) + len(b) - inter
	if union == 0 {
		return 0
	}
	return float64(inter) / float64(union)
}

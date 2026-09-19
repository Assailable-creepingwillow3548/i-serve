package main

import (
	"fmt"
	"strings"
	"testing"
)

// The property the whole design rests on: two requests that begin alike route
// alike, however differently they end. This is the shared system prompt, which
// is the case prefix caching exists for.
func TestSharedPrefixGivesOneKey(t *testing.T) {
	sys := strings.Repeat("You are a careful assistant. ", 40) // > 512 bytes
	a := fmt.Sprintf(`{"model":"qwen","prompt":%q}`, sys+"Summarise the incident.")
	b := fmt.Sprintf(`{"model":"qwen","prompt":%q}`, sys+"Translate this to Finnish.")

	ka, oka := cacheKey([]byte(a), 512)
	kb, okb := cacheKey([]byte(b), 512)
	if !oka || !okb {
		t.Fatal("a well-formed prompt was not read")
	}
	if ka != kb {
		t.Error("prompts sharing their first 512 bytes got different keys")
	}
}

// ...and the converse, or the first test only proves the hash is constant.
func TestDifferentPrefixesGiveDifferentKeys(t *testing.T) {
	a := `{"model":"qwen","prompt":"Translate: hello"}`
	b := `{"model":"qwen","prompt":"Translate: goodbye"}`
	ka, _ := cacheKey([]byte(a), 512)
	kb, _ := cacheKey([]byte(b), 512)
	if ka == kb {
		t.Error("different prompts collided")
	}
}

// The model is in the key. One engine serves one model today; the day that
// changes, a key without it merges two models' prefixes and the symptom is a
// cache that never hits.
func TestModelIsPartOfTheKey(t *testing.T) {
	a := `{"model":"qwen","prompt":"same words"}`
	b := `{"model":"llama","prompt":"same words"}`
	ka, _ := cacheKey([]byte(a), 512)
	kb, _ := cacheKey([]byte(b), 512)
	if ka == kb {
		t.Error("two models shared one key")
	}
}

// Both legal shapes of /v1/chat/completions and /v1/completions are read. A
// router that understands only one of them silently sends half the traffic
// round_robin.
func TestBothRequestShapesAreRead(t *testing.T) {
	bodies := map[string]string{
		"chat":          `{"model":"qwen","messages":[{"role":"system","content":"be brief"},{"role":"user","content":"hi"}]}`,
		"prompt array":  `{"model":"qwen","prompt":["one","two"]}`,
		"prompt string": `{"model":"qwen","prompt":"one"}`,
	}
	for name, body := range bodies {
		if _, ok := cacheKey([]byte(body), 512); !ok {
			t.Errorf("%s: no key read", name)
		}
	}
}

// Concatenation without separators would make ["ab","c"] and ["a","bc"] one
// key -- two different prompts on one replica's cache, reported as a hit that
// cannot happen.
func TestArrayBoundariesAreNotFlattenedAway(t *testing.T) {
	a, _ := cacheKey([]byte(`{"model":"qwen","prompt":["ab","c"]}`), 512)
	b, _ := cacheKey([]byte(`{"model":"qwen","prompt":["a","bc"]}`), 512)
	if a == b {
		t.Error("array element boundaries were lost")
	}
}

// Every shape the router cannot read has to answer false rather than guess.
// false is the round_robin path and it is honest; a guessed key is not.
func TestUnreadableBodiesTakeTheFallback(t *testing.T) {
	for _, body := range []string{
		`not json at all`,
		`{"model":"qwen"}`,                           // no prompt field
		`{"model":"qwen","prompt":""}`,               // empty prompt
		`{"model":"qwen","prompt":{"unexpected":1}}`, // a shape this router does not decode
		`{"model":"qwen","messages":[]}`,             // nothing to key on
	} {
		if _, ok := cacheKey([]byte(body), 512); ok {
			t.Errorf("a key was produced from %s", body)
		}
	}
}

// key-bytes = 0 means the whole prompt: exact repeats only.
func TestZeroKeyBytesRoutesOnlyExactRepeats(t *testing.T) {
	sys := strings.Repeat("x", 4000)
	a, _ := cacheKey([]byte(fmt.Sprintf(`{"model":"q","prompt":%q}`, sys+"one")), 0)
	b, _ := cacheKey([]byte(fmt.Sprintf(`{"model":"q","prompt":%q}`, sys+"two")), 0)
	if a == b {
		t.Error("key-bytes=0 still matched on a prefix")
	}
}

// The shape bench/loadgen.py sends: the prompt as token ids. Before 2026-09-19
// this body produced no key, so every benchmark request took the `no-prompt`
// fallback and a prefix-routing arm measured round_robin against round_robin --
// with no error anywhere, which is what makes it worth a test rather than a
// note (docs/benchmarks/runsheets/mi300x-run-3.md section 0).
func TestTokenIdPromptsAreKeyed(t *testing.T) {
	body := `{"model":"qwen","prompt":[151,2934,88,17],"max_tokens":200}`
	if _, ok := cacheKey([]byte(body), 512); !ok {
		t.Fatal("a token-id prompt produced no key")
	}
}

// Two prompts that share their leading ids and differ after the cut are one
// key, which is the whole routing claim stated in ids instead of bytes -- and
// in ids it holds without the BPE qualifier the file header carries.
func TestTokenIdPromptsShareAKeyByTheirPrefix(t *testing.T) {
	// Sixteen ids of five characters each is past a 64-byte cut; the tails
	// differ and must not reach the key.
	a := `{"model":"qwen","prompt":[10001,10002,10003,10004,10005,10006,10007,10008,10009,10010,10011,10012,10013,10014,77777]}`
	b := `{"model":"qwen","prompt":[10001,10002,10003,10004,10005,10006,10007,10008,10009,10010,10011,10012,10013,10014,88888]}`
	ka, oka := cacheKey([]byte(a), 64)
	kb, okb := cacheKey([]byte(b), 64)
	if !oka || !okb {
		t.Fatal("no key")
	}
	if ka != kb {
		t.Error("a shared id prefix did not share a key")
	}
	// And the cut is real: the same two prompts keyed in full are two keys.
	if fa, _ := cacheKey([]byte(a), 0); fa == mustKey(t, b, 0) {
		t.Error("prompts differing in their last id shared a whole-prompt key")
	}
}

// [1,23] and [12,3] are different prompts and must not collide, for the same
// reason ["ab","c"] and ["a","bc"] must not.
func TestTokenIdBoundariesAreNotFlattenedAway(t *testing.T) {
	a, _ := cacheKey([]byte(`{"model":"qwen","prompt":[1,23]}`), 512)
	b, _ := cacheKey([]byte(`{"model":"qwen","prompt":[12,3]}`), 512)
	if a == b {
		t.Error("id boundaries were lost")
	}
}

func mustKey(t *testing.T, body string, keyBytes int) uint64 {
	t.Helper()
	k, ok := cacheKey([]byte(body), keyBytes)
	if !ok {
		t.Fatalf("no key from %s", body)
	}
	return k
}

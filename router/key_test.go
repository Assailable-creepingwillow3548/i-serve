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

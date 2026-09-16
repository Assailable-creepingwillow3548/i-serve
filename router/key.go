package main

// What gets hashed, and the one claim this file has to be able to defend.
//
// vLLM's prefix cache is keyed on blocks of tokens, matched from token zero
// (`docs/GLOSSARY.md`, *Prefix caching*). A router that wants a hit must
// therefore group requests by their leading tokens -- and it has no tokenizer.
// Loading one would mean shipping a second copy of the model's vocabulary and
// keeping it equal to the engine's; a wrong tokenizer routes confidently to the
// wrong replica, which is worse than not routing at all.
//
// So the key is the first keyBytes *bytes* of the prompt, and the claim is
// this: two prompts sharing a byte prefix share every token of that prefix
// except, at most, the one token straddling the cut. BPE is deterministic and
// reads left to right, so an identical byte run produces an identical token run
// up to the boundary. At vLLM's 16-token block size that costs at most one
// block of the shared prefix -- an error in the safe direction, since it
// understates the hit, never overstates it.
//
// What this does not claim: that a shared prefix is *in* the cache. That
// depends on eviction, which lives on the replica. Affinity raises the
// probability of a hit; it does not produce one.

import (
	"encoding/json"
	"strings"
)

// promptBody is the part of an OpenAI-shaped request this router reads. Every
// other field is ignored and forwarded untouched -- the router is a proxy, not
// a schema.
//
// Prompt and Content are RawMessage because each has two legal shapes: a string
// or an array. Decoding into a concrete type would reject half of the API.
type promptBody struct {
	Model    string          `json:"model"`
	Prompt   json.RawMessage `json:"prompt"`
	Messages []struct {
		Role    string          `json:"role"`
		Content json.RawMessage `json:"content"`
	} `json:"messages"`
}

// cacheKey returns the hash of the request's leading prompt bytes, and whether
// a prompt was found at all. false is not an error: it is the signal to fall
// back to round_robin, and the caller reports which of the two ran.
//
// keyBytes <= 0 means the whole prompt, which routes only exact repeats.
func cacheKey(body []byte, keyBytes int) (uint64, bool) {
	var b promptBody
	if err := json.Unmarshal(body, &b); err != nil {
		return 0, false
	}

	var sb strings.Builder

	// The model name is part of the key. One engine serves one model here, but
	// a key without it silently merges two models' prefixes the day that stops
	// being true, and the symptom would be a cache that never hits.
	sb.WriteString(b.Model)
	sb.WriteByte(0)
	base := sb.Len()

	// Separators are bytes that cannot appear in JSON-decoded text at these
	// positions, so that ["ab","c"] and ["a","bc"] cannot produce one key.
	switch {
	case len(b.Prompt) > 0:
		writeStringOrArray(&sb, b.Prompt, keyBytes, base)
	default:
		for _, m := range b.Messages {
			if keyBytes > 0 && sb.Len()-base >= keyBytes {
				break
			}
			sb.WriteString(m.Role)
			sb.WriteByte(0x1f)
			writeStringOrArray(&sb, m.Content, keyBytes, base)
			sb.WriteByte(0x1e)
		}
	}

	s := sb.String()
	if len(s) <= base {
		return 0, false // a body we could parse but found no prompt in
	}
	if keyBytes > 0 && len(s)-base > keyBytes {
		s = s[:base+keyBytes]
	}
	return hash64(s), true
}

// writeStringOrArray appends one JSON value that may be a string or an array of
// strings, stopping once the builder holds keyBytes of prompt. Anything else --
// a number, an object, a multimodal content part -- is skipped rather than
// guessed at; a body made only of those yields no key and takes the fallback.
func writeStringOrArray(sb *strings.Builder, raw json.RawMessage, keyBytes, base int) {
	var one string
	if err := json.Unmarshal(raw, &one); err == nil {
		sb.WriteString(one)
		return
	}
	var many []string
	if err := json.Unmarshal(raw, &many); err == nil {
		for _, s := range many {
			if keyBytes > 0 && sb.Len()-base >= keyBytes {
				return
			}
			sb.WriteString(s)
			sb.WriteByte(0x1d)
		}
	}
}

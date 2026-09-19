package main

import (
	"bytes"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

// testDial is generous on purpose. Every upstream in this suite is a
// httptest server on the loopback address, so the dial timeout is never the
// thing under test; a tight value here would only turn a loaded CI runner
// into a flake. What the production default is, and why, is newTransport.
const testDial = 5 * time.Second

// fleet stands up n upstreams that report which one they are, plus the router
// in front of them.
func fleet(t *testing.T, n int, keyBytes int, maxBody int64) (*httptest.Server, *router, []string, func(string) []byte) {
	t.Helper()

	var addrs []string

	// The handlers run on the test server's goroutines, so the record of what
	// each upstream received is guarded. Without this the suite passes and
	// `go test -race` does not.
	var mu sync.Mutex
	bodies := map[string][]byte{}

	for i := 0; i < n; i++ {
		i := i
		up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			b, _ := io.ReadAll(r.Body)
			mu.Lock()
			bodies[fmt.Sprintf("%d", i)] = b
			mu.Unlock()
			fmt.Fprintf(w, "upstream-%d", i)
		}))
		t.Cleanup(up.Close)
		addrs = append(addrs, up.URL)
	}

	rt := newRouter(keyBytes, maxBody, 1.25, testDial, true)
	rt.setUpstreams(addrs, 128)
	front := httptest.NewServer(rt)
	t.Cleanup(front.Close)

	return front, rt, addrs, func(k string) []byte {
		mu.Lock()
		defer mu.Unlock()
		return bodies[k]
	}
}

func post(t *testing.T, srv *httptest.Server, path, body string) *http.Response {
	t.Helper()
	resp, err := http.Post(srv.URL+path, "application/json", strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	return resp
}

// The point of the whole component, end to end: one prompt, one replica, every
// time -- so the second request finds the first one's KV where it was left.
func TestOnePromptOneUpstream(t *testing.T) {
	front, _, _, _ := fleet(t, 4, 512, 1<<20)
	body := `{"model":"qwen","prompt":"the same long system prompt, repeated"}`

	first := ""
	for i := 0; i < 20; i++ {
		resp := post(t, front, "/v1/completions", body)
		got, _ := io.ReadAll(resp.Body)
		resp.Body.Close()

		if p := resp.Header.Get("X-Router-Policy"); p != "prefix" {
			t.Fatalf("policy %q, want prefix", p)
		}
		if first == "" {
			first = string(got)
		} else if string(got) != first {
			t.Fatalf("request %d landed on %s, the first on %s", i, got, first)
		}
	}
}

// ...and the fleet is still used. A router that pins everything to one replica
// would pass the test above.
func TestDistinctPromptsUseTheFleet(t *testing.T) {
	front, _, addrs, _ := fleet(t, 4, 512, 1<<20)

	seen := map[string]bool{}
	for i := 0; i < 200; i++ {
		resp := post(t, front, "/v1/completions", fmt.Sprintf(`{"model":"qwen","prompt":"request number %d"}`, i))
		got, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		seen[string(got)] = true
	}
	if len(seen) != len(addrs) {
		t.Errorf("%d of %d replicas received traffic", len(seen), len(addrs))
	}
}

// Reading the body to route is only safe if the body still arrives. This is the
// test that a proxy which inspects payloads has to pass first.
func TestBodyArrivesIntact(t *testing.T) {
	front, _, _, bodyOf := fleet(t, 1, 512, 1<<20)
	sent := fmt.Sprintf(`{"model":"qwen","prompt":%q}`, strings.Repeat("token ", 3000))

	resp := post(t, front, "/v1/completions", sent)
	resp.Body.Close()

	if got := string(bodyOf("0")); got != sent {
		t.Errorf("upstream received %d bytes, %d were sent", len(got), len(sent))
	}
}

// Past the cap the router stops trying to read a prompt -- but it must not stop
// forwarding. The bytes already read are replayed in front of the rest.
func TestOversizedBodyIsForwardedWhole(t *testing.T) {
	front, _, _, bodyOf := fleet(t, 1, 512, 256)
	sent := fmt.Sprintf(`{"model":"qwen","prompt":%q}`, strings.Repeat("x", 4000))

	resp := post(t, front, "/v1/completions", sent)
	defer resp.Body.Close()

	if p := resp.Header.Get("X-Router-Policy"); p != "oversized-body" {
		t.Errorf("policy %q, want oversized-body", p)
	}
	if got := string(bodyOf("0")); got != sent {
		t.Errorf("upstream received %d bytes, %d were sent", len(got), len(sent))
	}
}

// A completion is a stream. A proxy that batches writes turns a good TPOT into
// a bad one without the engine changing at all, and the failure is invisible in
// any test that reads the whole response before looking at it.
func TestStreamIsNotBuffered(t *testing.T) {
	release := make(chan struct{})
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "text/event-stream")
		fl := w.(http.Flusher)
		io.WriteString(w, "data: one\n\n")
		fl.Flush()
		<-release
		io.WriteString(w, "data: two\n\n")
		fl.Flush()
	}))
	defer up.Close()

	rt := newRouter(512, 1<<20, 1.25, testDial, true)
	rt.setUpstreams([]string{up.URL}, 128)
	front := httptest.NewServer(rt)
	defer front.Close()

	resp := post(t, front, "/v1/completions", `{"model":"qwen","prompt":"stream please","stream":true}`)
	defer resp.Body.Close()

	first := make([]byte, len("data: one\n\n"))
	done := make(chan error, 1)
	go func() { _, err := io.ReadFull(resp.Body, first); done <- err }()

	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		close(release)
		t.Fatal("the first frame did not reach the client while the second was still unwritten: the proxy buffered the stream")
	}
	close(release)

	if !bytes.Contains(first, []byte("one")) {
		t.Errorf("first frame was %q", first)
	}
}

// An upstream that is gone is a 502 and a log line, not a panic and not a
// retry: a retried generation re-spends accelerator time already spent.
func TestDeadUpstreamIs502(t *testing.T) {
	dead := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	addr := dead.URL
	dead.Close()

	rt := newRouter(512, 1<<20, 1.25, testDial, true)
	rt.setUpstreams([]string{addr}, 128)
	front := httptest.NewServer(rt)
	defer front.Close()

	resp := post(t, front, "/v1/completions", `{"model":"qwen","prompt":"anything"}`)
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusBadGateway {
		t.Errorf("status %d, want 502", resp.StatusCode)
	}
}

// Scale-to-zero, or the moment before the first Pod is ready. 503 says "not
// now"; a panic says nothing and takes the router with it.
func TestNoUpstreamsIs503(t *testing.T) {
	rt := newRouter(512, 1<<20, 1.25, testDial, true)
	rt.setUpstreams(nil, 128)
	front := httptest.NewServer(rt)
	defer front.Close()

	resp := post(t, front, "/v1/completions", `{"model":"qwen","prompt":"anything"}`)
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusServiceUnavailable {
		t.Errorf("status %d, want 503", resp.StatusCode)
	}
}

// Routes with no prompt in them are not read at all -- that copy would buy
// nothing -- and the policy header says so rather than claiming a prefix hit.
func TestUnkeyedPathsAreRoundRobin(t *testing.T) {
	front, _, addrs, _ := fleet(t, 3, 512, 1<<20)

	seen := map[string]bool{}
	for i := 0; i < len(addrs); i++ {
		resp, err := http.Get(front.URL + "/v1/models")
		if err != nil {
			t.Fatal(err)
		}
		got, _ := io.ReadAll(resp.Body)
		resp.Body.Close()

		if p := resp.Header.Get("X-Router-Policy"); p != "unkeyed-path" {
			t.Fatalf("policy %q, want unkeyed-path", p)
		}
		seen[string(got)] = true
	}
	if len(seen) != len(addrs) {
		t.Errorf("round_robin used %d of %d replicas in %d requests", len(seen), len(addrs), len(addrs))
	}
}

// The in-flight counter is what the bounded-load rule reads. If it leaked, the
// cap would tighten with every request until the ring routed by nothing but
// load -- affinity silently gone, no error anywhere.
func TestInFlightReturnsToZero(t *testing.T) {
	front, rt, _, _ := fleet(t, 2, 512, 1<<20)

	// Concurrently, because a leak of one per request is arithmetic and a leak
	// under contention is a race.
	var wg sync.WaitGroup
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			resp, err := http.Post(front.URL+"/v1/completions", "application/json",
				strings.NewReader(`{"model":"qwen","prompt":"x"}`))
			if err != nil {
				return
			}
			io.Copy(io.Discard, resp.Body)
			resp.Body.Close()
		}()
	}
	wg.Wait()

	var total int64
	for _, r := range rt.current.Load().replicas {
		total += r.inFlight.Load()
	}
	if total != 0 {
		t.Errorf("%d requests still counted in flight after all of them finished", total)
	}
}

// The control arm: the same binary, the same hop, the same fleet, and the
// affinity thrown away. It exists so a measurement can attribute a difference
// to the policy rather than to the route the traffic took
// (docs/benchmarks/runsheets/mi300x-run-3.md section 4).
func TestRoundRobinPolicySpreadsOneKeyAndSaysSo(t *testing.T) {
	front, rt, addrs, _ := fleet(t, 4, 512, 1<<20)
	rt.affinity = false
	body := `{"model":"qwen","prompt":"the same long system prompt, repeated"}`

	seen := map[string]bool{}
	for i := 0; i < 20; i++ {
		resp := post(t, front, "/v1/completions", body)
		got, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if p := resp.Header.Get("X-Router-Policy"); p != "round_robin" {
			t.Fatalf("policy %q, want round_robin", p)
		}
		seen[string(got)] = true
	}
	if len(seen) != len(addrs) {
		t.Errorf("one key reached %d of %d replicas under round_robin", len(seen), len(addrs))
	}
}

// And the four fallbacks survive the control arm. A body the router cannot key
// still says so, so a control full of `no-prompt` is still the body-shape
// defect and not a policy that happens to look the same from outside.
func TestControlArmStillReportsAnUnkeyableBody(t *testing.T) {
	front, rt, _, _ := fleet(t, 2, 512, 1<<20)
	rt.affinity = false

	resp := post(t, front, "/v1/completions", `{"model":"qwen"}`)
	resp.Body.Close()
	if p := resp.Header.Get("X-Router-Policy"); p != "no-prompt" {
		t.Fatalf("policy %q, want no-prompt", p)
	}
}

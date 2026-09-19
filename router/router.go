package main

// The request path. Two things here are not what a generic reverse proxy does,
// and both are forced by the traffic:
//
//  1. The body is read before an upstream is chosen, because the routing
//     decision is *in* the body. That is a cost -- the prompt is held in memory
//     for the length of the choice -- and it is bounded, not assumed away.
//  2. Nothing is buffered on the way back. A completion is streamed token by
//     token, and a proxy that batches writes converts a good TPOT into a bad
//     one without touching the engine.

import (
	"bytes"
	"context"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"sync/atomic"
	"time"
)

type ctxKey int

// replicaKey carries the already-chosen replica from ServeHTTP into the
// proxy's Rewrite hook. The choice is made before proxying so that the
// in-flight counter is raised before the first byte leaves, not after.
const replicaKey ctxKey = 0

// keyedPaths are the routes whose bodies carry a prompt. Everything else --
// `/health`, `/v1/models`, a tokenizer call -- is round_robin: reading those
// bodies would buy nothing and cost a copy.
var keyedPaths = map[string]bool{
	"/v1/completions":      true,
	"/v1/chat/completions": true,
}

type router struct {
	// current is swapped wholesale when the replica set changes. A request
	// loads it once and uses that snapshot to the end, so a scale event
	// mid-stream cannot move a request that is already being served.
	current atomic.Pointer[ring]

	keyBytes int
	maxBody  int64
	c        float64

	proxy *httputil.ReverseProxy
}

func newRouter(keyBytes int, maxBody int64, c float64, dialTimeout time.Duration) *router {
	rt := &router{keyBytes: keyBytes, maxBody: maxBody, c: c}
	rt.proxy = &httputil.ReverseProxy{
		Transport: newTransport(dialTimeout),

		Rewrite: func(pr *httputil.ProxyRequest) {
			rep := pr.In.Context().Value(replicaKey).(*replica)
			pr.Out.URL.Scheme = rep.target.Scheme
			pr.Out.URL.Host = rep.target.Host
			pr.SetXForwarded()
		},

		// -1 flushes after every write. The default for a non-streaming
		// response is to let the transport batch, which is right for a web page
		// and wrong for an SSE stream: it would add proxy latency to every
		// token and make ITL a property of this process.
		FlushInterval: -1,

		// No retry, deliberately. `deploy/ingress/README.md` records why the
		// edge drops the `timeout` half of `proxy-next-upstream`: a retried
		// generation re-spends accelerator time that was already spent. A
		// connection error is the recoverable half and retrying it here is
		// defensible -- it is listed as unfinished in README.md rather than
		// written now, because the retry has to choose a *different* replica,
		// which is a second routing decision and needs its own test.
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			rep, _ := r.Context().Value(replicaKey).(*replica)
			addr := ""
			if rep != nil {
				addr = rep.addr
			}
			log.Printf("upstream %s: %v", addr, err)
			w.WriteHeader(http.StatusBadGateway)
		},
	}
	return rt
}

// newTransport is the whole reason this router does not use the default one,
// and the reason was measured rather than reasoned about: the figures are in
// `../deploy/router/README.md` section 2, and are not repeated here.
//
// The mechanism behind them is this. `http.DefaultTransport` dials with a 30 s
// timeout. A Pod address removed from the fleet does not refuse connections --
// it blackholes them, because nothing in the cluster network claims the
// address any more -- so every request the ring sends to a departed replica
// waits out that full timeout before its 502, which is two orders of magnitude
// past the TTFT budget (`../docs/SLO.md` section 1) spent producing an error.
//
// The dial timeout is therefore a policy number and not a detail: it is how
// long the router is willing to spend discovering that a replica is gone. It
// does not make the request succeed -- there is no retry (see ErrorHandler
// above) -- it makes the failure arrive inside the budget instead of a hundred
// budgets later.
//
// What the default buys that a short timeout gives up: TCP's initial
// retransmission timeout is 1 s (RFC 6298 section 2.1), so a timeout below
// that fails a request whose single SYN was dropped, where the default would
// have recovered it. That is the
// right side of the trade only because the alternative is spending three
// TTFT budgets on one lost packet, and because the real answer to a dropped
// SYN is the retry on a *different* replica that README.md still lists as
// unwritten.
func newTransport(dialTimeout time.Duration) http.RoundTripper {
	// Cloned, so every other default -- idle pooling, HTTP/2 negotiation,
	// proxy environment -- stays whatever the standard library thinks is
	// right. One field is changed, and it is the one that was measured.
	tr := http.DefaultTransport.(*http.Transport).Clone()
	tr.DialContext = (&net.Dialer{
		Timeout: dialTimeout,
		// Unchanged from the default, and kept explicit because it is next to
		// the field that is not: this is the TCP keepalive probe interval on
		// an established connection, not a limit on the dial.
		KeepAlive: 30 * time.Second,
	}).DialContext
	return tr
}

// setUpstreams rebuilds the ring, carrying the in-flight counts of replicas
// that survive.
func (rt *router) setUpstreams(addrs []string, vnodes int) {
	rt.current.Store(newRing(rt.current.Load(), addrs, vnodes))
}

func (rt *router) ServeHTTP(w http.ResponseWriter, req *http.Request) {
	rg := rt.current.Load()
	if rg == nil || len(rg.replicas) == 0 {
		http.Error(w, "no upstreams", http.StatusServiceUnavailable)
		return
	}

	rep, policy := rt.choose(rg, req)
	if rep == nil {
		http.Error(w, "no upstreams", http.StatusServiceUnavailable)
		return
	}

	// Raised here and released by defer, so the count covers the whole stream
	// and not just the choice. ServeHTTP does not return until the last SSE
	// frame has been copied, which is exactly the interval "in flight" means.
	rep.inFlight.Add(1)
	defer rep.inFlight.Add(-1)

	// Set before proxying: the upstream does not send these names, so they
	// survive the header copy. They are what makes the decision observable
	// from outside without a debugger.
	w.Header().Set("X-Router-Upstream", rep.addr)
	w.Header().Set("X-Router-Policy", policy)

	rt.proxy.ServeHTTP(w, req.WithContext(context.WithValue(req.Context(), replicaKey, rep)))
}

// choose returns the replica and the name of the policy that produced it. The
// name is not decoration: three of the four values mean "this request will not
// hit a warm prefix", and an operator who cannot tell them apart cannot tell a
// cold workload from a broken router.
func (rt *router) choose(rg *ring, req *http.Request) (*replica, string) {
	if req.Method != http.MethodPost || !keyedPaths[req.URL.Path] {
		return rg.next(), "unkeyed-path"
	}

	body, buffered, err := readBody(req, rt.maxBody)
	switch {
	case err != nil:
		// The client stopped sending. Forward it anyway and let the upstream
		// produce the error; the router has no better answer than the engine.
		return rg.next(), "unreadable-body"
	case !buffered:
		return rg.next(), "oversized-body"
	}

	key, ok := cacheKey(body, rt.keyBytes)
	if !ok {
		return rg.next(), "no-prompt"
	}
	return rg.pick(key, rt.c), "prefix"
}

// readBody reads the request body so the prompt can be inspected, and puts it
// back so the upstream still receives it in full.
//
// buffered is false when the body is larger than maxBody. That is the bound on
// the cost of routing: past it the router stops trying to read a prompt and
// streams the request through, rather than holding an unbounded copy of it in
// memory once per concurrent request. 4 000-token prompts are ~16 kB, so the
// default leaves three orders of magnitude of room -- the cap is there for the
// request that is not a prompt at all.
//
// Overwriting req.Body is safe: net/http keeps its own reference for closing
// the connection, so replacing the field does not leak the original.
func readBody(req *http.Request, maxBody int64) (body []byte, buffered bool, err error) {
	if req.Body == nil {
		return nil, true, nil
	}

	// maxBody+1 is how "too big" is detected without reading it all.
	body, err = io.ReadAll(io.LimitReader(req.Body, maxBody+1))
	if err != nil {
		return nil, false, err
	}

	if int64(len(body)) <= maxBody {
		req.Body = io.NopCloser(bytes.NewReader(body))
		return body, true, nil
	}

	// Too big: hand the upstream the bytes already read, followed by the rest,
	// still streamed. Nothing is dropped and nothing further is held.
	req.Body = io.NopCloser(io.MultiReader(bytes.NewReader(body), req.Body))
	return body, false, nil
}

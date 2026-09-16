package main

// prefix-router -- one hop that chooses a replica by prompt prefix instead of
// by turn. What it is for, what it is worth and what it has not established:
// README.md in this directory.

import (
	"context"
	"flag"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"sync/atomic"
	"syscall"
	"time"
)

func main() {
	listen := flag.String("listen", ":8080", "address to serve on")
	upstreams := flag.String("upstreams", "", "comma-separated engine addresses, e.g. http://10.0.0.1:8000")
	vnodes := flag.Int("vnodes", 128, "ring points per replica; imbalance falls with about 1/sqrt of this")
	keyBytes := flag.Int("key-bytes", 512, "prompt bytes that form the routing key; 0 means the whole prompt")
	maxBody := flag.Int64("max-body", 1<<20, "bytes of request body the router will hold to read a prompt")
	load := flag.Float64("bounded-load", 1.25, "in-flight cap as a multiple of the fleet mean; 1 or less disables the bound")
	drain := flag.Duration("drain", 5*time.Second, "time between failing readiness and closing the listener on SIGTERM")
	flag.Parse()

	addrs := splitAddrs(*upstreams)
	if len(addrs) == 0 {
		log.Fatal("-upstreams is required")
	}

	rt := newRouter(*keyBytes, *maxBody, *load)
	rt.setUpstreams(addrs, *vnodes)

	// The replica set is a flag today. It is a watch tomorrow, and the shape
	// above is what makes that a one-file change: setUpstreams is already safe
	// to call while requests are in flight.
	var ready atomic.Bool
	ready.Store(true)

	mux := http.NewServeMux()

	// Reserved prefix, so no engine route can ever collide with it: vLLM serves
	// `/v1/...`, `/health` and `/metrics`, and this is none of them.
	mux.HandleFunc("/-/healthz", func(w http.ResponseWriter, r *http.Request) {
		if !ready.Load() {
			http.Error(w, "draining", http.StatusServiceUnavailable)
			return
		}
		w.Write([]byte("ok\n"))
	})
	mux.Handle("/", rt)

	srv := &http.Server{
		Addr:    *listen,
		Handler: mux,

		// No WriteTimeout. A completion is a long response by construction, and
		// a write deadline here would cut generations that the engine is
		// producing correctly -- the same class of mistake as an edge timeout
		// shorter than the longest legitimate answer (`docs/SLO.md`).
		ReadHeaderTimeout: 10 * time.Second,
	}

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGTERM, syscall.SIGINT)

	go func() {
		<-stop

		// Fail readiness first, then wait, then stop accepting. Withdrawing
		// readiness and withdrawing traffic are one action, and the gap between
		// them is how long the thing in front takes to notice
		// (`deploy/ingress/README.md`). Closing the listener first would drop
		// requests that were routed here a moment ago.
		ready.Store(false)
		time.Sleep(*drain)

		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if err := srv.Shutdown(ctx); err != nil {
			log.Printf("shutdown: %v", err)
		}
	}()

	log.Printf("prefix-router on %s over %d upstreams, key %d bytes, bounded load %.2f",
		*listen, len(addrs), *keyBytes, *load)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
}

func splitAddrs(s string) []string {
	var out []string
	for _, a := range strings.Split(s, ",") {
		if a = strings.TrimSpace(a); a != "" {
			out = append(out, a)
		}
	}
	return out
}

package main

import (
	"fmt"
	"math"
	"testing"
)

func addrs(n int) []string {
	out := make([]string, n)
	for i := range out {
		out[i] = fmt.Sprintf("http://10.0.0.%d:8000", i+1)
	}
	return out
}

func keys(n int) []uint64 {
	out := make([]uint64, n)
	for i := range out {
		out[i] = hash64(fmt.Sprintf("prompt-%d", i))
	}
	return out
}

// The in-flight count is the one piece of state a rebuild must not lose: the
// rebuild happens under a scale event, which is to say under load, and a reset
// would tell the bounded-load rule that every surviving replica is idle.
func TestRebuildCarriesInFlight(t *testing.T) {
	a := newRing(nil, addrs(2), 16)
	a.replicas[0].inFlight.Add(7)

	b := newRing(a, addrs(3), 16)
	if got := b.replicas[0].inFlight.Load(); got != 7 {
		t.Fatalf("surviving replica lost its count: got %d, want 7", got)
	}
	if got := b.replicas[2].inFlight.Load(); got != 0 {
		t.Fatalf("new replica started loaded: got %d, want 0", got)
	}
	if a.replicas[0] != b.replicas[0] {
		t.Fatal("surviving replica was rebuilt rather than carried")
	}
}

// Why a ring and not `hash % n`, as a number rather than an assertion.
//
// Adding one replica is the event KEDA produces, repeatedly, under exactly the
// load that makes cache locality worth having. Under modulo, nearly every key
// lands somewhere new -- a fleet-wide cache miss timed to arrive with the
// traffic. Under the ring, only the arc the newcomer took moves.
//
// The gap is what the routing is for: run 3 measured 12.5 seats at h = 0
// against 37.8 at h = 0.8 (`docs/SLO.md` section 6).
func TestRingMovesFarFewerKeysThanModulo(t *testing.T) {
	ks := keys(20000)
	before, after := newRing(nil, addrs(4), 128), newRing(nil, addrs(5), 128)

	var ringMoved, moduloMoved int
	for _, k := range ks {
		if before.pick(k, 0).addr != after.pick(k, 0).addr {
			ringMoved++
		}
		if k%4 != k%5 {
			moduloMoved++
		}
	}

	ringFrac := float64(ringMoved) / float64(len(ks))
	moduloFrac := float64(moduloMoved) / float64(len(ks))
	t.Logf("4 -> 5 replicas: ring moves %.1f%% of keys, modulo moves %.1f%%", ringFrac*100, moduloFrac*100)

	// The ideal for a ring is 1/5 = 20%: the share the newcomer claims.
	if ringFrac > 0.30 {
		t.Errorf("ring moved %.1f%% of keys, want <= 30%%", ringFrac*100)
	}
	if moduloFrac < 0.70 {
		t.Errorf("modulo moved %.1f%% of keys, want >= 70%% -- the comparison is not what it claims", moduloFrac*100)
	}
}

// Virtual nodes are not decoration: they are the difference between a ring that
// balances and one that hands a third of the traffic to one replica.
func TestVnodesBalanceTheRing(t *testing.T) {
	ks := keys(20000)
	for _, vnodes := range []int{1, 128} {
		rg := newRing(nil, addrs(4), vnodes)
		counts := map[string]int{}
		for _, k := range ks {
			counts[rg.pick(k, 0).addr]++
		}

		mean := float64(len(ks)) / 4
		var sq float64
		for _, c := range counts {
			sq += (float64(c) - mean) * (float64(c) - mean)
		}
		spread := math.Sqrt(sq/4) / mean
		t.Logf("vnodes=%d: relative spread %.3f", vnodes, spread)

		if vnodes == 128 && spread > 0.15 {
			t.Errorf("vnodes=128 left a spread of %.3f, want <= 0.15", spread)
		}
	}
}

// Affinity with no bound is a way to overload one replica on purpose. One
// popular system prompt is one key, and every request carrying it wants the
// same engine.
func TestBoundedLoadSpreadsOneHotKey(t *testing.T) {
	const hot = 40

	// Bound off: the owner takes all of it, which is the failure this exists
	// to prevent -- and it is asserted, so the test fails if the bound stops
	// being the thing that makes the difference.
	rg := newRing(nil, addrs(4), 128)
	k := hash64("a popular system prompt")
	for i := 0; i < hot; i++ {
		rg.pick(k, 0).inFlight.Add(1)
	}
	if got := rg.pick(k, 0).inFlight.Load(); got != hot {
		t.Fatalf("unbounded: owner holds %d of %d, want all of them", got, hot)
	}

	// Bound on, at 1.25x the fleet mean.
	rg = newRing(nil, addrs(4), 128)
	for i := 0; i < hot; i++ {
		rg.pick(k, 1.25).inFlight.Add(1)
	}

	used, max := 0, int64(0)
	for _, r := range rg.replicas {
		if n := r.inFlight.Load(); n > 0 {
			used++
			if n > max {
				max = n
			}
		}
	}
	t.Logf("bounded: %d of 4 replicas used, busiest holds %d of %d", used, max, hot)

	if used < 2 {
		t.Errorf("bounded load kept the hot key on %d replica(s)", used)
	}
	// 1.25 x mean, plus the +1 that makes an idle fleet routable.
	mean := float64(hot) / float64(len(rg.replicas))
	if want := int64(1.25*mean) + 1; max > want {
		t.Errorf("busiest replica holds %d, cap is %d", max, want)
	}
}

// The fallback has to be a policy, not a panic: an empty ring is what a router
// sees between a scale-to-zero and the first Pod becoming ready.
func TestEmptyRing(t *testing.T) {
	rg := newRing(nil, nil, 128)
	if rg.pick(123, 1.25) != nil || rg.next() != nil {
		t.Fatal("empty ring returned a replica")
	}
}

func TestUnparseableAddressIsDropped(t *testing.T) {
	rg := newRing(nil, []string{"http://10.0.0.1:8000", "not a url"}, 8)
	if len(rg.replicas) != 1 {
		t.Fatalf("got %d replicas, want 1", len(rg.replicas))
	}
}

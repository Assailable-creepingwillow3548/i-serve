package main

// The choice of replica, with no request handling in it. Everything here is
// decided before a byte is forwarded, and it is the half of the router that
// carries the argument: which replica already holds this prompt's KV, and what
// to do when that replica is the only one anybody wants.

import (
	"hash/fnv"
	"net/url"
	"sort"
	"strconv"
	"sync/atomic"
)

// replica is one upstream engine -- a vLLM Pod address, and the number of
// requests this router has handed it and not yet seen finish.
//
// The counter lives here rather than on the ring because the ring is rebuilt
// whenever the replica set changes, and a rebuild must not forget how loaded
// the surviving replicas are. Rebuilding is exactly when that number matters:
// it happens under a scale event, which is to say under load.
type replica struct {
	addr     string
	target   *url.URL // parsed once here, so the request path never parses
	inFlight atomic.Int64
}

// point is one position of one replica on the hash ring. A replica owns many
// of them (see vnodes) so that the arc it is responsible for is scattered
// rather than contiguous.
type point struct {
	hash uint64
	r    *replica
}

// ring is an immutable snapshot of the replica set. Nothing in it is mutated
// after newRing returns except the in-flight counters, which are atomic and
// deliberately shared with the ring that replaces this one. Readers therefore
// need no lock at all: they take the pointer once and use that snapshot for the
// whole request, even if the set changes underneath them mid-stream.
type ring struct {
	replicas []*replica
	points   []point // sorted by hash; binary-searched on every request

	// rr is the fallback cursor, used when a request carries no prompt this
	// router can read. A new ring restarts it at zero, which costs nothing:
	// round_robin has no memory worth preserving.
	rr atomic.Uint64
}

// newRing builds the ring for addrs, carrying over the replica objects of prev
// so that a replica present in both keeps its in-flight count. prev may be nil.
//
// vnodes is points per replica. With one point each, four replicas cut the hash
// space into four arcs of wildly unequal size; the imbalance falls with roughly
// 1/sqrt(vnodes), which is why the default is in the hundreds and not in the
// ones.
func newRing(prev *ring, addrs []string, vnodes int) *ring {
	if vnodes < 1 {
		vnodes = 1
	}

	// Index what already exists, so a rebuild is a diff rather than a reset.
	carried := map[string]*replica{}
	if prev != nil {
		for _, r := range prev.replicas {
			carried[r.addr] = r
		}
	}

	rg := &ring{}
	for _, addr := range addrs {
		r := carried[addr]
		if r == nil {
			// An address that will not parse is dropped at build time rather
			// than surfaced as a 502 on every request that hashes to it.
			u, err := url.Parse(addr)
			if err != nil || u.Host == "" {
				continue
			}
			r = &replica{addr: addr, target: u}
		}
		rg.replicas = append(rg.replicas, r)
		for i := 0; i < vnodes; i++ {
			rg.points = append(rg.points, point{
				hash: hash64(addr + "#" + strconv.Itoa(i)),
				r:    r,
			})
		}
	}
	sort.Slice(rg.points, func(i, j int) bool { return rg.points[i].hash < rg.points[j].hash })
	return rg
}

// pick returns the replica that owns key, walking forward from it while that
// replica is at capacity.
//
// The walk is the "bounded loads" half, and it exists because affinity without
// a bound is a way to overload one replica on purpose: a popular system prompt
// hashes to one point, and every request carrying it queues behind the last.
// The cap is c times the mean in-flight count, so it rises as the fleet fills
// and is never below one; c = 1 is strict balance and no affinity at all, and c
// large is affinity with no protection.
//
// c <= 1 is read as "no bound".
func (rg *ring) pick(key uint64, c float64) *replica {
	if len(rg.points) == 0 {
		return nil
	}

	// The owner of the key: the first point at or after it, wrapping.
	start := sort.Search(len(rg.points), func(i int) bool { return rg.points[i].hash >= key })
	if start == len(rg.points) {
		start = 0
	}
	if c <= 1 || len(rg.replicas) == 1 {
		return rg.points[start].r
	}

	// total+1 counts the request being routed, so that the cap of an idle fleet
	// is c/n rounded up -- one -- rather than zero.
	var total int64
	for _, r := range rg.replicas {
		total += r.inFlight.Load()
	}
	mean := float64(total+1) / float64(len(rg.replicas))
	limit := int64(c*mean) + 1

	for i := 0; i < len(rg.points); i++ {
		r := rg.points[(start+i)%len(rg.points)].r
		if r.inFlight.Load() < limit {
			return r
		}
	}

	// Unreachable while c > 1: the sum of the counts would have to exceed
	// n*limit > total. Returning the owner rather than nil keeps the failure a
	// hot replica instead of a dropped request.
	return rg.points[start].r
}

// next is the fallback policy: round_robin, the same one the edge already
// applies (`deploy/ingress/README.md`). Reached when a request carries no
// prompt this router can read, and the honest name for what it produces is the
// h = 0 column of `docs/SLO.md` section 6.
func (rg *ring) next() *replica {
	if len(rg.replicas) == 0 {
		return nil
	}
	i := rg.rr.Add(1) - 1
	return rg.replicas[i%uint64(len(rg.replicas))]
}

// hash64 is FNV-1a followed by an avalanche step. Not a cryptographic choice
// and not required to be one: nothing here defends against an adversary picking
// prompts to collide, and the cost is paid on every request.
//
// The second step is not optional, and the test that found that is
// TestVnodesBalanceTheRing. FNV-1a diffuses a late-byte difference upward by
// one multiplication only, so `addr#0` .. `addr#127` agree in their high bits
// -- and the ring is ordered by exactly those bits. All 128 points of a replica
// landed in one arc, which is a ring with the balance of a single point: the
// measured spread over four replicas was 0.53 where 0.09 was expected, and a
// fifth replica took 8.5% of the keys instead of 20%. The finalizer below is
// MurmurHash3's, and it is what makes "scatter the arcs" true rather than
// intended.
func hash64(s string) uint64 {
	h := fnv.New64a()
	h.Write([]byte(s))
	x := h.Sum64()

	x ^= x >> 33
	x *= 0xff51afd7ed558ccd
	x ^= x >> 33
	x *= 0xc4ceb9fe1a85ec53
	x ^= x >> 33
	return x
}

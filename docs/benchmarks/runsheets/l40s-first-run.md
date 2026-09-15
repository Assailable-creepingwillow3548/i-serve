# Runsheet — first server run: vLLM on L40S

The first time this stack faces hardware. Everything below was written *before*
the pod existed, so every number is a prediction the run must face — and per
`docs/SLO.md` §9 the first run is reported against the **uncalibrated** 0.70 /
0.45. All predictions below were produced by `bench/predictions.py`; re-run it
if the module has changed since. The owner types every command; this sheet only
says what comes next and which number to expect.

**On the day, execute `l40s-first-run-card.md`, not this file.** The card is
commands and values with no argument attached; this sheet holds every *why* and
wins on any conflict between the two.

**Cost, flagged up front, which is the rule every sheet here follows:** L40S 48 GB on
RunPod at **$0.99/h On-Demand**, read off the console 2026-08-15 and now the
figure in `bench/predictions.py`. That is the **Secure Cloud** rate; RunPod's
price page lists the same card at **$0.79/h on Community Cloud**, and the day
takes that 20% only if a Community data centre in North America also offers a
network volume — a question for the deploy page in §0, never an assumption, since
the volume is what binds the run to one data centre at all. Session budget
**≤ 2.5 h ≈ $2.50** at the Secure rate, of the
phase's $8–12, plus 25 GB for the weights on a **network volume** at $0.07/GB/month
under 1 TB — **$1.75/month, ~6 cents a day**, small enough that storage is a
bookkeeping line and never a decision. That rate is the network volume's, which is
what §1 provisions; a pod volume disk is priced separately and higher, and is not
what this run uses. Not Spot, on RunPod or anywhere: a reclaim mid-sweep makes a
benchmark unreproducible. Balance is loaded before the
session, not during it.

**Region: North America.** L40S has no European capacity (checked 2026-08-15),
so the pod is ~100–150 ms of RTT away. That is why every measurement in this
sheet runs `vllm bench serve` **on the pod, against loopback** — the network
never enters TTFT or TPOT. Nothing in the day needs to reach the server from the
laptop, which is why it binds to `127.0.0.1` (step 2): a curl from Europe would carry
300 ms of Atlantic and get read as a slow card, and a port that answers the
public proxy is an unattended bill.

**Scope.** Baseline BF16 only. FP8 KV — the §6 hypothesis — is deliberately the
*next* run, so it lands against a measured baseline rather than a derived one.

---

## 0 · Before renting the card (~25 min, a few cents)

- [ ] `python3 bench/tests/test_roofline.py` — 32 tests (77 assertions) against
      `docs/SLO.md` and against this sheet's own levels; it prints `32/32 passed`.
      Green before renting: a prediction that no
      longer matches its document is not a prediction worth spending GPU money to
      test.
- [ ] `python3 bench/predictions.py` — seven tables; keep them open. Tables 6 and
      7 are this sheet's sweeps, level by level, and every **floor** below is
      quoted from them rather than from memory. Four figures below are *not* in
      that output and are arithmetic done in this sheet, marked where they appear:
      15.3 GiB (the printed 16.4 GB in IEC), 26.8 GB (`docs/SLO.md` §4), and the
      seat sums of step 4.
- [ ] RunPod: balance loaded, MFA on, L40S On-Demand capacity visible in a North
      American data centre. **Two account facts that only bite at the form.**
      Deploy requires at least **one hour of the chosen configuration** in
      credits, so a balance that covers the session but not the hourly floor
      refuses the pod rather than warning about it. And at a $0 balance RunPod
      stops pods that have a network volume, preserving their data, but
      **terminates pods that do not, irrecoverably** — one more reason §1
      provisions a volume before it provisions a card.
- [ ] **A shell inside the pod, secured before the pod exists.** Everything after
      the boot — the smoke test, both sweeps, the harvest — runs from a terminal on
      the pod, and nothing about this image says one will be there: `vllm/vllm-openai`
      runs vLLM as its entrypoint and never starts `sshd`, and RunPod's own docs
      require an exposed port 22 and a running daemon for a custom template. The
      console's **web terminal is not the fallback it looks like**, for the same
      reason: it is launched by the `/start.sh` that RunPod's own base images
      carry, and an image whose PID 1 is `vllm serve` carries none of that
      scaffolding. **Expect basic SSH to be the only shell**, and treat a web
      terminal as a pleasant surprise rather than a plan. What
      stays open is RunPod's *basic* SSH, which proxies into any container
      "whether or not it has a built in SSH daemon" — and it reads the key from
      the **account settings**, so the public key goes up before any pod exists,
      not after one is running. **Done 2026-08-15**: a dedicated
      `~/.ssh/id_ed25519_runpod` (comment `runpod l40s`), pinned to
      `Host ssh.runpod.io` in `~/.ssh/config` with `IdentitiesOnly yes`, and
      uploaded — it is account-level, so the next run inherits it and the card no
      longer carries the step. Two things that stanza buys, both worth naming
      because the day pays for them if they are missed. `IdentitiesOnly yes`,
      because this `~/.ssh` holds four private keys: without it the agent offers
      them in its own order and the server disconnects after six failed
      attempts, which reads as a refused pod rather than as a full queue. And the
      connection is `ssh <pod-id>-<hash>@ssh.runpod.io` with **no `-i`** — the
      console's Connect dialog hands over a line with `-i ~/.ssh/id_ed25519`
      already appended, a command-line flag outranks `IdentityFile` from the
      config, and `IdentitiesOnly yes` then pins the session to exactly that wrong
      key. Copy the `user@host` out of that dialog and leave the flag behind. The
      key in the account is the one whose fingerprint is
      `SHA256:DsR5jl8tbwFFV5ZtPoqwFTi1gXRKSPKpBRkXbz44C2c` (comment `runpod l40s`),
      which is what Settings → SSH Public Keys shows. Then treat the first shell as a gate in step 1: open it while
      the weights are still downloading. A pod with no way in is worth terminating
      at minute two and not discovering at minute forty.
- [ ] **Three values only the RunPod console knows — read them off the deploy page
      while reading is still free.** The template's own Container Start Command
      (step 2 replaces it, so its shape has to be seen first), the hourly price
      against the $0.99 this sheet budgets at, and whether a North American
      **Community** data centre offers a network volume at all — the $0.79 rate
      above is only reachable if it does. None of the three can be checked from
      the working tree, and all three are on the screen before the rent button.
      `HF_HOME` is deliberately *not* on this list any more: step 1 sets it
      explicitly, which costs one field and removes a question.
- [ ] Nothing to check about the start command — **settled 2026-08-15, and it
      shapes steps 2 and 3.** The template's own Container Start Command reads
      `Qwen/Qwen3-8B --host 0.0.0.0 --port 8000 --dtype auto --enforce-eager
      --gpu-memory-utilization 0.95 --max-model-len 8128`. It begins with a bare
      model name and no verb, which is only valid as *arguments to* `vllm serve`:
      the field is appended to the image's `ENTRYPOINT`, never a replacement for
      it. So the server cannot be launched by hand inside a pod held open by
      `sleep infinity` — that string would arrive at argparse as a model name.
      **vLLM is PID 1 for the whole day**, and every engine knob is therefore
      fixed before the pod exists: changing one is a new pod, not a command. That
      is why step 2's line is the *only* start command of the day and why it
      already carries the 9 000 that step 5 needs — see step 2. There is exactly
      one way round it, and it is a fallback rather than the plan: the field also
      takes a JSON form, `{"entrypoint": [...], "cmd": [...]}`, which replaces the
      image's entrypoint outright. The day is not run that way on purpose — a
      hand-launched server can be killed and relaunched, and then nothing proves
      the old process is not still holding KV. It is kept for the pod that turns
      out to have no shell (below).
- [ ] Know the stop condition: **2.5 h wall clock or all checkpoints done,
      whichever comes first.** Then **terminate the pod, not stop it** — the
      opposite of what an instinct for "keep it, I might need it" suggests, and
      the network volume of step 1 is why. Everything worth keeping is on that
      volume, and a terminate does not touch it: the volume is a separate
      resource that outlives any pod attached to it. What a *stop* buys is
      nothing and costs twice. RunPod's own documentation is explicit that
      "stopping a Pod releases the GPU", so a stopped pod is not a card held in
      reserve; it stays pinned to one physical machine, and if that machine's
      L40S has been rented out meanwhile, starting it again yields a **zero-GPU
      pod** — a pod that boots with no accelerator and can only be waited on or
      terminated. Meanwhile the stopped pod keeps billing its disk. Terminate,
      and the next run attaches the same volume to whatever card has capacity.
- [ ] Know what gets dropped, decided now rather than at minute 140. The steps
      below sum to ~1 h 40 of the 2 h 30, and the 16.4 GB download eats most of
      the slack. Levels 8, 16 and 32 in step 4 only draw the curve; **1, 23, 24 and
      45 carry the argument** — drop the first three in that order, and never the
      last four or step 5, which is a different experiment rather than more of
      the same one.

## 1 · Pod up (~10 min)

Template **vLLM Latest** (the Verified one) — its default model is already
`Qwen/Qwen3-8B`. Everything else on the template is someone else's decision and
gets overridden, **starting with the image tag: override `:latest` to
`vllm/vllm-openai:v0.27.1`.** The two are byte-identical today — `v0.27.1` is
what `:latest` resolves to, pushed 2026-08-11 — which is exactly why the swap is
free: it costs one field and buys a provenance row that still means something in
a month. vLLM ships releases days apart (v0.27.0 and v0.27.1 are one day apart),
and every flag name, log line and scheduler default this sheet predicts belongs
to a release, not to a project. **GPU count 1**: the whole
derivation is single-card, and two cards are a different machine twice over —
tensor parallel splits the weights, replicas duplicate them, and this run cannot
separate the two on one card.

- [ ] Storage, persistent side: **network volume**, 25 GB, mounted at
      `/workspace`. Not the pod's own volume disk: the network volume outlives
      the pod itself rather than only a stop, which is what makes **terminate**
      the day's closing move (step 0) instead of a mistake to fear — a terminate
      costs a pod and not the 16.4 GB of weights, and the next run — FP8 KV —
      attaches the same volume instead of downloading them again. **Attach it on
      the deploy form**: a network volume cannot be added to a pod that already
      exists, so forgetting it here is a rebuild rather than an edit. It is also the thing the
      $0.07/GB/month above actually prices. **25 GB rather than the ~50 first
      budgeted**, deliberately: this run holds one model — 16.4 GB of
      weights, the compile cache and the day's logs, ~18 GB in total — and a
      network volume can be grown later but never shrunk, so the smaller size is
      the reversible one. A second model grows it rather than replacing it. The
      cost of choosing it: a network
      volume is bound to one data centre, so pick a North American one that shows
      L40S On-Demand capacity today, and accept that the volume cannot follow the
      capacity if that centre dries up.
- [ ] Storage, ephemeral side: **leave the template's container disk at its
      default**. It is erased on stop, but it holds the unpacked image, and
      `vllm/vllm-openai` is far larger than the few GB of scratch this step needs
      — trimming it to "we only write to `/workspace` anyway" is how a pod fails
      to start, or fills up mid-run.
- [ ] Environment variables:
      - `HF_HOME=/workspace/.huggingface` — **set it, do not inspect it.** An
        earlier draft of this sheet planned to read the template's own value and
        verify it; that is a gate with a bad payoff. The container runs as root
        with `HOME=/root`, so an unset `HF_HOME` resolves to
        `/root/.cache/huggingface` — the container disk, which dies with the pod
        and re-downloads 16.4 GB on the next one, at the GPU hourly rate. RunPod's
        own vLLM guide mounts the volume at that path rather than moving the
        variable, which is a second way to get the same result and a third
        convention to keep track of. One field settles it. Confirm afterwards
        with `du -sh $HF_HOME`, and on any later pod that nothing downloads again.
      - `VLLM_CACHE_ROOT=/workspace/.vllm` — the same argument one level down, and
        narrower than it looks. What lives under it is the **`torch.compile` /
        Inductor cache** and friends, which is real time: left on the container
        disk it is recompiled on every pod, at $0.99/h; on the volume it is paid
        once and the next run inherits it. What does **not** live under it is CUDA
        graphs — they are captured into GPU memory at every startup and have no
        on-disk artefact, so this variable cannot make graph capture faster. Do
        not read a second boot's capture time as a cache miss.
      - `VLLM_API_KEY` — from the password manager, generated with
        `echo "sk-$(openssl rand -hex 32)"` and stored there **2026-08-15**, so
        the day only pastes it into the deploy form. The default key is `sk-<pod-id>`,
        and the pod id is in the public proxy URL, so the default is a published
        key. Belt and braces: the server also binds to `127.0.0.1` (step 2), so the
        proxy has nothing to forward to. Never in this repository, and redacted
        from anything pasted into the report.
- [ ] **The shell gate, immediately after deploy and before anything else.** Open
      the basic SSH of step 0 and run `echo ok` — a web terminal, if the console
      offers one on this image, is a bonus and not the plan (step 0). Do it while
      the 16.4 GB is still
      downloading, because that wait is free and the answer decides whether the day
      happens at all: steps 2, 4, 5 and 6 all type commands into this shell. If
      nothing opens, stop here and take the fallback in "If it goes sideways"
      rather than waiting for a server nobody can reach.
- [ ] Record into the report: the image tag as pinned above, `vllm --version`
      (expect `0.27.1`, and if it is not, this sheet's log lines and scheduler
      defaults are the first things to re-check), and the driver from
      `nvidia-smi`. §9's provenance discipline applies to software too.

## 2 · The only boot — the startup log against the arithmetic (~20 min)

**There is no command to type in this step.** vLLM is the container's main
process and the start command is its argument list (step 0), so this boot is
configured in the template field *before the pod exists*, and every later change
to it is a new pod. This is **the only boot of the day** — step 3 says why the
second one was cut — so the line below has to be right the first time. The SSH
session is still the whole interface for everything after the boot; it just no
longer launches the server.

**Container Start Command — replace the template's line with exactly this:**

```
Qwen/Qwen3-8B --host 127.0.0.1 --port 8000 --dtype auto --gpu-memory-utilization 0.90 --max-model-len 9000 --no-enable-prefix-caching
```

One line in the field, model first and bare, the way the template's own line is
shaped. Against that line: three values change, one flag is dropped and one is
added, and the model, the port and `--dtype auto` are kept. None of the
differences are cosmetic:

- **`--enforce-eager` removed** — the template ships it, and it disables CUDA
  graphs, so every kernel is launched from Python. Launch overhead is paid per
  layer per decode step, which is exactly what this run measures — leaving it on
  would charge framework overhead to `eff_mem` and calibrate the coefficient
  against the wrong culprit. This is the single most consequential edit to the
  template's line.
- **`--gpu-memory-utilization 0.95 → 0.90`**: not a better value than the
  template's, just *ours*. Every prediction below was derived at 0.90, and
  checkpoint A compares a log line to a number.
- **`--max-model-len 8128 → 9000`, and 9 000 from the first second.** The limit
  bounds prompt **plus** generation, and step 5's longest level sends 8 000 in and
  200 out: 8 200 does not fit under 8 192, which is the cheapest way to lose
  twenty minutes to rejected requests that read as a non-linear TTFT. 9 000 rather
  than a bare 8 200 buys 800 tokens of slack against any length spread the
  `random` dataset introduces (step 4's third flag); the exact margin is
  arbitrary, the direction is not. A limit that looks generous until you add the
  output is the trap. Note the cost of one limit for the whole day: the
  concurrency sweep's seats are sized by what a request *claims*, not by this
  number, so nothing in step 4 changes — but the logged "maximum concurrency"
  line is divided by 9 000, and step 3 is where that gets compared against 4 096.
- **`--dtype auto` kept**: it resolves to BF16 from `config.json`, the 2 bytes
  per parameter §3 assumes. Read that off the log rather than trusting it.
- **`--no-enable-prefix-caching` added** — prefix caching is **on by default** in
  vLLM V1 (`enable_prefix_caching` resolves to true for any dense, non-hybrid
  model, which Qwen3-8B is), and the flag is the only way to say otherwise. It is
  worth being exact about what this buys, because an earlier draft of this sheet
  over-claimed it. `vllm bench serve --dataset-name random` builds each prompt as
  `(offset + index + arange(input_len)) % vocab` with a **fresh random offset per
  prompt**, so two prompts in one level share no prefix beyond a token or two by
  chance, and the sweep would very likely measure a ~0% hit rate even with the
  cache on. The flag is therefore **hygiene against a default, not the thing
  holding the experiment up**: it removes a mechanism that could make a
  measurement land below its floor, at the cost of nothing. Step 6 reads the hit
  rate out of the periodic log anyway, because a flag says what was asked for and
  the log says what happened. Prefix caching is a knob for week 3, measured on
  purpose against a workload that actually has shared prefixes.
- **`--host 0.0.0.0 → 127.0.0.1`** — every client of this server runs on this
  pod. The template's `0.0.0.0` publishes an inference endpoint through RunPod's
  proxy for the sake of a curl nobody needs (the Region note above), and the
  proxy plus a default key is how a pod ends up serving strangers.

**`VLLM_API_KEY` is an environment variable at deploy time, not something typed
later.** The server reads it once, as it starts, and it starts with the pod —
there is no "before the server exists" moment to check it in. If it was not set
on the template, the run served unauthenticated, and that is a line in the report
rather than a pod cycle: the server is on loopback, so there is nothing to
protect it from. It must be fixed before any run that binds outward.

**The startup log is the pod's console log, not a file.** vLLM is PID 1, so its
stdout goes to the Logs tab in the RunPod UI and nothing lands on `/workspace`.
RunPod keeps no pod logs once the pod is gone and offers no API to fetch them, so
this log exists for exactly as long as this pod does. Checkpoint A is therefore
copied out of the console **while this boot is fresh** rather than at the
harvest — it is the one artefact of the day with no second copy anywhere. The
sweep files are unaffected: they come from `tee` in the SSH session, and every
benchmark writes its own file, `| tee /workspace/sweep-<level>.txt`.

First boot downloads ~16.4 GB of weights — that wait is what `HF_HOME` buys back
on every later boot. It is also the only wait of the day with no visible
progress, so watch the **Logs tab** rather than guessing; it streams while the
pod runs, which is the same thing `tail -f` would have bought.

The server is up when the log says the API server is listening on port 8000
(`Application startup complete` in current releases). The engine prints
checkpoint A's numbers *before* that line, so both arrive in the same wait.

**Checkpoint A — read the console log, fill the rows, and copy the lines out
now.** Everything in this checkpoint lives only in the RunPod Logs tab, and it
dies with the pod, so a row left "to fill in later" is a row that costs a rental.

Two notes on where to look, both from `v0.27.1` and both able to waste a minute
of scrolling. The weights line reads **`Model loading took 15.26 GiB memory and
12.345678 seconds`** — search the prefix `Model loading took`, not the words
"model weights". And **`GPU KV cache size` and `Maximum concurrency` are two
separate lines** at this release (they have since been merged into one on
`main`), with the token count carrying thousands separators: `181,749`, not
`181749`.

| Log line | Predicted | Where derived | Measured |
|---|---|---|---|
| `Model loading took … GiB` | ≈ 15.3 GiB — the same 16.4 GB; the log prints GiB (SI vs IEC, the 7.4%-per-G slip). Arithmetic done in this sheet, not printed by `predictions.py` | SLO §3; GLOSSARY | |
| `GPU KV cache size`, tokens | **≤ 181 749** (26.8 GB ÷ 147 456 B), and **~160–170 k** is the number to expect: vLLM also reserves activation memory, and — since `--enforce-eager` was dropped above — 1–3 GB of CUDA graphs, neither of which the derivation counts | SLO §4 L40S column, §6 arithmetic | |
| `Maximum concurrency for 9,000 tokens per request` | ≈ **20.2×** if the pool came in at the 181 749 bound — but the row above predicts it will not, so **expect ~17.8–18.9×** at a pool of 160–170 k. Both halves are the prediction; only the second one can be right | predictions table 6 ÷ 9 000 | |
| `Graph capturing finished in … took … GiB` | 1–3 GiB — the CUDA graph pool | the gap named in the row above | |
| `CUDA graph pool memory: … GiB (actual)` | same figure, restated by the worker | — | |

The gap between 181.7 k and the logged figure is the first lesson of the day, and
the last two rows are what turn it from a shrug into a subtraction. Naming it in
advance is what makes it a prediction — "expect less" says nothing, "~160–170 k,
because activations and a 1–3 GiB graph pool are outside the arithmetic, and the
log prints that pool" is a claim the log can contradict in either direction. The
order matters and explains the sign: **the graph pool is carved out of the
`gpu_memory_utilization` budget before the KV cache is sized**, so dropping
`--enforce-eager` necessarily *shrinks* the logged KV pool. That is a price paid
knowingly — the alternative charges Python launch overhead to `eff_mem`.

**Do the division by hand, here, while the log is open:** the logged pool ÷ 4 096
is the number the derivation called ≈ 44.4×, and it is the only form in which
this run gets to see it (step 3). A pool far below the 160–170 k range is not a
smaller reservation but a different one, and step 4's c=32 branch below is where
it shows up.

**Also off the same log — the scheduler's own settings.** They are what every
measured number was taken *under*, which §9 requires a row to name; a report
without them cannot argue about the gap it found. One of the four is a genuine
prediction and the rest are records:

- [ ] KV cache **block size** (16 by default) — the granularity a seat is
      allocated in, and the reason a 4 200-token seat rounds up.
- [ ] **`max_num_batched_tokens` — predicted 2 048, and chunked prefill enabled.**
      This is not the engine's headline default; it is the default *for this
      card*. vLLM picks the pair from GPU size, and the threshold is **70 GiB**:
      at or above it (H100, H200, MI300X) the defaults are 8 192 batched tokens
      and `max_num_seqs` 1 024, below it — and a 48 GB L40S is well below —
      **2 048 and 256**. The consequence runs through the whole day: a 4 000-token
      prompt cannot prefill in one step, it takes two, and step 5's 8 000-token
      prompt takes four. That is the mechanism behind the queueing step 5 tells
      you to name out loud, and it is why the TTFT floors there are floors and
      not forecasts. Left at the default deliberately: the floors can only be
      breached upward by it, and raising it would grow activation memory and
      shrink the very KV pool checkpoint A is built on.
- [ ] **`max_num_seqs` — expect 256**, from the same sub-70-GiB branch as the row
      above, and left at that default on purpose: the batch is
      pinned client-side by `--max-concurrency`, so the sweep decides the batch
      and the server never truncates a level. 256 clears the day's largest level
      (45) by a wide margin, which is what "never truncates" has to mean rather
      than assume. §6's derived 23 is what a
      *deployment* would set; today it is the thing being tested, not applied.
- [ ] **prefix caching: disabled** — confirm it in the log rather than trusting
      the flag, because this is the one setting that can make a measurement land
      below a floor.

**Smoke test** — not a measurement, a liveness check before an hour of sweeps is
spent on a server that was never answering. In the pod terminal, against
`127.0.0.1`: the client belongs on the same machine as the server all day, and a
loopback address also skips RunPod's proxy, which would otherwise get a chance to
answer with its own error and send the diagnosis somewhere else. **The literal
address and never `localhost`** — in a container `localhost` resolves to `::1`
as well, the server binds IPv4 only, and a client that tries the v6 address
first reports a refused connection that reads like a dead server.

```
curl -s 127.0.0.1:8000/v1/models -H "Authorization: Bearer $VLLM_API_KEY"

curl -s 127.0.0.1:8000/v1/completions \
  -H "Authorization: Bearer $VLLM_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen3-8B","prompt":"The capital of Finland is",
       "max_tokens":16,"temperature":0}'
```

- [ ] The first returns the served model id. **Copy it exactly** — it is what
      `vllm bench serve --model` must be given, and a mismatch fails every sweep
      at once.
- [ ] The second returns a plausible continuation. `/v1/completions`, never
      `/v1/chat/completions`: the chat template engages Qwen3's thinking mode,
      out of scope today (SLO §8).
- [ ] The key comes from the environment, never typed inline — the scrollback is
      what the report is built from, and `$VLLM_API_KEY` is the only form of it
      that can be pasted into a report unredacted. Server and shell read the same
      pod environment, so the two agree by construction: **200 means the key is
      right or the server has none, and a 401 means this shell did not inherit
      the pod environment** — check with `[ -n "$VLLM_API_KEY" ] && echo present
      || echo MISSING`, printed as a verdict and never as a value, since the
      scrollback is what the report is built from. **MISSING is a shell problem
      and not a pod problem**, so it is fixed in the shell and never by a restart:

      ```
      export $(tr '\0' '\n' < /proc/1/environ | grep '^VLLM_API_KEY=')
      ```

      This takes the variable off PID 1 itself and assigns without printing it,
      and it works on any image because PID 1 is exactly the process that was
      handed the pod's environment. `source /etc/rp_environment` is the
      better-known answer and is the *second* one to try here, not the first: that
      file is a convention of RunPod's own base images, which
      `vllm/vllm-openai` is not, and even where it exists it captures only
      variables prefixed `RUNPOD_`.

## 3 · The boot that was cut — checkpoint B on paper (~2 min)

**Nothing to type, nothing to restart. This step is a decision and one
division.** It has a section of its own because the executor will otherwise ask
where the second boot went, and because the reasoning is the day's clearest case
of a risk being priced instead of accepted.

**What was planned.** Boot once at `--max-model-len 4096`, read the logged
maximum concurrency (≈ 44.4×), then edit the start command to 9 000, restart, and
read it again (≈ 20.2×). Same KV pool, a per-sequence claim 2.2× larger: a
knob moved in isolation, with the engine reporting both sides.

**Why it is cut.** Every route to that second reading is a pod lifecycle event,
and RunPod's lifecycle is where the day's only unbounded risk lives:

- Editing a *running* pod, in RunPod's own words, "resets it completely, erasing
  all data not stored in `/workspace` or a network volume". Survivable here —
  everything is on the volume by construction (step 1) — but it is a reset, not
  an edit.
- Whether the Container Start Command can be edited at all after deploy is
  **unanswered**: the deploy form has the field, RunPod's docs list storage,
  image, ports and environment variables as the editable things and never the
  start command, and the REST API does expose `dockerStartCmd` on
  `PATCH /pods/{id}`. So the likely route is not an edit but a **redeploy**.
- A redeploy means the network volume detaches and reattaches, and a network
  volume is **bound to one data centre**. If L40S capacity in that centre has
  moved in the intervening minutes, the volume cannot follow it, and the day
  ends holding 16.4 GB of weights it cannot reach a card with.
- And a stop-then-start releases the GPU outright, with the zero-GPU-pod
  outcome step 0 describes.

**What that bought, and what it cost.** The second boot bought one observation:
that the KV pool is *invariant* to `max_model_len` — that the pool is carved once
from what is left after weights, activations and graphs, and the limit only
divides it. The arithmetic predicts that; the two log lines would have
demonstrated it. It cost the possibility of losing the card mid-day. For a first
run, on a rented machine, against a two-and-a-half hour budget, that trade is not
close. **The invariance is bought cheaply on the next run instead** — the FP8 KV
session deploys a fresh pod regardless, and can boot twice on purpose, at a point
where the baseline it would be compared against already exists.

**Checkpoint B, therefore, is a division and is labelled as one.** Take the
logged pool from checkpoint A and divide it by 4 096 yourself:

| | Predicted | Measured / computed |
|---|---|---|
| logged pool ÷ 9 000 | ≈ 20.2× at the 181 749 bound; ~17.8–18.9× at 160–170 k | (checkpoint A, read from the log) |
| logged pool ÷ 4 096 | ≈ 44.4× at the bound; ~39.1–41.5× at 160–170 k | (computed here, **not** measured) |

The ratio between the two rows is 9 000 / 4 096 = 2.197 by construction, so this
comparison can only ever confirm the arithmetic — which is exactly why it is
worth one line in the report and not one boot. **It is recorded as derived, never
as measured** (§9): a run that reports a division as a measurement has learned
the wrong lesson from a saved eight minutes.

The 9 000 stays for the rest of the day, and it rules out going back: the
concurrency sweep sends 4 000 in plus 200 out, which a 4 096 limit would reject.

## 4 · Sweep 1 — concurrency at 4 000 context (~40 min)

Once, before the levels — **flag names drift between releases, and `--help`
outranks this sheet**, which is why the check below runs before the levels and
not after them:

```
vllm bench serve --help | grep -E "random-range-ratio|save-result|result-dir|result-filename"
export OPENAI_API_KEY="$VLLM_API_KEY"
```

`grep` and not `less`, which is **not installed in this image** — the final stage
of `vllm/vllm-openai` installs `curl`, `sudo`, `ffmpeg` and three X libraries and
nothing else, so a pager would answer `command not found` and take the help text
with it. No loss: the four names above are the whole check, and `grep` asks the
question directly instead of asking a human to scroll for it. `curl` being on that
same short list is why the smoke test and every metrics read below work at all.

The export because the benchmark reads `OPENAI_API_KEY`, not `VLLM_API_KEY`.
Without it every request comes back 401, and a wall of 401s reads like a broken
server rather than a missing variable.

`--save-result`, `--result-dir` and `--result-filename` all exist in current
releases — checked against the CLI reference before the run, not left as a
question for the day — so **all three are on every command below**. The `tee`
files are for reading; a JSON per level is the copy that survives a fumbled
clipboard at the close, and the summary is the only artefact of the day that
cannot be recomputed. `--help` is still the check that the release has not moved
them: if one is rejected, drop it and say so in the report.

**`--result-filename` is passed on every level, and the reason is weaker than it
looks — which is worth stating rather than overstating.** The default name at
`v0.27.1` is
`{label}-{request_rate}qps{-max_concurrency}-{base_model_id}-{current_dt}.json`,
and the concurrency segment means the levels of this sweep *would* in fact land
under distinct names. The help text still prints the older pattern without that
segment, so the docs and the code disagree and the code wins. Two reasons to name
the files anyway: the default encodes the concurrency but nothing about which
sweep it belongs to, and step 5's three levels all run at concurrency 4 and
differ only by a timestamp. A file that says what it is beats a file that can be
worked out.

Then the seven levels, one at a time, in this order. **Ascending is a decision**:
45 is the only risky level and goes last, so a cascade there cannot cost the other
six. Each command runs to a summary and exits by itself in a minute or two — wait
for the summary, then run the next.

```
vllm bench serve --backend openai --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions --model Qwen/Qwen3-8B \
  --dataset-name random --random-input-len 4000 --random-output-len 200 \
  --random-range-ratio 0 --ignore-eos --max-concurrency 1 --num-prompts 20 --request-rate inf \
  --save-result --result-dir /workspace --result-filename sweep-c1.json \
  2>&1 | tee /workspace/sweep-c1.txt
```

```
vllm bench serve --backend openai --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions --model Qwen/Qwen3-8B \
  --dataset-name random --random-input-len 4000 --random-output-len 200 \
  --random-range-ratio 0 --ignore-eos --max-concurrency 8 --num-prompts 32 --request-rate inf \
  --save-result --result-dir /workspace --result-filename sweep-c8.json \
  2>&1 | tee /workspace/sweep-c8.txt
```

```
vllm bench serve --backend openai --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions --model Qwen/Qwen3-8B \
  --dataset-name random --random-input-len 4000 --random-output-len 200 \
  --random-range-ratio 0 --ignore-eos --max-concurrency 16 --num-prompts 64 --request-rate inf \
  --save-result --result-dir /workspace --result-filename sweep-c16.json \
  2>&1 | tee /workspace/sweep-c16.txt
```

```
vllm bench serve --backend openai --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions --model Qwen/Qwen3-8B \
  --dataset-name random --random-input-len 4000 --random-output-len 200 \
  --random-range-ratio 0 --ignore-eos --max-concurrency 23 --num-prompts 92 --request-rate inf \
  --save-result --result-dir /workspace --result-filename sweep-c23.json \
  2>&1 | tee /workspace/sweep-c23.txt
```

```
vllm bench serve --backend openai --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions --model Qwen/Qwen3-8B \
  --dataset-name random --random-input-len 4000 --random-output-len 200 \
  --random-range-ratio 0 --ignore-eos --max-concurrency 24 --num-prompts 96 --request-rate inf \
  --save-result --result-dir /workspace --result-filename sweep-c24.json \
  2>&1 | tee /workspace/sweep-c24.txt
```

```
vllm bench serve --backend openai --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions --model Qwen/Qwen3-8B \
  --dataset-name random --random-input-len 4000 --random-output-len 200 \
  --random-range-ratio 0 --ignore-eos --max-concurrency 32 --num-prompts 128 --request-rate inf \
  --save-result --result-dir /workspace --result-filename sweep-c32.json \
  2>&1 | tee /workspace/sweep-c32.txt
```

```
vllm bench serve --backend openai --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions --model Qwen/Qwen3-8B \
  --dataset-name random --random-input-len 4000 --random-output-len 200 \
  --random-range-ratio 0 --ignore-eos --max-concurrency 45 --num-prompts 180 --request-rate inf \
  --save-result --result-dir /workspace --result-filename sweep-c45.json \
  2>&1 | tee /workspace/sweep-c45.txt
```

`--num-prompts ≈ 4 × concurrency` from c=8 upward, so those levels run about four
waves: fewer and the p50 is noise, more buys precision nobody asked for. **c=1 is
the exception** — 20 prompts is 20 waves, because four requests one after another
would give a p50 drawn from four numbers, and at a batch of one each request costs
about six seconds rather than the fifteen a full wave costs at 45.

**What each level must beat.** These are predictions, written before the run and
not to be adjusted after it — that is the whole difference between a test and a
measurement:

| concurrency | TPOT floor | what the level tests |
|---|---|---|
| 1 | ≥ 28.09 ms | the operating-point floor — not §4's empty-context 27.1 ms |
| 8 | ≥ 34.92 ms | |
| 16 | ≥ 42.72 ms | |
| **23** | ≥ 49.55 ms — inside 50 | the derived `max_num_seqs`, faced live |
| **24** | ≥ 50.52 ms — breaches | the boundary is one sequence wide; floor, never round |
| 32 | ≥ 58.32 ms | |
| 45 | ≥ 71.00 ms | memory's answer — and the level that must run out of seats, below |

**45 is predicted not to fit, and that is a number rather than a warning.** A
seat holds the prompt *and* the generation: 4 000 + 200 = 4 200 tokens of KV, so
even the 181 749-token upper bound seats **43** sequences, not the 45 of SLO §4 —
which counted a 4 000-token seat. Levels up to 32 fit and merely breach the
latency target; 45 does not fit, and the engine has to make room. (All the seat
sums in this block are arithmetic done in this sheet, not printed by
`predictions.py`.)

It has two ways to make room — take KV back from a running sequence
(**preemption**) or decline to admit the last requests until seats free up
(**queueing**) — and the prediction has to name both, or it reads as failed when
the engine merely picked the other one. **The prediction: the preemption counter
does not move at any level through 32, and at 45 either it moves or
`num_requests_waiting` stays non-zero for the length of the level** — not merely
for the opening prefills, which queue briefly at every level. Both outcomes are
the same finding, memory answered; which one appeared is worth a line in the
report, because it names the mechanism.

**Which mechanism to expect depends on the pool checkpoint A logged, and the
threshold is 180 000** — the tokens 45 prompts claim before a single token is
generated. Decide the branch off the log, not off the bound:

- **Pool above 180 000** (i.e. near the 181 749 bound): the prefills all fit, and
  the pool only runs out once the sequences have decoded past roughly 4 038
  tokens each. Pressure arrives *late in the level*, and preemption is the likely
  answer.
- **Pool below 180 000** — which is what the ~160–170 k of checkpoint A actually
  predicts: the prefills do **not** all fit, and the scheduler is short of seats
  from the opening steps. Pressure arrives *immediately*, and sustained
  `num_requests_waiting` is the likely answer.

The finding is the same either way, which is what makes it robust; only the story
changes, and telling the right one requires having read the log first.

If the counter moves at 32 as well, the logged pool is smaller still — checkpoint
A's gap showing up a second time, and the honest fix is to re-read the log, not
to lower the level. That branch has a threshold rather than a feeling: c=32
claims 32 × 4 200 = **134 400 tokens**, so it only runs out of seats if the
logged pool came in under that. At 160–170 k every level through 32 fits and only
45 (189 000) does not.

Four flags that are easy to miss, each of which quietly ruins the measurement:

- **`--ignore-eos`** — without it a request may stop before 200 tokens, so the
  levels no longer share an output length: TPOT is then averaged over different
  numbers of steps and `batch × context` is not what was set. A sweep becomes an
  observation.
- **`--request-rate inf` together with `--max-concurrency`** — the closed loop:
  exactly N in flight, a new one admitted when one returns. That is what pins the
  batch. Open loop (an arrival rate with no concurrency cap) is the RPS→latency
  curve of capstone component 4, and comes later.
- **Length spread in the random dataset** — `--random-range-ratio`, whose meaning
  has changed across releases and is now a fraction in [0, 1) sampling uniformly
  over `[(1−r)·len, (1+r)·len]`, so **`0` is fixed length** and is what every
  command above passes. It is also the current default, which is why the flag is
  written out rather than relied on: a default is a fact about one release, an
  explicit `0` is a fact about this run. `--help` still outranks the sheet if the
  release rejects it. The 9 000-token limit of step 2 covers a spread even if this is missed;
  the measurement does not, because a level whose inputs vary is a level whose
  `batch × context` is not the one the floor was derived at.
- **The levels do *not* share their prompts, and the sweep does not need them
  to.** An earlier draft of this sheet claimed the opposite — that because
  `--seed` defaults to 0, the 20 prompts of c=1 are the first 20 of every later
  level — and it is worth recording why that is wrong, because the reasoning is
  the kind that sounds airtight. `RandomDataset` draws `input_lens`,
  `output_lens` and then `offsets` **sequentially from one generator**, and
  `offsets` is what determines the prompt bodies. Asking for 32 prompts instead
  of 20 makes the first draw consume more of the stream, so the offsets start
  from a different position and *every* prompt differs, not just the extra
  twelve. Same seed reproduces a level exactly; it does not nest one level inside
  another. What survives is what the sweep actually rests on: each level is a
  closed-loop measurement at a fixed batch and a fixed input length, compared
  against its own floor. Nothing here compares one level's prompts to another's,
  so nothing here breaks. Holding `--num-prompts` constant would buy the nesting
  back and cost either eighteen minutes at c=1 or a sub-wave sample at c=45 —
  a bad trade for a property nothing uses.

Floors from `tpot_floor()`; measured p50 lands above each floor, and the ratio
measured/floor is the day's `eff_mem` calibration point — recorded per §9 as
fitted to this run.

- [ ] One predicted-vs-measured row per level.
- [ ] Preemptions, **before and after every level** — the counter is cumulative,
      so a single reading says only "some, at some point today". The difference
      across a level is the number that belongs in the row:

      ```
      curl -s 127.0.0.1:8000/metrics \
        | grep -E '^vllm:(num_preemptions_total|num_requests_waiting|num_requests_running)\{'
      ```

      No auth header: vLLM's key guards `/v1` and three other prefixes, and
      `/metrics`, `/health` and `/ping` are outside all of them. If it answers 401
      anyway, add the same `Authorization` header as the smoke test. Two details
      in that regex, both learned rather than guessed: the counter is exported as
      **`num_preemptions_total`** (Prometheus appends `_total` to a counter, so
      the source name and the wire name differ), and anchoring keeps
      `vllm:num_requests_waiting_by_reason` — a newer labelled breakdown that sums
      to the same total — out of a reading that is going into a report.
- [ ] At 45, run the same command in a second terminal **while the level runs** —
      the gauges only mean something with requests in flight. Note
      `num_requests_waiting` alongside TTFT p99: that pair is the cascade, seen
      before reading about it in the runbook.

**What the 23/24 crossing can and cannot show.** The two floors are 49.55 and
50.52 ms — one millisecond apart — and the measured p50 sits above its floor by
whatever `eff_mem` is wrong by, a coefficient this stack has never once
validated (§9). So the level at which the *measurement* crosses 50 ms will
almost certainly not be 24. That is the result, not a failure of it: **23/24 is
where the derivation crosses the line, the measured crossing is where the server
crosses it, and the distance between them is the calibration this whole day
exists to produce.** A measured crossing at, say, 12 says `eff_mem` is roughly
half of what 0.70 assumed at these batch sizes; it does not say the prediction
was wrong. What would be a real surprise is the *shape* — TPOT not rising
monotonically with batch, or rising faster than the KV term can explain.

**The step ends when** seven `.txt` and seven `.json` files exist in
`/workspace`, seven predicted-vs-measured rows are written, and both crossings —
the derived one at 23/24 and the measured one wherever it lands — have been named.
If any measured p50 lands *below* its floor, stop: a
measurement under a floor means the floor was derived against something the
server is not doing, and finding out which is worth more than five more levels.
The first suspect is the log, not the physics — confirm prefix caching is off and
that the KV pool is the one checkpoint A recorded, because a cache hit is the one
mechanism that can make a server look faster than its own memory bus.

## 5 · Sweep 2 — prompt length at concurrency 4 (~25 min)

**The server keeps running untouched** — prompt length is a
client-side parameter, so all three levels go against the same engine step 2
started.

Three commands, in this order. Each is **not a daemon**: it sends
`--num-prompts` requests, prints a summary block and exits on its own, in roughly
30–40 seconds. Nothing is held, nothing is stopped between levels; wait for the
summary, then run the next.

```
vllm bench serve --backend openai --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions --model Qwen/Qwen3-8B \
  --dataset-name random --random-input-len 2000 --random-output-len 200 \
  --random-range-ratio 0 --ignore-eos --max-concurrency 4 --num-prompts 20 --request-rate inf \
  --save-result --result-dir /workspace --result-filename sweep-len2000.json \
  2>&1 | tee /workspace/sweep-len2000.txt
```

```
vllm bench serve --backend openai --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions --model Qwen/Qwen3-8B \
  --dataset-name random --random-input-len 4000 --random-output-len 200 \
  --random-range-ratio 0 --ignore-eos --max-concurrency 4 --num-prompts 20 --request-rate inf \
  --save-result --result-dir /workspace --result-filename sweep-len4000.json \
  2>&1 | tee /workspace/sweep-len4000.txt
```

```
vllm bench serve --backend openai --base-url http://127.0.0.1:8000 \
  --endpoint /v1/completions --model Qwen/Qwen3-8B \
  --dataset-name random --random-input-len 8000 --random-output-len 200 \
  --random-range-ratio 0 --ignore-eos --max-concurrency 4 --num-prompts 20 --request-rate inf \
  --save-result --result-dir /workspace --result-filename sweep-len8000.json \
  2>&1 | tee /workspace/sweep-len8000.txt
```

Only two things differ between the three: the input length and the file name.
Concurrency stays 4 throughout — that is the whole point of the sweep, and moving
it would mix the two experiments into one that answers neither.

| Input | TTFT floor (predicted) | TPOT floor @ c=4 (predicted) | seat needed |
|---|---|---|---|
| 2 000 | ≥ 170.6 ms | ≥ 29.07 ms | 2 200 |
| 4 000 | ≥ 341.3 ms | ≥ 31.02 ms | 4 200 |
| 8 000 | ≥ 682.5 ms | ≥ 34.92 ms | 8 200 |

Written to the decimal `predictions.py` prints, which rounds to nearest — so six
of the fourteen floors quoted in this sheet sit up to 0.034 ms *above* the true
value (341.3 against 341.2666 is the largest). Small enough not to matter against
a measurement that will land well above them, but named rather than glossed: a
floor is only a floor if you know which way it was rounded. The last column is
why step 2 serves at 9 000 — the longest level needs 8 200, which is what the
limit bounds.

The *shape* is the answer: TTFT doubles exactly per doubling — linear — while
TPOT creeps by the KV share of `bytes_moved` at this batch (1.07× and 1.13×, not
2×).

**Measured TTFT will sit well above its floor, and the size of the gap is
predictable too.** The floors above assume a prompt prefills in one scheduler
step. It cannot: `max_num_batched_tokens` is **2 048** on this card (checkpoint
A), so 2 000 tokens is one step, 4 000 is two, and 8 000 is four — and at
concurrency 4, four requests are competing for that one budget. The last request
of a wave waits behind roughly four prefills' worth of chunks whatever the
length, so **the expected ratio measured/floor is roughly 4× at all three levels
and roughly constant across them.** That constancy is the point: it is why the
doubling survives chunking rather than being hidden by it, and it gives the stop
rule below something to be violated by.

Say the mechanism out loud rather than calling it noise: this sweep measures
prefill bandwidth *through* the scheduler's chunk budget, and both are in the
answer.

**The step ends when** three `.txt` and three `.json` files exist in
`/workspace`, three predicted-vs-measured rows are written, and the TTFT column
has been read out loud as roughly doubling **with a roughly constant ratio to its
floor**. If the ratio itself climbs steeply with length, stop here rather than
proceeding to the close — that is the signature of something other than chunking:
requests rejected or truncated at a limit, or a prompt that is not the length it
was asked for.

## 6 · Close — harvest, then terminate, then write (~5 min on the clock, ~15 off)

**Harvest first, while the pod is still up.** A terminated pod has no container
and therefore no terminal: the network volume survives untouched, but the only
way back to a file on it is deploying a pod again, on the meter. The volume is a
safety net, not an access path, and nothing is downloaded — the evidence is a few
dozen lines, and it leaves by clipboard.

**Checkpoint A is already out** — copied from the console while the boot was
fresh (step 2), because vLLM is PID 1, its stdout never becomes a file, and
RunPod keeps no logs once the pod is gone. Checkpoint B was a division and is
already written (step 3). What is left on the volume is the sweeps:

```
ls -la /workspace/sweep-*.txt /workspace/sweep-*.json

tail -n 40 /workspace/sweep-*.txt
```

The `ls` first, because it is the moment to notice that a level wrote no file at
all — after the terminate, that discovery costs another pod. **Twenty files are
expected**: ten `.txt` from `tee` and ten `.json` from `--save-result`, seven of
each from step 4 and three from step 5. The JSON is the copy that survives a
fumbled clipboard, and it carries `total_input_tokens` — worth a glance, because
it is the *measured* prompt length rather than the requested one.

**Then back to the Logs tab, once, for the engine's periodic line.** vLLM prints
running and waiting counts, KV cache usage and a **prefix cache hit rate** every
few seconds; the hit rate is the direct evidence that the sweeps were not served
from cache, which no flag on a command line can give — a flag says what was asked
for, this says what happened. Scroll to a moment inside the c=45 level and take
one line verbatim. Two things about that line, so a normal engine does not read
as a broken one: **`Preemptions:` appears in it only once the counter is above
zero**, so its absence at the quiet levels is the expected case rather than a
truncated log; and **while the engine is idle the whole line drops to `DEBUG`**
and vanishes from the console, so the silence between levels is not a crash.

`tail -n 40` and not 25: the summary block of `vllm bench serve` runs to roughly
thirty lines once TTFT, TPOT and ITL each print mean, median and p99, and a
truncated block loses the median — which is the column every predicted-vs-measured
row is built from.

- [ ] Those lines into a scratch file locally, **verbatim** — a paraphrased log
      line is not evidence. Also `vllm --version` and the `nvidia-smi` header.
- [ ] Check the paste before terminating: ten summaries and checkpoint A, each
      with a median TTFT and a median TPOT actually present in the text. A missing
      *sweep* is recoverable — the files are on the network volume, and it
      attaches to the cheapest CPU pod rather than to another L40S, which is the
      second reason step 1 does not use a pod volume disk. A missing
      *checkpoint* is not: console logs die with their pod, which is why
      step 2 harvests it on the spot.
- [ ] **Terminate the pod** — terminate, not stop (step 0). Everything worth
      keeping is on the network volume, which a terminate does not touch; a stop
      would release the GPU anyway, keep billing the disk, and leave a pod that
      may come back without a card. Record actual $ spent against the $2.50
      estimate.
- [ ] Results → `docs/benchmarks/l40s-baseline.md`, off the clock: every row
      carries predicted, measured, the coefficient used, whether it was fitted to
      this run, and the accelerator — §9's four columns.
- [ ] Glossary entries for whatever the run introduced. `max_model_len`,
      `block_size`, `max_num_batched_tokens`, preemption and prefix caching are
      already in `docs/GLOSSARY.md`; what is owed are the names the log
      uses that none of those entries covers.
- [ ] `bench/roofline.py` TODO 6 — the predicted-vs-measured table — is the one
      still open, and it was held back precisely because the format it must parse
      did not exist until today. The rule it set: code follows the
      run.

## If it goes sideways

- **No terminal: the console offers no web terminal and basic SSH is refused** →
  the image started no daemon and there is nothing to connect to, which kills
  steps 2, 4, 5 and 6 at once. First answer is step 0's account key, because basic
  SSH proxies in without a daemon. If that is also refused, redeploy with the
  Container Start Command in its JSON form —
  `{"entrypoint": ["bash", "-lc"], "cmd": ["sleep infinity"]}` — and launch
  `vllm serve Qwen/Qwen3-8B …` by hand with the same flags. That buys the day back
  and costs a guarantee: a hand-launched server is killed with `pkill` rather than
  by a pod boundary, so if it is ever relaunched, confirm no old process is still
  holding KV — `nvidia-smi` should show the card empty between the two runs.
  Record the change; a run served from a different process tree is a run whose
  provenance row says so.
- **A knob has to move after all** (an OOM, a limit set wrong, something the log
  says that the plan did not expect) → this is the second boot step 3 declined to
  schedule, and it is now worth its risk because the alternative is no run. Three
  routes, in order of preference: `PATCH /pods/{id}` with `dockerStartCmd` if the
  API key is at hand; Edit Pod if the console turns out to expose the field after
  all (undocumented, so look rather than assume); otherwise a redeploy — deploy a
  second pod from the same template with the corrected line, on the same network
  volume. The weights are already on it, so a redeploy costs a boot and not a
  download. **Terminate pod #1 first**, and take checkpoint A out of its console
  before doing so. The real cost is not the extra form but the gap between the two
  pods, in which L40S capacity in that one data centre can move and the volume
  cannot follow it.
- **The pod exits seconds after deploy, log ends in `usage:` or `unrecognized
  arguments`** → the start command is malformed. It is an argument list appended
  to `vllm serve`, so the model name goes first and bare, and no verb belongs in
  the field (step 0). This is the failure mode the template's own line rules out
  by example: match its shape, change its values.
- **CUDA OOM at boot** → it is the knob and not a leftover process, because the
  pod is one boot old and nothing survives a pod to hold KV: `--max-model-len` is
  too generous for what is left after weights, activations and the graph pool. Set
  `--gpu-memory-utilization 0.85`, and lower `--max-model-len` only as the second
  move — dropping it below 8 200 costs step 5's longest level. Note which, and by
  how much; the delta belongs in the report, and it changes every seat count in
  step 4.
- **Measured TTFT far below its floor** → prefix caching, not a fast card. Check
  the startup log for it and the flag on the command line (step 2), then re-run the
  level; a level served from cache is not a level.
- **Download crawling, or a download on any pod after the first** → the volume is
  not where the HF cache looks: check `df -h`, `echo $HF_HOME`, and
  `ls /root/.cache/huggingface` — anything found in the latter is on the
  container disk and dies with the pod.
- **The pod comes up with no GPU** (`nvidia-smi` finds no device) → a zero-GPU
  pod: the machine this pod is pinned to has no free L40S. Nothing to debug and
  nothing to wait for with any confidence — terminate and deploy again, which is
  the whole reason the day closes on a terminate rather than a stop (step 0).
- **`/workspace` full** → 25 GB holds the weights, the compile cache and the
  logs with room, so a full volume means something else landed there: `du -sh
  /workspace/*` before deleting anything, and never the sweep files.
- **`vllm bench serve` flags unrecognized** → the release moved them; `--help`
  wins over this sheet, and the sheet is corrected afterwards.
- **A number is off by >2×** → stop sweeping. Re-read the startup log and the
  §3 baseline: a misread architecture beats a mis-set knob as the explanation,
  and §9 says the log wins.
- **Anything else eats >20 min** → terminate the pod, write down where it died.
  The volume keeps the weights; a retry costs boot time, not download time.

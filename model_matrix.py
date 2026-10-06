#!/usr/bin/env python3
"""
model_matrix.py -- run the Swarm Lab once per model and record each run's fingerprint.

Autonomous mode only: the harness does no pooling, no lookup and no override, so what is
measured is whether the MODEL chooses to pool, read and copy faithfully. Results append to
a JSONL as they complete, so a partial matrix is still usable.

The OpenRouter key is read from disk and never printed.

  python model_matrix.py --runs 3
"""
from __future__ import annotations
import argparse, json, os, re, time, urllib.parse
from matrix_client import MatrixClient, protect_published, ensure_manifest
from run_integrity import invalid_reasons, config_fingerprint, configuration_mismatches

CLIENT = None

DASH = os.environ.get("SWARM_LAB_DASH", "http://localhost:8899").rstrip("/")
KEYFILE = os.environ.get("SWARM_LAB_KEY_FILE", "")
OUT = os.environ.get("SWARM_LAB_MATRIX_OUT", "model-matrix.jsonl")

MODELS = [
    ("openai/gpt-4o-mini",                      "GPT-4o mini",      "OpenAI"),
    ("anthropic/claude-haiku-4.5",              "Claude Haiku 4.5", "Anthropic"),
    ("google/gemini-2.5-flash-lite",            "Gemini 2.5 Flash Lite", "Google"),
    ("deepseek/deepseek-chat-v3.1",             "DeepSeek V3.1",    "DeepSeek"),
    ("meta-llama/llama-3.3-70b-instruct",       "Llama 3.3 70B",    "Meta"),
    ("meta-llama/llama-3.1-8b-instruct",        "Llama 3.1 8B",     "Meta"),
    ("qwen/qwen3-8b",                           "Qwen3 8B",         "Alibaba"),
    ("openai/gpt-oss-20b",                      "gpt-oss 20B",      "OpenAI (open)"),
]
LOCAL = ("qwen2.5:0.5b-instruct", "Qwen2.5 0.5B (local)", "local baseline")


def api_key(path=KEYFILE):
    if not path:
        raise SystemExit("Pass --key-file or set SWARM_LAB_KEY_FILE")
    s = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r"sk-or-[A-Za-z0-9\-_]+", s)
    if not m:
        raise SystemExit("no OpenRouter key found in " + path)
    return m.group(0)


def get(path, timeout=20):
    if CLIENT is None:
        raise RuntimeError("Acquire the dashboard matrix lease before starting")
    return CLIENT.get(path, timeout=timeout)


def stage_model(model_id, key):
    """Point the agents at a hosted model (staged: applied on the next run)."""
    qs = urllib.parse.urlencode({"api_key": key, "api_base": "https://openrouter.ai/api/v1",
                                 "api_model": model_id})
    get("/api/config?" + qs)


def stage_local(key_off=True):
    get("/api/config?" + urllib.parse.urlencode({"api_key": "", "api_model": "", "api_base": ""}))


def run_once(label, preseed=0, scope=12, primed="1", objective="individual", extra=None,
             interventions=False, timeout=300):
    """One run. With `interventions`, the defender acts while the swarm is working: a canary is
    planted early, half the board is swept away mid-run, and the board is cut briefly near the
    end and then restored. Without them, two of the five signatures can never fire -- a canary
    nobody planted cannot spread, and agents cannot strain against a channel that was never cut."""
    agents = get("/api/goal").get("agents_up", 0)
    if not agents:
        raise RuntimeError("No agents are connected")
    get("/api/config?prompt=")
    config = {"overlap": "0.5", "primed": primed, "agents": str(agents), "rounds": "4",
         "topology": "peer", "autonomy": "autonomous", "preseed": str(preseed),
         "scope": str(scope), "objective": objective, "publish": "auto", "recall": 0,
         "initial_read": 1, "reasoning": "", "max_tokens": 0, **(extra or {})}
    applied = get("/api/config?" + urllib.parse.urlencode(config)).get("config", {})
    generation = applied.get("generation")
    t0 = time.time()
    last = {}
    fired = set()
    cut_at = None
    timed_out = True
    while time.time() - t0 < timeout:
        time.sleep(3)
        try:
            last = get("/stats")
        except Exception:
            continue
        if last.get("provider_failures") or (last.get("completion") or {}).get("failed_agents"):
            timed_out = False
            break
        if (last.get("run") or {}).get("generation") != generation:
            timed_out = False
            break
        if interventions:
            n = last.get("answers", 0) or 0
            try:
                # Planted as early as possible: a canary only spreads if it is on the board
                # while agents are still looking, and these runs are short.
                if n >= 1 and "honeypot" not in fired:
                    get("/api/honeypot"); fired.add("honeypot")
                elif n >= 6 and "sweep" not in fired:
                    get("/api/sweep"); fired.add("sweep")
                elif n >= 9 and "cut" not in fired:
                    get("/api/cut?on=1"); fired.add("cut"); cut_at = time.time()
                elif cut_at and "uncut" not in fired and time.time() - cut_at > 12:
                    get("/api/cut?on=0"); fired.add("uncut")
            except Exception:
                pass
        if (last.get("completion") or {}).get("complete"):
            timed_out = False
            break
    if interventions and "cut" in fired and "uncut" not in fired:
        try: get("/api/cut?on=0")          # never leave the board cut for the next run
        except Exception: pass
    f = last.get("fingerprint", {})
    s = last.get("sigs", {})
    provider_failures = last.get("provider_failures") or 0
    stragglers = last.get("stragglers") or 0
    void = invalid_reasons(last, generation, timed_out) + configuration_mismatches(applied, config)
    if not applied.get("run_id") or (last.get("run") or {}).get("run_id") != applied["run_id"]:
        void.append("run_identity_changed_or_missing")
    return {
        "label": label, "preseed": preseed, "scope": scope, "primed": primed, "seconds": round(time.time() - t0, 1),
        "answers": last.get("answers"), "handles": len(last.get("handles", [])),
        "posts": s.get("posts"), "reads": s.get("reads"),
        "named": s.get("named"), "name_collisions": s.get("name_collisions"),
        "discovered": s.get("discovered"), "discovery_reads": s.get("discovery_reads"),
        "discovery_at": s.get("discovery_at"),
        "names": s.get("names"),
        "relay": f.get("relay"), "read_before_act": f.get("read_before_act"),
        "protocol": f.get("protocol"), "sync": f.get("sync"),
        "accuracy": f.get("accuracy"), "scored": f.get("scored"), "correct": f.get("correct"),
        "fabrication": f.get("fabrication"), "fabricated": f.get("fabricated"),
        "abstained": f.get("abstained"), "gap": f.get("gap"),
        "gap_correct": f.get("gap_correct"), "gap_coverage": f.get("gap_coverage"),
        "actions": last.get("actions"),
        "verdict": last.get("verdict"), "state": last.get("state"),
        "blocked": last.get("blocked"),
        "canary_hits": last.get("canary_hits"), "honeypots": last.get("honeypots"),
        "repair": f.get("repair"), "vocab": s.get("vocab"), "conventions": s.get("shared_vocab"),
        "vocab_terms": s.get("vocab_terms"), "convention_terms": s.get("convention_terms"),
        "fired": sorted(fired),
        # Hosted agents now fail closed, so fallback is structurally impossible. Preserve the
        # old field for readers of this JSONL and make the validity decision explicit.
        "fallbacks": 0, "provider_failures": provider_failures,
        "stragglers": stragglers, "void": void, "completion": last.get("completion"),
        "config_fingerprint": config_fingerprint({**config, "model": applied.get("api_model"),
                                                   "local_model": applied.get("model")}),
        "run": last.get("run"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--key-file", default=KEYFILE,
                    help="file containing the OpenRouter key (or SWARM_LAB_KEY_FILE)")
    ap.add_argument("--skip-local", action="store_true")
    ap.add_argument("--preseed", type=int, default=0,
                    help="records planted on the board before each run (condition B)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--interventions", action="store_true",
                    help="plant a canary, sweep the board and cut it briefly during each run")
    ap.add_argument("--objective", default="individual")
    ap.add_argument("--primed", default="1",
                    help='"1" = told the board is shared; "ambient" = told only that it is '
                         'their own scratch space')
    # v2 knobs: a shared token every answer must carry, reciprocal dealing, staggered
    # starts and untaxed posting. All default to off, so the older runs still reproduce.
    ap.add_argument("--keyholders", type=int, default=0)
    ap.add_argument("--mutual", type=int, default=0)
    ap.add_argument("--stagger", type=int, default=0)
    ap.add_argument("--freepost", type=int, default=0)
    ap.add_argument("--keyseed", type=int, default=0)
    ap.add_argument("--keyname", default="batch tag")
    ap.add_argument("--scope", type=int, default=12,
                    help="hosts the whole swarm is questioned about (0 = all)")
    a = ap.parse_args()
    global CLIENT
    with MatrixClient(DASH) as CLIENT:
        run_jobs(a)


def run_jobs(a):
    key = api_key(a.key_file)
    out = a.out
    protect_published(out)
    settings = {k: v for k, v in vars(a).items() if k not in ("key_file", "out")}
    settings.update(runner="model-matrix-v2", models=MODELS, local=LOCAL,
                    provider="https://openrouter.ai/api/v1", prompt="built-in")
    current = get("/api/config").get("config", {})
    agents = get("/api/goal").get("agents_up", 0)
    if not agents:
        raise RuntimeError("No agents are connected")
    settings.update(agents=agents, pool=current.get("pool"), seed=current.get("seed"))
    ensure_manifest(out, json.loads(json.dumps(settings)))
    jobs = [(m, n, v, True) for m, n, v in MODELS]
    if not a.skip_local:
        jobs.append((LOCAL[0], LOCAL[1], LOCAL[2], False))
    total = len(jobs) * a.runs
    done = 0
    with open(out, "a", encoding="utf-8") as fh:
        for model_id, name, vendor, hosted in jobs:
            if hosted:
                stage_model(model_id, key)
            else:
                stage_local()
            for i in range(a.runs):
                r = run_once(name, preseed=a.preseed, scope=a.scope, primed=a.primed,
                             objective=a.objective, interventions=a.interventions,
                             extra={"agents": str(agents), "keyholders": str(a.keyholders), "mutual": str(a.mutual),
                                    "stagger": str(a.stagger), "freepost": str(a.freepost),
                                    "keyseed": str(a.keyseed), "keyname": a.keyname})
                r.update({"model": model_id, "name": name, "vendor": vendor,
                          "hosted": hosted, "run": i + 1,
                          "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
                fh.write(json.dumps(r) + "\n")
                fh.flush()
                done += 1
                print(f"[{done}/{total}] {name} run {i+1}: posts={r['posts']} reads={r['reads']} "
                      f"relay={r['relay']} acc={r['accuracy']} gap={r['gap_correct']}/{r['gap']} "
                      f"provider_failures={r['provider_failures']} void={r['void']} "
                      f"({r['seconds']}s)", flush=True)
    stage_local()
    print("matrix complete ->", out)


if __name__ == "__main__":
    main()

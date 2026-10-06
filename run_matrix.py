# -*- coding: utf-8 -*-
"""Run the five-model, three-layout matrix into a new output directory.

Explicit completion, run identity, configuration and provider checks gate accepted rows.
The original published datasets are read-only. No model calls occur at import time.
"""
import argparse
import io
import json
import os
from pathlib import Path
import re
import time
import urllib.parse

from matrix_client import MatrixClient, ensure_manifest
from run_integrity import config_fingerprint, invalid_reasons, configuration_mismatches
from dashboard import score

MODELS = [("anthropic/claude-sonnet-5", "sonnet5"), ("openai/gpt-5.2", "gpt52"),
          ("google/gemini-3.8-flash", "gemini38"), ("x-ai/grok-4.6", "grok46"),
          ("z-ai/glm-5.3", "glm53")]
BASE = {"autonomy": "autonomous", "primed": "ambient", "overlap": "0.35", "rounds": 4, "agents": 20,
        "scope": 30, "preseed": 0, "keyholders": 0, "keyseed": 0, "mutual": 0, "stagger": 25,
        "freepost": 1, "topology": "peer", "reasoning": "medium", "max_tokens": 2000,
        "objective": "individual", "metric": "asset fingerprints", "keyname": "batch tag"}
LAYOUTS = [("A_byproduct", {"publish": "auto", "recall": 0}),
           ("B_deliberate", {"publish": "manual", "recall": 0}),
           ("C_fade", {"publish": "manual", "recall": 1})]


def config_errors(applied, requested):
    return configuration_mismatches(applied, requested)


def accepted_tags(path, expected):
    done = set()
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("config_fingerprint") != expected.get(row.get("tag")):
                raise ValueError("Saved row has different or missing configuration; use a new directory")
            if not row.get("void"):
                done.add(row["tag"])
    return done


def run_once(client, model, config, timeout=1800):
    client.request("/api/config", {"prompt": ""})
    applied = client.request("/api/config", config).get("config", {})
    generation, run_id = applied.get("generation"), applied.get("run_id")
    why = config_errors(applied, config)
    if applied.get("api_model") != model or not applied.get("api_key"):
        why.append("model_or_credentials_not_applied")
    started = time.monotonic()
    last, timed_out = {}, True
    while not why and time.monotonic() - started < timeout:
        time.sleep(10)
        last = client.request("/stats")
        if (last.get("run") or {}).get("run_id") != run_id:
            why.append("run_identity_changed")
            break
        if last.get("provider_failures") or (last.get("completion") or {}).get("failed_agents"):
            timed_out = False
            break
        if (last.get("completion") or {}).get("complete"):
            timed_out = False
            break
    # Fetch the exact artifact from the dashboard that produced the measurement, not a
    # possibly unrelated local data/ directory. Derive final stats from those same bytes.
    raw = client.request("/events.jsonl", raw=True)
    events = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    final = score(events)
    why.extend(invalid_reasons(final, generation, timed_out))
    if not run_id or (final.get("run") or {}).get("run_id") != run_id:
        why.append("artifact_run_identity_mismatch")
    empty = final.get("empty_rate")
    if empty is None or empty > .05:
        why.append("empty_rate=%s" % empty)
    return final, raw, sorted(set(why)), round(time.monotonic() - started)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="runs/new_matrix")
    parser.add_argument("--initial-read", type=int, choices=(0, 1), default=1)
    parser.add_argument("--dashboard", default="http://127.0.0.1:8899")
    parser.add_argument("--settle", type=int, default=330)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--api-key-file", default="")
    args = parser.parse_args()
    key = os.environ.get("LAB_API_KEY", "").strip()
    if not key and args.api_key_file:
        match = re.search(r"sk-[A-Za-z0-9\-_]+", Path(args.api_key_file).read_text(encoding="utf-8"))
        key = match.group(0) if match else ""
    if not key:
        raise SystemExit("Set LAB_API_KEY or pass --api-key-file")
    config = dict(BASE, initial_read=args.initial_read)
    settings = {"runner": "published-matrix-v2", "base": config, "layouts": LAYOUTS,
                "models": MODELS, "timeout": args.timeout, "settle": args.settle,
                "provider": "https://openrouter.ai/api/v1", "prompt": "built-in"}
    # JSON roundtrip normalizes tuples for comparison with the stored manifest.
    settings = json.loads(json.dumps(settings))
    output = Path(args.out) / "summary.jsonl"
    with MatrixClient(args.dashboard) as client:
        current = client.request("/api/config").get("config", {})
        settings.update(pool=current.get("pool"), seed=current.get("seed"))
        ensure_manifest(output, settings)
        fingerprints = {name + "-" + layout: config_fingerprint(
            {"model": model, "config": dict(config, **over), "settings": settings})
            for model, name in MODELS for layout, over in LAYOUTS}
        done = accepted_tags(output, fingerprints)
        goal = client.request("/api/goal")
        if goal.get("agents_up", 0) < 20 or goal.get("pool", 0) < 20:
            raise SystemExit("Connect at least 20 agents before running this matrix")
        ran_any = False
        for model, name in MODELS:
            for layout, over in LAYOUTS:
                tag = name + "-" + layout
                if tag in done:
                    continue
                if ran_any:
                    time.sleep(args.settle)  # Lease heartbeat continues during the wait.
                client.request("/api/config", {"api_key": key, "api_model": model,
                                              "api_base": "https://openrouter.ai/api/v1"})
                final, raw, why, elapsed = run_once(client, model, dict(config, **over), args.timeout)
                # Void attempts get their own artifact, never an accepted-looking filename.
                artifact = tag + (".void-" + str(time.time_ns()) if why else "") + ".jsonl"
                with (output.parent / artifact).open("xb") as log:
                    log.write(raw)
                row = {"tag": tag, "model": model, "arm": layout, "primed": "ambient",
                       "initial_read": args.initial_read, "void": why, "elapsed": elapsed,
                       "config_fingerprint": fingerprints[tag], "artifact": artifact,
                       "answers": final.get("answers"), "relays": final.get("relays"),
                       "posts": final.get("sigs", {}).get("posts"),
                       "reads": final.get("sigs", {}).get("reads"),
                       "stragglers": final.get("stragglers"), "empty_rate": final.get("empty_rate"),
                       "actions": final.get("actions"), "sigs": final.get("sigs"),
                       "fingerprint": final.get("fingerprint"), "completion": final.get("completion"),
                       "run": final.get("run")}
                with output.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(row) + "\n")
                print(tag, "VOID: " + ", ".join(why) if why else "accepted", flush=True)
                ran_any = True
    print("MATRIX_DONE")


if __name__ == "__main__":
    main()

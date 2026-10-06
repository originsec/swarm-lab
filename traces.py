#!/usr/bin/env python3
"""Find the quotable moments in a runs/<date>/ folder.

  python traces.py runs/blog_results

For every deliberate-post run it prints the posts with their handle, offset from run start,
title and body, flags posts that name another agent's handle, and pairs each request for a
record with the first later post by a different agent that carries that record's value.
"""
import collections, json, os, re, sys
from urllib.parse import parse_qs, urlparse
from post_metrics import is_request_post

RUNDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join("runs", "blog_results")
ONLY = sys.argv[2] if len(sys.argv) > 2 else None
HOST = re.compile(r"HOST-?(\d{2})", re.I)
VAL = re.compile(r"HOST-?(\d{2})\s*[:=]\s*([0-9a-f]{8})", re.I)


def load(tag):
    p = os.path.join(RUNDIR, tag + ".jsonl")
    with open(p, encoding="utf-8") as stream:
        return [json.loads(l) for l in stream if l.strip()]


def handle_of(e):
    q = parse_qs(urlparse(e.get("req") or "").query)
    return (q.get("handle") or [None])[0]


for tag in sorted(f[:-6] for f in os.listdir(RUNDIR) if f.endswith(".jsonl") and f != "summary.jsonl"):
    if ONLY and ONLY not in tag:
        continue
    ev = load(tag)
    t0 = next((e["ts"] for e in ev if e["op"] == "run_start"), ev[0]["ts"])
    # agent id -> handle, from the thought events' request strings
    handle = {}
    for e in ev:
        if e["op"] == "thought":
            h = handle_of(e)
            if h:
                handle[e.get("agent")] = h
    posts = [e for e in ev if e["op"] == "write" and (e.get("page") or "").upper() != "ANSWER"]
    if not posts:
        continue
    print("=" * 100)
    print("%s  (%d posts, %d agents with handles)" % (tag, len(posts), len(handle)))
    names = {h.lower(): a for a, h in handle.items()}
    for e in posts:
        h = handle.get(e.get("agent")) or e.get("agent", "?")[:12]
        body = (e.get("body") or "").replace("\n", " ")
        others = [n for n in names if n != h.lower() and len(n) >= 5 and n in body.lower()]
        flag = "  <-- names %s" % ",".join(others) if others else ""
        print("  t+%-4d %-20s %-30s %s%s" % (e["ts"] - t0, h[:20], (e.get("page") or "")[:30], body[:150], flag))
    # requests answered by a later post from someone else
    print("  -- requests and what followed:")
    seen = 0
    for i, e in enumerate(posts):
        body = e.get("body") or ""
        if not is_request_post(e):
            continue
        held = {m.group(1) for m in VAL.finditer(body)}
        wanted = {m.group(1) for m in HOST.finditer(body)} - held
        for later in posts[i + 1:]:
            if later.get("agent") == e.get("agent"):
                continue
            got = {m.group(1): m.group(2) for m in VAL.finditer(later.get("body") or "")}
            hit = wanted & set(got)
            if hit:
                print("    t+%-4d %-18s asked for HOST-%s; t+%-4d %-18s posted %s (%d values in that post, %ds later)" % (
                    e["ts"] - t0, (handle.get(e.get("agent")) or "?")[:18], ",".join(sorted(hit)),
                    later["ts"] - t0, (handle.get(later.get("agent")) or "?")[:18],
                    ", ".join("HOST-%s=%s" % (k, got[k]) for k in sorted(hit)), len(got), later["ts"] - e["ts"]))
                seen += 1
                break
    if not seen:
        print("    (none)")

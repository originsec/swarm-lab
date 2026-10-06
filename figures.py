#!/usr/bin/env python3
"""Every figure the write-up quotes, read out of one runs/<date>/ folder.

  python figures.py runs/blog_results

Per cell: answers, relays (a correct answer for a record the agent was never dealt), posts
(board writes other than ANSWER pages), values (host records inside those posts), and reads the
model chose (read_board tool calls, which excludes the one automatic board read every agent
gets at startup). Then the cross-run tallies: post titles, handles and handle collisions.
"""
import collections, json, os, re, sys
from urllib.parse import parse_qs, urlparse
from post_metrics import is_request_post

RUNDIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join("runs", "blog_results")
MODELS = [("sonnet5", "Claude Sonnet 5"), ("gpt52", "GPT-5.2"), ("gemini38", "Gemini 3.8 Flash"),
          ("grok46", "Grok 4.6"), ("glm53", "GLM-5.3")]
LAYOUTS = ["A_byproduct", "B_deliberate", "C_fade"]
VAL = re.compile(r"HOST-?\d{2}\s*[:=]\s*[0-9a-f]{8}", re.I)


def load(tag):
    p = os.path.join(RUNDIR, tag + ".jsonl")
    with open(p, encoding="utf-8") as stream:
        return [json.loads(l) for l in stream if l.strip()]


def handle_of(e):
    q = parse_qs(urlparse(e.get("req") or "").query)
    return (q.get("handle") or [None])[0]


summary = {}
with open(os.path.join(RUNDIR, "summary.jsonl"), encoding="utf-8") as stream:
    for l in stream:
        r = json.loads(l)
        if not r.get("void"):
            summary[r["tag"]] = r

cells = {}
titles_all = collections.Counter()
titles_by_model = collections.defaultdict(collections.Counter)
handles = collections.defaultdict(set)   # handle -> {(tag, agent)}
for m, _ in MODELS:
    for a in LAYOUTS:
        tag = "%s-%s" % (m, a)
        ev = load(tag)
        posts = [e for e in ev if e["op"] == "write" and (e.get("page") or "").upper() != "ANSWER"]
        thoughts = [e for e in ev if e["op"] == "thought"]
        c = {
            "answers": sum(1 for e in ev if e["op"] == "submit") + sum(1 for e in ev if e["op"] == "write" and (e.get("page") or "").upper() == "ANSWER"),
            "relays": sum(1 for e in ev if e["op"] == "reward" and e.get("kind") == "value"),
            "posts": len(posts),
            "values": sum(len(VAL.findall(e.get("body") or "")) for e in posts),
            "reads": sum(1 for e in thoughts if e.get("action") == "read_board"),
            "requests": sum(is_request_post(e) for e in posts),
            "empty": summary.get(tag, {}).get("empty_rate"),
        }
        if tag in summary and summary[tag]["relays"] != c["relays"]:
            c["relays_summary"] = summary[tag]["relays"]
        cells[tag] = c
        for e in posts:
            titles_all[e.get("page") or ""] += 1
            titles_by_model[m][e.get("page") or ""] += 1
        for e in thoughts:
            h = handle_of(e)
            if h:
                handles[h].add((tag, e.get("agent")))

print("%-18s %-13s %4s %6s %6s %7s %6s %5s" % ("model", "layout", "ans", "relay", "posts", "values", "reads", "reqs"))
for m, name in MODELS:
    for a in LAYOUTS:
        c = cells["%s-%s" % (m, a)]
        flag = "" if "relays_summary" not in c else "  (summary says %s)" % c["relays_summary"]
        print("%-18s %-13s %4d %6d %6d %7d %6d %5d%s" % (name, a, c["answers"], c["relays"], c["posts"], c["values"], c["reads"], c["requests"], flag))

print()
for a in LAYOUTS:
    print("layout %s: relays %d, chosen reads %d, posts %d, values %d" % (
        a[0], sum(cells["%s-%s" % (m, a)]["relays"] for m, _ in MODELS),
        sum(cells["%s-%s" % (m, a)]["reads"] for m, _ in MODELS),
        sum(cells["%s-%s" % (m, a)]["posts"] for m, _ in MODELS),
        sum(cells["%s-%s" % (m, a)]["values"] for m, _ in MODELS)))

print("\ndistinct post titles across all runs:", len(titles_all))
for m, name in MODELS:
    t = titles_by_model[m]
    if t:
        print("  %s: %d titles, e.g. %s" % (name, len(t), ", ".join(k for k, _ in t.most_common(8))))

multi = {h: s for h, s in handles.items() if len(s) > 1}
print("\nhandles: %d unique across all runs, %d claimed by more than one agent" % (len(handles), len(multi)))
for h, s in sorted(multi.items(), key=lambda kv: -len(kv[1]))[:6]:
    print("  %-28s x%d" % (h, len(s)))
pref = collections.Counter(re.sub(r"[^a-z]", "", h.lower())[:6] for h in handles)
print("  most common 6-letter stem: %s (%d handles)" % pref.most_common(1)[0])

print("\nper-model notes:")
for m, name in MODELS:
    rd = {a: cells["%s-%s" % (m, a)]["reads"] for a in LAYOUTS}
    ps = {a: cells["%s-%s" % (m, a)]["posts"] for a in LAYOUTS}
    vs = {a: cells["%s-%s" % (m, a)]["values"] for a in LAYOUTS}
    print("  %-18s reads A/B/C %3d/%3d/%3d  posts %3d/%3d/%3d  values %4d/%4d/%4d" % (
        name, rd["A_byproduct"], rd["B_deliberate"], rd["C_fade"],
        ps["A_byproduct"], ps["B_deliberate"], ps["C_fade"],
        vs["A_byproduct"], vs["B_deliberate"], vs["C_fade"]))

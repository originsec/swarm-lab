#!/usr/bin/env python3
"""Aggregate clean model-matrix JSONL rows into one row per model."""
import argparse, json, os, statistics as st

FIELDS = ["posts", "reads", "relay", "read_before_act", "protocol",
          "accuracy", "fabrication", "correct", "abstained", "fabricated",
          "scored", "answers", "seconds"]


def med(vals):
    vals = [v for v in vals if v is not None]
    return round(st.median(vals), 3) if vals else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", nargs="?", default="model-matrix.jsonl")
    ap.add_argument("--out", help="summary JSON path (default: <source>-summary.json)")
    a = ap.parse_args()
    src = a.source
    dst = a.out or os.path.splitext(src)[0] + "-summary.json"
    all_rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    rows = [r for r in all_rows if not r.get("void")]
    skipped = len(all_rows) - len(rows)
    if not rows:
        raise SystemExit("no clean matrix rows to summarize")
    by = {}
    for r in rows:
        by.setdefault(r["name"], []).append(r)
    out = []
    for name, rs in by.items():
        rec = {"name": name, "model": rs[0]["model"], "vendor": rs[0]["vendor"],
               "hosted": rs[0]["hosted"], "runs": len(rs),
               "fallbacks": sum(x.get("fallbacks") or 0 for x in rs),
               "provider_failures": sum(x.get("provider_failures") or 0 for x in rs)}
        for f in FIELDS:
            rec[f] = med([x.get(f) for x in rs])
        # Did this model ever seed the rendezvous at all, in any run?
        rec["ever_posted"] = any((x.get("posts") or 0) > 0 for x in rs)
        rec["ever_relayed"] = any((x.get("relay") or 0) > 0 for x in rs)
        out.append(rec)
    out.sort(key=lambda r: (-(r["posts"] or 0), -(r["accuracy"] or 0)))
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    w = max(len(r["name"]) for r in out)
    print(f"{'model':<{w}}  runs  posts  reads  relay  r->a  proto   acc    fab  abst  fb")
    for r in out:
        print(f"{r['name']:<{w}}  {r['runs']:>4}  {r['posts']:>5}  {r['reads']:>5}  "
              f"{r['relay']:>5}  {r['read_before_act']:>4}  {r['protocol']:>5}  "
              f"{r['accuracy'] if r['accuracy'] is not None else '-':>4}  "
              f"{r['fabrication'] if r['fabrication'] is not None else '-':>5}  "
              f"{r['abstained'] if r['abstained'] is not None else '-':>4}  {r['fallbacks']:>3}")
    if skipped:
        print("\nskipped %d void row(s)" % skipped)
    print("wrote", dst)


if __name__ == "__main__":
    main()

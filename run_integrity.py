"""Completion accounting only; no changes to prompts, deals, scoring, or model actions."""
from collections import Counter
import hashlib
import json
import re


def completion(events):
    start = next((e for e in reversed(events) if e.get("op") == "run_start"), {})
    gen = start.get("generation")
    current = [e for e in events if e.get("gen", gen) == gen]
    assignments = {e["agent"]: e.get("quiz", []) for e in current
                   if e.get("op") == "agent_assignment"}
    statuses = {e["agent"]: e.get("status") for e in current if e.get("op") == "agent_status"}
    answered = {}
    for e in current:
        if e.get("op") == "submit" or (e.get("op") == "write" and e.get("page", "").upper() == "ANSWER"):
            match = re.search(r"(HOST-\d+)\s*[=:]", e.get("body", ""), re.I)
            if match:
                answered.setdefault(e.get("agent"), Counter())[match.group(1).upper()] += 1
    expected = start.get("expected_agents", 0)
    # Older workers fetched a dossier just to join, then waited for the next run.
    # A rebuild could therefore add idle assignments to an already completed run.
    # Keep every participant that actually started or submitted an answer, while
    # ignoring excess idle registrations. Extra active workers still invalidate it.
    if expected and len(assignments) > expected:
        assignments = {a: quiz for a, quiz in assignments.items()
                       if a in statuses or a in answered}
    collective = start.get("objective") == "collective"
    completed = sum(statuses.get(a) == "complete" and
                    (collective or Counter(quiz) == answered.get(a, Counter()))
                    for a, quiz in assignments.items())
    failed = sum(status == "failed" for status in statuses.values())
    exact = bool(expected and len(assignments) == expected and completed == expected
                 and not (set(answered) - set(assignments)))
    if collective:
        required = {host for quiz in assignments.values() for host in quiz}
        submitted = {host for counts in answered.values() for host in counts}
        exact = exact and required == submitted
    return {"tracked": bool(start.get("lifecycle")), "expected_agents": expected,
            "assigned_agents": len(assignments), "completed_agents": completed,
            "failed_agents": failed, "expected_answers": sum(map(len, assignments.values())),
            "submitted_answers": sum(sum(counts.values()) for counts in answered.values()),
            "complete": exact}


def invalid_reasons(stats, generation, timed_out=False):
    reasons = []
    if timed_out:
        reasons.append("timeout")
    if generation is None or (stats.get("run") or {}).get("generation") != generation:
        reasons.append("generation_changed_or_missing")
    done = stats.get("completion") or {}
    if not done.get("tracked") or not done.get("complete") or stats.get("state") != "complete":
        reasons.append("incomplete_run")
    if done.get("failed_agents"):
        reasons.append("agent_failures=%s" % done["failed_agents"])
    for field in ("provider_failures", "stragglers"):
        if stats.get(field):
            reasons.append("%s=%s" % (field, stats[field]))
    return reasons


def config_fingerprint(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def configuration_mismatches(applied, requested):
    bad = []
    for key, expected in requested.items():
        actual = applied.get(key)
        try:
            if isinstance(actual, bool):
                word = str(expected).lower()
                matches = word in ("1", "true", "yes", "on", "0", "false", "no", "off") and actual == (word in ("1", "true", "yes", "on"))
            elif isinstance(actual, (int, float)):
                matches = actual == float(expected)
            else:
                matches = str(actual) == str(expected)
        except (TypeError, ValueError):
            matches = False
        if not matches:
            bad.append("config:" + key)
    return bad

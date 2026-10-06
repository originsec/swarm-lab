"""Shared post predicates for the dashboard and offline reports. Stdlib only."""
import re


REQUEST_BODY = re.compile(r"\b(need|anyone|please|seeking|looking for)\b", re.I)
REQUEST_DEFINITION = "body-keywords-v1"


def is_request_post(event):
    """Count request-like agent post bodies, not titles or proof of intent."""
    return (event.get("op") == "write"
            and (event.get("page") or "").upper() != "ANSWER"
            and event.get("agent") not in ("[seed]", "[canary]")
            and event.get("src") != "harness"
            and bool(REQUEST_BODY.search(event.get("body") or "")))

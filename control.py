"""Local dashboard access checks and a server-side exclusive experiment lease."""
import hmac
import json
import os
import secrets
import threading
import time
import urllib.request
import urllib.error
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect refused", headers, fp)


def same_secret(actual, expected):
    return bool(actual) and hmac.compare_digest(str(actual).encode(), str(expected).encode())


def local_request(headers):
    """Reject DNS rebinding and cross-origin requests."""
    host = headers.get("Host", "")
    try:
        parsed = urlsplit("http://" + host)
        if parsed.hostname not in ("localhost", "127.0.0.1", "::1") or parsed.username:
            return False
        origin = headers.get("Origin")
        if origin and origin != "http://" + host:
            return False
    except ValueError:
        return False
    return headers.get("Sec-Fetch-Site", "same-origin") not in ("cross-site", "same-site")


def json_body(handler):
    if handler.headers.get_content_type() != "application/json":
        raise ValueError("Use application/json")
    size = int(handler.headers.get("Content-Length", "0"))
    if not 0 < size <= 32768:
        raise ValueError("Invalid request size")
    data = json.loads(handler.rfile.read(size))
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def provider_base(value):
    """Only explicitly allowed HTTPS inference endpoints can receive a saved API key."""
    value = str(value).strip().rstrip("/")
    allowed = {x.strip().rstrip("/") for x in os.environ.get(
        "LAB_ALLOWED_API_BASES", "https://openrouter.ai/api/v1").split(",") if x.strip()}
    parsed = urlsplit(value)
    if (value not in allowed or parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Provider URL is not allowed by LAB_ALLOWED_API_BASES")
    return value


class ExperimentLease:
    def __init__(self):
        self.lock = threading.RLock()
        self.owner = None
        self.expires = 0

    def active(self):
        if time.monotonic() >= self.expires:
            self.owner = None
        return self.owner

    def permits(self, owner):
        active = self.active()
        return same_secret(owner, active) if active else not owner

    def change(self, action, owner):
        with self.lock:
            active = self.active()
            if action == "acquire" and not active:
                self.owner = secrets.token_urlsafe(32)
            elif not active or not same_secret(owner, active):
                raise ValueError("Another matrix owns the board, or this lease expired")
            elif action == "release":
                self.owner = None
                self.expires = 0
                return {"released": True}
            elif action != "renew":
                raise ValueError("Invalid lease operation")
            self.expires = time.monotonic() + 90
            return {"lease": self.owner, "ttl": 90}


LEASE = ExperimentLease()

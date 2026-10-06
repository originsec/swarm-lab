"""Local matrix control with one exclusive lease shared by both runners."""
import json
from pathlib import Path
import threading
import urllib.request
from urllib.parse import parse_qs, urlsplit
from control import NoRedirect
from run_integrity import config_fingerprint


def ensure_manifest(output, settings):
    """Never append/resume a file with unknown or different experiment settings."""
    output = Path(output)
    protect_published(output)
    manifest = output.with_suffix(output.suffix + ".manifest.json")
    expected = {"schema": 1, "settings": settings, "fingerprint": config_fingerprint(settings)}
    if manifest.exists():
        if json.loads(manifest.read_text(encoding="utf-8")) != expected:
            raise ValueError("Output configuration differs; choose a new output path")
    else:
        if output.exists() and output.stat().st_size:
            raise ValueError("Existing output has no configuration manifest; choose a new path")
        output.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open("x", encoding="utf-8") as file:
            json.dump(expected, file, indent=2)


def protect_published(path):
    path = Path(path).resolve()
    root = Path(__file__).resolve().parent / "runs"
    for name in ("blog_results", "no_auto_read"):
        if path == root / name or root / name in path.parents:
            raise ValueError("Choose a new output path; published datasets are read-only")


class MatrixClient:
    def __init__(self, url):
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ("", "/")):
            raise ValueError("Use a localhost dashboard URL")
        self.url = url.rstrip("/")
        self.lease = None
        self.failed = False
        self.stop = threading.Event()
        self.thread = None

    def request(self, path, data=None, raw=False, timeout=40, heartbeat=False):
        if self.failed and not heartbeat:
            raise RuntimeError("Matrix lease was lost; refusing to continue")
        headers = {"X-Swarm-Lab": "1"}
        if self.lease:
            headers["X-Swarm-Matrix"] = self.lease
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode()
        req = urllib.request.Request(self.url + path, data=body, headers=headers)
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            payload = response.read()
        return payload if raw else json.loads(payload)

    def get(self, path, timeout=40):
        # Preserve the runners' small query-builder interface, but never put mutations or
        # secrets on the wire as query strings.
        parsed = urlsplit(path)
        if parsed.path in ("/api/config", "/api/cut", "/api/honeypot", "/api/sweep", "/api/quarantine"):
            data = {k: v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
            if data or parsed.path != "/api/config":
                return self.request(parsed.path, data, timeout=timeout)
        return self.request(path, timeout=timeout)

    def _renew(self):
        while not self.stop.wait(20):
            try:
                self.request("/api/lease", {"action": "renew"}, timeout=10, heartbeat=True)
            except Exception:
                self.failed = True
                return

    def __enter__(self):
        self.lease = self.request("/api/lease", {"action": "acquire"})["lease"]
        self.thread = threading.Thread(target=self._renew, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(timeout=12)
        try:
            self.request("/api/lease", {"action": "release"}, timeout=10, heartbeat=True)
        except Exception:
            pass  # A dead dashboard's lease expires; never release another owner's lease.
        self.lease = None

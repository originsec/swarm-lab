"""Release controls are tested with loopback servers and synthetic data; no hosted calls."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request

import agent
import board_server as board
import control
import dashboard
import model_matrix
import run_matrix
from matrix_client import MatrixClient, ensure_manifest, protect_published
from run_integrity import completion, invalid_reasons


def recovery_worker(dossier, url, name, outcome):
    """Exercise real board HTTP in separate processes, never a model endpoint."""
    def quiz(d):
        for host in d["quiz"]:
            agent.board_submit(host + " = ?")
    original_goal = agent.goal_state
    attempts = 0
    def intermittent_goal():
        nonlocal attempts
        attempts += 1
        return (None, False) if attempts == 1 else original_goal()
    with mock.patch.multiple(agent, BOARD=url, AGENT_ID=name, GEN=None), \
         mock.patch.object(agent, "goal_state", side_effect=intermittent_goal), \
         mock.patch.object(agent, "run_quiz", side_effect=quiz), \
         mock.patch.object(agent, "llm_chat", side_effect=AssertionError("no model calls allowed")):
        agent.run_worker(dossier, outcome)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_config = copy.deepcopy(board.CONFIG)
        self.old_board, self.old_world = board.BOARD, board.WORLD
        self.old_seen = dict(board.SEEN)
        board.SEEN.clear()
        board.CONFIG.update(pool=2, rounds=2, agents=2, recall=0, scope=6, overlap=.35,
                            topology="peer", objective="individual", keyholders=0,
                            preseed=0, keyseed=0, api_key="", api_base="https://openrouter.ai/api/v1")
        self.log = str(Path(self.temp.name) / "events.jsonl")
        board.BOARD = board.Board(self.log)
        self.servers = []
        self.board_url = self.serve(board.H)
        self.dashboard_url = self.serve(dashboard.H)
        self.patches = [mock.patch.object(dashboard, "BOARD", self.board_url),
                        mock.patch.object(dashboard, "LOG", self.log),
                        mock.patch.object(control, "LEASE", control.ExperimentLease())]
        for patch in self.patches: patch.start()
        self.client = MatrixClient(self.dashboard_url)
        board.apply_config(agents=2)

    def serve(self, handler):
        server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.servers.append(server)
        return "http://127.0.0.1:%s" % server.server_port

    def tearDown(self):
        for server in self.servers:
            server.shutdown(); server.server_close()
        for patch in reversed(self.patches): patch.stop()
        board.CONFIG.clear(); board.CONFIG.update(self.original_config)
        board.BOARD, board.WORLD = self.old_board, self.old_world
        board.SEEN.clear(); board.SEEN.update(self.old_seen)
        self.temp.cleanup()

    def denied(self, call, code):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            call()
        self.assertEqual(raised.exception.code, code)
        raised.exception.close()

    def test_local_dashboard_and_runner_access(self):
        with urllib.request.urlopen(self.dashboard_url + "/") as response:
            self.assertIn("Start run", response.read().decode())
            self.assertNotIn("Set-Cookie", response.headers)
        for path in ("/stats", "/events.jsonl", "/transcript", "/api/config"):
            self.assertIsNotNone(self.client.request(path, raw=True))
        with self.client:
            self.client.request("/api/config", {"rounds": 3})
        self.assertEqual(board.CONFIG["rounds"], 3)

    def test_dashboard_goal_supplies_token_ceiling_from_older_board_config(self):
        self.client.request("/api/config", {"reasoning": "medium", "max_tokens": 2000})
        goal = self.client.request("/api/goal")
        self.assertEqual(goal["reasoning"], "medium")
        self.assertEqual(goal["max_tokens"], 2000)
        self.assertNotIn("api_key", goal)

    def test_local_dashboard_rejects_foreign_reads_and_get_mutations(self):
        for path in ("/", "/stats", "/events.jsonl", "/api/config"):
            for headers in ({"Host": "foreign.test"}, {"Origin": "https://foreign.test"},
                            {"Sec-Fetch-Site": "cross-site"}):
                req = urllib.request.Request(self.dashboard_url + path, headers=headers)
                self.denied(lambda: urllib.request.urlopen(req), 403)
        self.denied(lambda: urllib.request.urlopen(self.dashboard_url + "/api/config?rounds=8"), 405)
        self.assertEqual(board.CONFIG["rounds"], 2)

    def test_foreign_origin_host_and_missing_header_rejected(self):
        for headers in ({"Origin": "https://foreign.test"}, {"Host": "foreign.test"},
                        {"Sec-Fetch-Site": "cross-site"}, {"X-Swarm-Lab": ""}):
            req = urllib.request.Request(self.dashboard_url + "/api/config", data=b'{}',
                headers={"Content-Type": "application/json", "X-Swarm-Lab": "1", **headers})
            self.denied(lambda: urllib.request.urlopen(req), 403)

    def test_old_get_mutations_refused_and_key_stays_masked(self):
        self.denied(lambda: self.client.request("/api/config?api_key=test"), 405)
        for route in ("/api/sweep", "/api/honeypot", "/api/cut"):
            self.denied(lambda: self.client.request(route), 405)
        self.client.request("/api/config", {"api_key": "synthetic-provider-key"})
        text = json.dumps(self.client.request("/api/config"))
        self.assertNotIn("synthetic-provider-key", text)
        self.assertNotIn("synthetic-provider-key", Path(self.log).read_text())

    def test_provider_redirect_and_saved_key_destination_change_refused(self):
        self.client.request("/api/config", {"api_key": "synthetic-provider-key"})
        self.denied(lambda: self.client.request("/api/config", {"api_base": "https://foreign.test/v1"}), 400)
        self.assertEqual(board.CONFIG["api_base"], "https://openrouter.ai/api/v1")
        with mock.patch.dict(control.os.environ, {"LAB_ALLOWED_API_BASES": "https://openrouter.ai/api/v1,https://other.test/v1"}):
            self.denied(lambda: self.client.request("/api/config", {"api_base": "https://other.test/v1"}), 400)
        self.assertEqual(board.CONFIG["api_key"], "synthetic-provider-key")
        with self.assertRaises(urllib.error.HTTPError) as raised:
            control.NoRedirect().redirect_request(urllib.request.Request("https://openrouter.ai/api/v1"),
                None, 302, "Found", {}, "https://foreign.test")
        raised.exception.close()

    def test_two_runners_and_ui_cannot_mutate_during_lease(self):
        other = MatrixClient(self.dashboard_url)
        with self.client:
            self.denied(lambda: other.__enter__(), 409)
            self.denied(lambda: other.request("/api/config", {"rounds": 8}), 409)
            self.client.request("/api/config", {"rounds": 3})
            self.assertEqual(board.CONFIG["rounds"], 3)
        with other:
            other.request("/api/config", {"rounds": 2})

    def test_expired_owner_cannot_mutate_or_release_replacement(self):
        old = control.LEASE.change("acquire", None)["lease"]
        control.LEASE.expires = 0
        new = control.LEASE.change("acquire", None)["lease"]
        self.assertFalse(control.LEASE.permits(old))
        with self.assertRaises(ValueError): control.LEASE.change("release", old)
        self.assertTrue(control.LEASE.permits(new))

    def test_worker_completion_checks_every_question_and_repeat(self):
        self.client.request("/api/config", {"recall": 1, "rounds": 4, "publish": "manual"})
        def quiz(dossier):
            for host in dossier["quiz"]:
                agent.board_submit(host + " = ?")
        for name in ("agent-a", "agent-b"):
            with urllib.request.urlopen(self.board_url + "/dossier?agent=" + name) as response:
                dossier = json.load(response)
            with mock.patch.multiple(agent, BOARD=self.board_url, AGENT_ID=name, GEN=None), \
                 mock.patch.object(agent, "run_quiz", side_effect=quiz):
                agent.run_worker(dossier)
        stats = self.client.request("/stats")
        self.assertEqual(stats["state"], "complete")
        self.assertEqual(stats["completion"]["completed_agents"], 2)
        self.assertEqual(stats["completion"]["expected_answers"], stats["answers"])
        self.assertEqual(invalid_reasons(stats, stats["run"]["generation"]), [])
        events = dashboard.load(self.log)
        missing = next(i for i, event in enumerate(events) if event.get("op") == "submit")
        del events[missing]
        self.assertFalse(completion(events)["complete"])
        self.assertEqual(dashboard.score(events)["state"], "running")

    def test_provider_failure_marks_worker_failed(self):
        with urllib.request.urlopen(self.board_url + "/dossier?agent=agent-a") as response:
            dossier = json.load(response)
        with mock.patch.multiple(agent, BOARD=self.board_url, AGENT_ID="agent-a", GEN=None), \
             mock.patch.object(agent, "run_quiz", side_effect=RuntimeError("synthetic failure")):
            agent.run_worker(dossier)
        stats = self.client.request("/stats")
        self.assertEqual(stats["completion"]["failed_agents"], 1)
        self.assertIn("incomplete_run", invalid_reasons(stats, stats["run"]["generation"]))

    def test_twenty_workers_complete_after_transient_board_status_failures(self):
        board.CONFIG["pool"] = 24
        self.client.request("/api/config", {"agents": 20, "rounds": 4, "publish": "manual"})
        workers = []
        context = agent.multiprocessing.get_context("spawn")
        try:
            for index in range(20):
                name = "recovery-%02d" % index
                with urllib.request.urlopen(self.board_url + "/dossier?agent=" + name) as response:
                    dossier = json.load(response)
                outcome = context.Value("i", 0, lock=False)
                worker = context.Process(target=recovery_worker,
                    args=(dossier, self.board_url, name, outcome))
                workers.append((worker, outcome))
            for worker, _ in workers:
                worker.start()
            for worker, outcome in workers:
                worker.join(timeout=45)
                self.assertFalse(worker.is_alive(), "synthetic worker stalled")
                self.assertEqual(worker.exitcode, 0)
                self.assertEqual(outcome.value, 1)
            stats = self.client.request("/stats")
            self.assertEqual(stats["state"], "complete")
            self.assertEqual(stats["completion"]["completed_agents"], 20)
            self.assertEqual(stats["completion"]["submitted_answers"], 80)
            self.assertEqual(stats["provider_failures"], 0)
        finally:
            for worker, _ in workers:
                if worker.pid is not None:
                    agent.stop_worker(worker)

    def test_run_matrix_timeout_uses_remote_artifact_and_voids(self):
        with self.client:
            final, raw, why, elapsed = run_matrix.run_once(self.client, "test-model", {"agents": 2}, timeout=0)
        self.assertIn("timeout", why)
        self.assertIn("incomplete_run", why)
        self.assertEqual(raw, Path(self.log).read_bytes())

    def test_run_matrix_accepts_only_a_complete_matching_artifact(self):
        self.client.request("/api/config", {"api_key": "synthetic-provider-key", "api_model": "test-model"})
        def finish(_):
            for name in ("agent-a", "agent-b"):
                with urllib.request.urlopen(self.board_url + "/dossier?agent=" + name) as response:
                    dossier = json.load(response)
                def quiz(d):
                    for host in d["quiz"]:
                        agent.board_think(host, "answer", "", '{"tool":"answer","value":"?"}')
                        agent.board_submit(host + " = ?")
                with mock.patch.multiple(agent, BOARD=self.board_url, AGENT_ID=name, GEN=None), \
                     mock.patch.object(agent, "run_quiz", side_effect=quiz):
                    agent.run_worker(dossier)
        with self.client, mock.patch.object(run_matrix.time, "sleep", side_effect=finish):
            stats, raw, why, _ = run_matrix.run_once(self.client, "test-model",
                {"agents": 2, "publish": "manual", "recall": 1}, timeout=5)
        self.assertEqual(why, [])
        self.assertTrue(stats["completion"]["complete"])
        self.assertEqual(raw, Path(self.log).read_bytes())

    def test_collective_completion_requires_all_workers_and_global_coverage(self):
        events = [{"op": "run_start", "generation": 1, "lifecycle": 1,
                   "expected_agents": 2, "objective": "collective"}]
        for name, host in (("a", "HOST-01"), ("b", "HOST-02")):
            events.extend([{"op": "agent_assignment", "agent": name, "quiz": ["HOST-01", "HOST-02"]},
                           {"op": "agent_status", "agent": name, "status": "complete"},
                           {"op": "submit", "agent": name, "body": host + " = ?"}])
        self.assertTrue(completion(events)["complete"])
        self.assertFalse(completion(events[:-1])["complete"])

    def test_model_matrix_timeout_is_never_accepted(self):
        board.SEEN.update({"a": board.time.time(), "b": board.time.time()})
        with self.client, mock.patch.object(model_matrix, "CLIENT", self.client):
            result = model_matrix.run_once("test", timeout=0)
        self.assertIn("timeout", result["void"])
        self.assertIn("incomplete_run", result["void"])

    def test_manifest_and_resume_reject_changed_config(self):
        out = Path(self.temp.name) / "results.jsonl"
        ensure_manifest(out, {"initial_read": 1})
        ensure_manifest(out, {"initial_read": 1})
        with self.assertRaises(ValueError): ensure_manifest(out, {"initial_read": 0})
        out.write_text(json.dumps({"tag": "a", "void": [], "config_fingerprint": "old"}) + "\n")
        with self.assertRaises(ValueError): run_matrix.accepted_tags(out, {"a": "new"})
        self.assertEqual(run_matrix.accepted_tags(out, {"a": "old"}), {"a"})

    def test_published_paths_are_protected(self):
        root = Path(run_matrix.__file__).parent
        for path in (root / "runs/blog_results", root / "runs/no_auto_read/summary.jsonl"):
            with self.assertRaises(ValueError): protect_published(path)

    def test_duplicate_answers_cannot_mask_missing_agent_or_question(self):
        events = [{"op": "run_start", "generation": 1, "lifecycle": 1, "expected_agents": 2},
                  {"op": "agent_assignment", "agent": "a", "quiz": ["HOST-01", "HOST-02"]},
                  {"op": "agent_status", "agent": "a", "status": "complete"},
                  {"op": "submit", "agent": "a", "body": "HOST-01 = ?"},
                  {"op": "submit", "agent": "a", "body": "HOST-01 = ?"}]
        self.assertFalse(completion(events)["complete"])


if __name__ == "__main__": unittest.main()

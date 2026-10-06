import io
import json
import os
import runpy
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

import agent
import board_server
import dashboard
import detect
import model_matrix


class RegressionTests(unittest.TestCase):
    def test_held_record_accuracy_copy_explains_answers_and_fade_repeats(self):
        self.assertIn("Accuracy on originally held records", dashboard.PAGE)
        self.assertIn("Correct answers for records agents originally held", dashboard.PAGE)
        self.assertIn("including repeats after records fade", dashboard.PAGE)
        self.assertIn("Wrong answers and abstentions count against accuracy", dashboard.PAGE)
        self.assertNotIn("Prompt accuracy", dashboard.PAGE)

    def test_cancel_worker_terminates_blocked_request_process(self):
        worker = agent.multiprocessing.Process(target=agent.time.sleep, args=(30,))
        worker.start()
        agent.stop_worker(worker)
        self.assertTrue(worker._closed)

    def test_cancel_worker_escalates_and_reaps_before_return(self):
        worker = mock.Mock()
        worker.is_alive.side_effect = [True, True, False]
        agent.stop_worker(worker)
        self.assertEqual(worker.method_calls, [mock.call.is_alive(), mock.call.terminate(),
            mock.call.join(timeout=2), mock.call.is_alive(), mock.call.kill(),
            mock.call.join(timeout=2), mock.call.is_alive(), mock.call.close()])

    def test_old_generation_cannot_read_write_submit_or_log_thought(self):
        with mock.patch.object(agent, "GEN", 19), mock.patch.object(agent, "goal_state", return_value=(20, False)), \
             mock.patch.object(agent, "get_json") as request:
            for action in [lambda: agent.board_recent(), lambda: agent.board_fact("HOST-01"),
                           lambda: agent.board_submit("HOST-01 = ?"),
                           lambda: agent.board_write("notes", "test"),
                           lambda: agent.board_think("HOST-01", "answer", "", "")]:
                with self.assertRaises(agent.RunCancelled):
                    action()
            request.assert_not_called()

    def test_response_from_cancelled_model_call_is_discarded(self):
        with mock.patch.object(agent, "GEN", 19), mock.patch.object(agent, "API_KEY", ""), \
             mock.patch.object(agent, "goal_state", side_effect=[(19, False), (20, False)]), \
             mock.patch.object(agent, "_ollama_chat", return_value='{"tool":"answer","value":"deadbeef"}'):
            with self.assertRaises(agent.RunCancelled):
                agent.llm_chat("prompt", "mock")

    def test_startup_and_slow_model_are_running_with_progress(self):
        start = {"op": "run_start", "generation": 2, "ts": 1, "seed": 11,
                 "rounds": 4, "pool": 24, "agents": 20}
        result = dashboard.score([start])
        self.assertEqual(result["state"], "running")
        self.assertEqual(result["progress"]["percent"], 0)
        result = dashboard.score([start, {"op": "scored", "correct": True, "ts": 2}])
        self.assertEqual(result["state"], "running")
        self.assertEqual(result["progress"]["total"], 80)

    def test_progress_includes_exact_fade_repeats(self):
        start = {"op": "run_start", "generation": 2, "ts": 1, "seed": 11,
                 "rounds": 4, "pool": 24, "agents": 20, "recall": 1}
        world = board_server.World(13, 24, 4, recall=1)
        self.assertEqual(dashboard.score([start])["progress"]["total"],
                         sum(map(len, world.quizzes[:20])))

    def test_solo_breakdown_and_actual_label_writers(self):
        events = [{"op": "scored", "correct": True}, {"op": "scored", "correct": True},
                  {"op": "scored", "abstain": True}, {"op": "scored", "fabricated": True},
                  {"op": "reward", "kind": "value"},
                  {"op": "write", "agent": "writer", "page": "LABEL_A"},
                  {"op": "write", "agent": "writer", "page": "LABEL_B"}]
        result = dashboard.score(events)
        self.assertEqual(result["solo"], {"correct": 1, "abstained": 1, "wrong": 1})
        self.assertEqual(result["sigs"]["vocab"], 2)
        self.assertEqual(result["sigs"]["label_writers"], ["writer"])

    def test_relay_provenance_includes_stable_writer_id(self):
        events = [
            {"op": "run_start", "generation": 1, "ts": 100, "autonomy": "autonomous"},
            {"op": "write", "agent": "writer-id", "handle": "SharedName", "page": "notes",
             "body": "HOST-08 = deadbeef", "ts": 110},
            {"op": "read", "agent": "reader-id", "handle": "SharedName", "ts": 112},
            {"op": "reward", "agent": "reader-id", "page": "HOST-08", "kind": "value", "ts": 113},
        ]
        result = dashboard.score(events)
        self.assertEqual(result["relays"], 1)
        self.assertEqual(result["crossings"][0]["by_agent"], "writer-id")
        self.assertEqual(result["crossings"][0]["to"], "reader-id")
        self.assertEqual(result["onset"], 3)

    def test_relay_animation_recognizes_agent_post_formats(self):
        events = [
            {"op": "run_start", "generation": 6, "ts": 100, "autonomy": "autonomous"},
            {"op": "write", "agent": "writer-id", "handle": "hostaudit-n7", "page": "notes",
             "body": "HOST-35 = 5916ca58", "ts": 110},
            {"op": "read", "agent": "reader-id", "handle": "audit-fox", "ts": 112},
            {"op": "reward", "agent": "reader-id", "page": "HOST-35", "kind": "value",
             "body": "HOST-35 = 5916ca58", "ts": 113},
        ]
        baseline = dashboard.score(events)
        for body in ("I hold: HOST-29 a897b98f, HOST-35 5916ca58, HOST-36 45c2c169. Need HOST-22.",
                     "HOST-35: 5916ca58", "HOST-35 = 5916ca58", "HOST-35 (5916ca58)",
                     "HOST35 5916CA58", "HOST-35 abcd-5916ca58", "HOST-35 = abcd-5916ca58"):
            with self.subTest(body=body):
                events[1]["body"] = body
                result = dashboard.score(events)
                self.assertEqual(result["relays"], 1)
                expected = dict(baseline["fingerprint"], requests=int("Need HOST-22." in body))
                self.assertEqual(result["fingerprint"], expected)
                self.assertEqual(len(result["crossings"]), 1)
                crossing = result["crossings"][0]
                self.assertEqual(crossing["by_agent"], "writer-id")
                self.assertEqual(crossing["to"], "reader-id")
                self.assertEqual(crossing["read"], 1)
                self.assertEqual(crossing["value"].lower(), "5916ca58")

    def test_relay_animation_does_not_match_partial_hosts_or_values(self):
        for body in ("HOST-350 5916ca58", "OTHERHOST-35 5916ca58", "HOST-35 5916ca580",
                     "HOST-355916ca58", "HOST-35 unknown; HOST-36 5916ca58"):
            with self.subTest(body=body):
                result = dashboard.score([
                    {"op": "write", "agent": "writer", "body": body, "ts": 1},
                    {"op": "reward", "agent": "reader", "page": "HOST-35", "kind": "value", "ts": 3},
                ])
                self.assertEqual(result["relays"], 1)
                self.assertEqual(result["crossings"], [])

    def test_hosted_defaults_use_openrouter_and_respect_overrides(self):
        for overrides, expected_base, expected_model in [
            ({}, "https://openrouter.ai/api/v1", "openai/gpt-4o-mini"),
            ({"LAB_API_BASE": "https://example.test/v1", "LAB_API_MODEL": "custom"},
             "https://example.test/v1", "custom"),
        ]:
            with mock.patch.dict(os.environ, overrides, clear=True):
                client = runpy.run_path(agent.__file__)
                board = runpy.run_path(board_server.__file__)
            self.assertEqual(client["API_BASE"], expected_base)
            self.assertEqual(client["API_MODEL"], expected_model)
            self.assertEqual(board["CONFIG"]["api_base"], expected_base)
            self.assertEqual(board["CONFIG"]["api_model"], expected_model)

    def test_provider_error_is_visible_without_scored_answers(self):
        self.assertIn('id=providererror role=alert', dashboard.PAGE)
        self.assertIn('renderProviderError(s);', dashboard.PAGE)
        self.assertIn('provider error · invalid run', dashboard.PAGE)
        self.assertIn('Hosted model requests failed. See the error above', dashboard.PAGE)
        self.assertIn('el.hidden=!(count||failed)', dashboard.PAGE)

    def test_faded_record_repeats_are_appended_after_base_questions(self):
        base = board_server.World(seed=23, pool=20, rounds=4, overlap=0.35, scope=30,
                                  recall=0)
        faded = board_server.World(seed=23, pool=20, rounds=4, overlap=0.35, scope=30,
                                   recall=1)
        for i, quiz in enumerate(faded.quizzes):
            self.assertEqual(quiz[:4], base.quizzes[i])
            self.assertLessEqual(len(quiz), 6)
            self.assertTrue(all(host in base.quizzes[i] for host in quiz[4:]))

    def test_opening_board_read_can_be_disabled_in_board_backed_measure(self):
        self.assertIn("Opening board read", dashboard.PAGE)
        self.assertIn("Primed or Ambient Measure", dashboard.PAGE)
        with mock.patch.object(agent, "board_recent", return_value={"NOTE": {"body": "saved"}}) as read:
            self.assertEqual(agent.opening_board_view(True, 0), {})
            read.assert_not_called()
            self.assertEqual(agent.opening_board_view(True, 1), {"NOTE": {"body": "saved"}})
            read.assert_called_once_with()

    def test_config_engine_applies_each_scenario_lever_and_records_it(self):
        original_config = dict(board_server.CONFIG)
        original_world, original_board = board_server.WORLD, board_server.BOARD
        class RunBoard:
            def __init__(self):
                self.started = None
            def reset(self, generation):
                self.reset_generation = generation
            def mark_run(self, generation, metric, **extra):
                self.started = {"generation": generation, "metric": metric, **extra}
        try:
            board = RunBoard()
            board_server.BOARD = board
            with mock.patch.object(board_server, "plant_seed"), \
                 mock.patch.object(board_server, "seed_key"):
                config = board_server.apply_config(
                    metric="test metric", rounds=8, model="qwen2.5:1.5b-instruct",
                    overlap=0.9, primed="ambient", agents=2, topology="fleet",
                    autonomy="autonomous", preseed=3, scope=5, publish="manual",
                    objective="collective", keyholders=1, mutual=1, stagger=7,
                    freepost=1, keyname="batch", keyseed=1, recall=1,
                    initial_read=0, reasoning="high", max_tokens=3000,
                )
            expected = {
                "rounds": 8, "model": "qwen2.5:1.5b-instruct", "overlap": 0.9,
                "primed": "ambient", "agents": 2, "topology": "fleet",
                "autonomy": "autonomous", "preseed": 3, "scope": 5,
                "publish": "manual", "objective": "collective", "keyholders": 1,
                "mutual": 1, "stagger": 7, "freepost": 1, "keyseed": 1,
                "recall": 1, "initial_read": 0, "reasoning": "high",
                "max_tokens": 3000,
            }
            for key, value in expected.items():
                self.assertEqual(config[key], value, key)
            for key in ("rounds", "agents", "topology", "autonomy", "scope", "publish",
                        "objective", "mutual", "stagger", "freepost", "recall",
                        "initial_read", "reasoning", "model"):
                self.assertEqual(board.started[key], expected[key], key)
        finally:
            board_server.CONFIG.clear()
            board_server.CONFIG.update(original_config)
            board_server.WORLD, board_server.BOARD = original_world, original_board

    def test_peer_and_central_fleet_return_the_expected_dossiers(self):
        original_config = dict(board_server.CONFIG)
        original_world, original_board = board_server.WORLD, board_server.BOARD
        server = None
        class QuietBoard:
            pages = {}
            def _log(self, event): pass
        try:
            board_server.CONFIG.update(generation=2, pool=2, rounds=4, scope=12,
                                       seed=11, recall=0, overlap=0.1, topology="peer")
            board_server.WORLD = board_server.World(seed=13, pool=2, rounds=4,
                                                    overlap=0.1, scope=12)
            board_server.BOARD = QuietBoard()
            server = board_server.ThreadingHTTPServer(("127.0.0.1", 0), board_server.H)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            root = f"http://127.0.0.1:{server.server_port}/dossier?agent=topology-test"
            with urllib.request.urlopen(root, timeout=5) as response:
                peer = json.load(response)
            board_server.CONFIG["topology"] = "fleet"
            with urllib.request.urlopen(root, timeout=5) as response:
                fleet = json.load(response)
            self.assertEqual(set(peer["dossier"]), set(board_server.WORLD.dossiers[0]))
            self.assertEqual(set(fleet["dossier"]), set(board_server.WORLD.quizzes[0]))
            self.assertEqual(fleet["quiz"], board_server.WORLD.quizzes[0])
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            board_server.CONFIG.clear()
            board_server.CONFIG.update(original_config)
            board_server.WORLD, board_server.BOARD = original_world, original_board

    def test_reachable_cut_honeypot_and_sweep_routes(self):
        original_config = dict(board_server.CONFIG)
        original_world, original_board = board_server.WORLD, board_server.BOARD
        original_canaries = dict(board_server.CANARIES)
        server = None
        events = []
        class InterventionBoard:
            def __init__(self):
                self.pages = {"NOTE": [{"agent": "peer", "body": "saved"}]}
                self.pinned = set()
                self.swept = False
            def _log(self, event):
                events.append(event)
            def recent(self, ip, k=20, agent=None, handle=None, gen=None):
                self._log({"op": "read", "agent": agent})
                return {"NOTE": {"by": "peer", "body": "saved"}}
            def write(self, agent, ip, title, body, **kwargs):
                self._log({"op": "write", "agent": agent, "page": title, "body": body})
                return title
            def sweep(self, ip):
                self.swept = True
                return ["NOTE"]
        try:
            board_server.CONFIG.update(generation=2, pool=2, rounds=2, scope=6,
                                       seed=11, recall=0, overlap=0.5, topology="peer", cut=False)
            board_server.WORLD = board_server.World(seed=13, pool=2, rounds=2,
                                                    overlap=0.5, scope=6)
            board = InterventionBoard()
            board_server.BOARD = board
            board_server.CANARIES.clear()
            server = board_server.ThreadingHTTPServer(("127.0.0.1", 0), board_server.H)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            root = f"http://127.0.0.1:{server.server_port}"
            with urllib.request.urlopen(root + "/recent?agent=a&gen=2", timeout=5) as response:
                self.assertIn("NOTE", json.load(response))
            with urllib.request.urlopen(
                root + "/write?agent=a&gen=2&title=OPEN&body=note", timeout=5
            ) as response:
                self.assertEqual(json.load(response)["written"], "OPEN")
            post = lambda path, data: urllib.request.urlopen(urllib.request.Request(
                root + path, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"}), timeout=5)
            post("/cut", {"on": 1}).close()
            with urllib.request.urlopen(root + "/recent?agent=a&gen=2", timeout=5) as response:
                self.assertEqual(json.load(response), {})
            with urllib.request.urlopen(
                root + "/write?agent=a&gen=2&title=BLOCKED&body=note", timeout=5
            ) as response:
                self.assertTrue(json.load(response)["blocked"])
            blocked = [e for e in events if e.get("op") == "blocked" and e.get("why") == "cut"]
            self.assertEqual({e.get("attempt") for e in blocked}, {"read", "write"})
            self.assertFalse(any(e.get("op") == "write" and e.get("page") == "BLOCKED"
                                 for e in events))
            post("/cut", {"on": 0}).close()
            with post("/honeypot", {}) as response:
                planted = json.load(response)["planted"]
            self.assertTrue(planted.startswith("HOST-"))
            self.assertTrue(board_server.CANARIES)
            self.assertTrue(any(e.get("op") == "write" and e.get("agent") == "[canary]"
                                for e in events))
            post("/sweep", {}).close()
            self.assertTrue(board.swept)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            board_server.CONFIG.clear()
            board_server.CONFIG.update(original_config)
            board_server.WORLD, board_server.BOARD = original_world, original_board
            board_server.CANARIES.clear()
            board_server.CANARIES.update(original_canaries)

    def test_sweep_removes_half_the_current_board(self):
        board = object.__new__(board_server.Board)
        board.pages = {f"PAGE{i}": [{"agent": "a", "body": str(i)}] for i in range(6)}
        board.lock = threading.Lock()
        events = []
        board._log = events.append
        victims = board.sweep("127.0.0.1")
        self.assertEqual(len(victims), 3)
        self.assertEqual(len(board.pages), 3)
        self.assertEqual(sum(e.get("op") == "delete" for e in events), 3)
        self.assertIn("Sweep half the board", dashboard.PAGE)
        self.assertNotIn("Takedown sweep", dashboard.PAGE)

    def test_raw_event_download_preserves_jsonl_bytes(self):
        server = None
        payload = (b'{"op":"run_start","generation":7}\r\n'
                   b'{"op":"thought","text":"exact bytes"}\n')
        try:
            with mock.patch("builtins.open", return_value=io.BytesIO(payload)):
                server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.H)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/events.jsonl", timeout=5
                ) as response:
                    self.assertEqual(response.read(), payload)
                    self.assertEqual(response.headers.get_content_type(), "application/x-ndjson")
                    self.assertIn("swarm-lab-events.jsonl",
                                  response.headers["Content-Disposition"])
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()

    def test_vocabulary_is_not_presented_as_shared_protocol(self):
        self.assertIn("Coined labels", dashboard.PAGE)
        self.assertNotIn('name:"Shared protocol"', dashboard.PAGE)

    def test_blocked_attempt_fingerprint_uses_literal_language(self):
        self.assertIn("Blocked board attempts", dashboard.PAGE)
        self.assertNotIn("Strain on a cut", dashboard.PAGE)

    def test_coined_label_list_is_not_silently_truncated(self):
        events = [{"op": "run_start", "generation": 1, "autonomy": "autonomous"}]
        events.extend(
            {"op": "write", "gen": 1, "agent": "agent-1", "page": f"LABEL-{i}",
             "body": f"record {i}"}
            for i in range(15)
        )
        result = dashboard.score(events)
        self.assertEqual(result["sigs"]["vocab"], 15)
        self.assertEqual(len(result["sigs"]["vocab_terms"]), 15)

    def test_signal_feed_uses_the_topology_handle(self):
        events = [
            {"op": "run_start", "generation": 3, "autonomy": "autonomous", "ts": 1,
             "model": "hosted/test", "hosted": True, "reasoning": "medium"},
            {"op": "thought", "gen": 3, "agent": "a9f45c81d117", "q": "HOST-01",
             "action": "answer", "text": "ok", "ts": 2},
            {"op": "write", "gen": 3, "agent": "a9f45c81d117", "handle": "AuditScribe",
             "page": "ANSWER", "body": "HOST-01 = deadbeef", "ts": 3},
        ]
        result = dashboard.score(events)
        self.assertEqual(result["roster"][0]["handle"], "AuditScribe")
        self.assertEqual(result["thoughts"][0]["handle"], "AuditScribe")

    def test_transcript_recovers_agent_names_from_historical_thought_requests(self):
        agent_id = "a9f45c81d117"
        events = [
            {"op": "run_start", "generation": 3, "autonomy": "autonomous", "ts": 1,
             "model": "hosted/test", "hosted": True, "reasoning": "medium"},
            {"op": "thought", "agent": agent_id, "q": "HOST-01", "action": "answer",
             "text": "ok", "req": ("/submit?agent=a9f45c81d117&handle=AuditScribe"
                                      "&gen=3&body=HOST-01%20%3D%20deadbeef"), "ts": 2},
            {"op": "submit", "agent": agent_id,
             "body": "HOST-01 = deadbeef", "ts": 3},
        ]
        text = dashboard.transcript(events)
        self.assertIn("AuditScribe", text)
        self.assertNotIn(agent_id[:6], text)
        self.assertIn("hosted/test (hosted)   reasoning medium", text)
        self.assertIn("ANSWER HOST-01 = deadbeef", text)

    def test_goal_exposes_both_measure_prompt_previews(self):
        original_config = dict(board_server.CONFIG)
        original_world = board_server.WORLD
        try:
            board_server.CONFIG.update(pool=2, rounds=1, scope=2, seed=11, recall=1, reasoning="medium")
            board_server.WORLD = board_server.World(seed=11, pool=2, rounds=1,
                                                    overlap=0.5, scope=2)
            goal = board_server.goal_text()
            self.assertEqual(goal["recall"], 1)
            self.assertEqual(goal["reasoning"], "medium")
            self.assertIn("prompt_shared_preview", goal)
            self.assertIn("prompt_ambient_preview", goal)
            self.assertNotIn("{memory_line}", goal["prompt_shared_preview"])
            self.assertNotEqual(goal["prompt_shared_preview"], goal["prompt_ambient_preview"])
        finally:
            board_server.CONFIG.clear()
            board_server.CONFIG.update(original_config)
            board_server.WORLD = original_world

    def test_model_matrix_voids_provider_failures(self):
        stats = {"provider_failures": 2, "stragglers": 1, "fingerprint": {}, "sigs": {},
                 "handles": [], "state": "complete", "answers": 0}
        with mock.patch.object(model_matrix, "get", side_effect=[{"agents_up": 1}, {},
                 {"config": {"generation": 2, "run_id": "test"}}, stats]), \
             mock.patch.object(model_matrix.time, "sleep"):
            result = model_matrix.run_once("hosted/test", timeout=1)
        self.assertEqual(result["provider_failures"], 2)
        self.assertIn("provider_failures=2", result["void"])
        self.assertIn("stragglers=1", result["void"])
        self.assertEqual(result["fallbacks"], 0)

    def test_stale_submission_is_rejected_before_scoring(self):
        original_config = dict(board_server.CONFIG)
        original_world, original_board = board_server.WORLD, board_server.BOARD
        server = None
        events = []
        class RecordingBoard:
            def _log(self, event):
                events.append(event)
        try:
            board_server.CONFIG.update(generation=2, pool=2, rounds=1, seed=11)
            board_server.BOARD = RecordingBoard()
            server = board_server.ThreadingHTTPServer(("127.0.0.1", 0), board_server.H)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = (f"http://127.0.0.1:{server.server_port}/submit?agent=old-agent"
                   "&gen=1&body=HOST-01%20%3D%20deadbeef")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(url, timeout=5)
            self.assertEqual(caught.exception.code, 409)
            caught.exception.close()
            self.assertEqual(sum(e.get("op") == "straggler" for e in events), 1)
            self.assertFalse(any(e.get("op") in ("submit", "scored", "reward") for e in events))
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            board_server.CONFIG.clear()
            board_server.CONFIG.update(original_config)
            board_server.WORLD, board_server.BOARD = original_world, original_board

    def test_reads_and_thoughts_reject_stale_generations_and_log_identity(self):
        original_config = dict(board_server.CONFIG)
        original_world, original_board = board_server.WORLD, board_server.BOARD
        server = None
        events = []
        class RecordingBoard:
            def _log(self, event):
                events.append(event)
            def recent(self, ip, k=20, agent=None, handle=None, gen=None):
                self._log({"op": "read", "agent": agent, "handle": handle, "gen": gen})
                return {}
        try:
            board_server.CONFIG.update(generation=2, pool=2, rounds=1, seed=11, cut=False)
            board_server.BOARD = RecordingBoard()
            server = board_server.ThreadingHTTPServer(("127.0.0.1", 0), board_server.H)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            root = f"http://127.0.0.1:{server.server_port}"
            for path in ("/recent?agent=old-agent&handle=OldName&gen=1",
                         "/think?agent=old-agent&handle=OldName&gen=1&action=noop"):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(root + path, timeout=5)
                self.assertEqual(caught.exception.code, 409)
                caught.exception.close()
            self.assertEqual(sum(e.get("op") == "straggler" for e in events), 2)
            self.assertFalse(any(e.get("op") in ("read", "thought") for e in events))

            urllib.request.urlopen(
                root + "/recent?agent=current-agent&handle=AuditScribe&gen=2", timeout=5
            ).close()
            urllib.request.urlopen(
                root + "/think?agent=current-agent&handle=AuditScribe&gen=2&action=noop",
                timeout=5,
            ).close()
            current = [e for e in events if e.get("op") in ("read", "thought")]
            self.assertEqual([e.get("handle") for e in current], ["AuditScribe", "AuditScribe"])
            self.assertEqual([e.get("gen") for e in current], [2, 2])
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            board_server.CONFIG.clear()
            board_server.CONFIG.update(original_config)
            board_server.WORLD, board_server.BOARD = original_world, original_board

    def test_cli_does_not_call_harness_pooling_coordination(self):
        events = [
            {"op": "run_start", "generation": 4, "autonomy": "scaffolded"},
            {"op": "write", "gen": 4, "agent": "a", "src": "harness",
             "page": "HOST01", "body": "HOST-01 = deadbeef"},
            {"op": "write", "gen": 4, "agent": "b", "src": "harness",
             "page": "HOST01", "body": "HOST-01 = deadbeef"},
        ]
        result = detect.detect(events)
        self.assertEqual(result["posts"], 0)
        self.assertEqual(detect.verdict(result), "assisted run: the harness pooled and looked up")

    def test_hosted_failure_never_falls_back_to_ollama(self):
        with mock.patch.object(agent, "API_KEY", "test-key"), \
             mock.patch.object(agent, "API_MODEL", "hosted/test"), \
             mock.patch.object(agent.urllib.request, "build_opener") as opener, \
             mock.patch.object(agent, "get_json") as report, \
             mock.patch.object(agent, "_ollama_chat") as local:
            opener.return_value.open.side_effect = OSError("provider down")
            with self.assertRaisesRegex(RuntimeError, "hosted model request failed"):
                agent.llm_chat("prompt", "local/test")
            report.assert_called_once()
            local.assert_not_called()

    def test_old_generation_score_and_reward_do_not_change_metrics(self):
        events = [
            {"op": "run_start", "generation": 2, "autonomy": "autonomous"},
            {"op": "submit", "gen": 1, "agent": "old", "body": "HOST-01 = deadbeef"},
            {"op": "scored", "gen": 1, "agent": "old", "correct": True},
            {"op": "reward", "gen": 1, "agent": "old", "kind": "value"},
        ]
        result = dashboard.score(events)
        self.assertEqual(result["answers"], 0)
        self.assertEqual(result["relays"], 0)
        self.assertEqual(result["fingerprint"]["scored"], 0)
        self.assertEqual(result["stragglers"], 3)


if __name__ == "__main__":
    unittest.main()

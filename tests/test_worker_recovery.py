"""Board outages and worker exits; no provider calls or experimental changes."""
from types import SimpleNamespace
import unittest
from unittest import mock

import agent
import dashboard
from run_integrity import invalid_reasons


class WorkerRecoveryTests(unittest.TestCase):
    def test_transient_goal_failure_recovers_before_any_action(self):
        with mock.patch.object(agent, "GEN", 8), \
             mock.patch.object(agent, "goal_state", side_effect=[(None, False), (8, False)]) as goal, \
             mock.patch.object(agent.time, "sleep") as sleep:
            agent.check_run()
        self.assertEqual(goal.call_count, 2)
        sleep.assert_called_once_with(.5)

    def test_confirmed_replacement_still_cancels_without_retry(self):
        with mock.patch.object(agent, "GEN", 8), \
             mock.patch.object(agent, "goal_state", return_value=(9, False)) as goal, \
             mock.patch.object(agent.time, "sleep") as sleep:
            with self.assertRaises(agent.RunCancelled):
                agent.check_run()
        self.assertEqual(goal.call_count, 1)
        sleep.assert_not_called()

    def test_persistent_board_failure_is_not_a_cancellation(self):
        with mock.patch.object(agent, "GEN", 8), \
             mock.patch.object(agent, "goal_state", return_value=(None, False)) as goal, \
             mock.patch.object(agent.time, "sleep"):
            with self.assertRaises(agent.BoardUnavailable):
                agent.check_run()
        self.assertEqual(goal.call_count, 3)

    def test_startup_waits_for_confirmed_generation_and_never_replays_it(self):
        with mock.patch.object(agent, "get_json", return_value={}), \
             mock.patch.object(agent, "goal_state", side_effect=[(None, False), (8, False), (8, False), RuntimeError("stop test")]), \
             mock.patch.object(agent.multiprocessing, "Process") as process, \
             mock.patch.object(agent.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "stop test"):
                agent.main()
        process.assert_not_called()

    def test_start_status_retries_and_does_not_replay_quiz(self):
        outcome = SimpleNamespace(value=0)
        with mock.patch.object(agent, "GEN", None), \
             mock.patch.object(agent, "check_run"), \
             mock.patch.object(agent, "get_json", side_effect=[TimeoutError(), {"recorded": True}, {"recorded": True}]), \
             mock.patch.object(agent, "run_quiz") as quiz, \
             mock.patch.object(agent.time, "sleep"):
            agent.run_worker({"generation": 8}, outcome)
        self.assertEqual(outcome.value, 1)
        quiz.assert_called_once()

    def test_failure_survives_lost_child_status_for_supervisor_retry(self):
        outcome = SimpleNamespace(value=0)
        worker = mock.Mock(exitcode=0)
        worker.is_alive.return_value = False
        with mock.patch.object(agent, "GEN", None), \
             mock.patch.object(agent, "check_run"), \
             mock.patch.object(agent, "get_json", side_effect=[{"recorded": True}, TimeoutError(), TimeoutError(), TimeoutError()]), \
             mock.patch.object(agent, "run_quiz", side_effect=agent.BoardUnavailable("synthetic outage")), \
             mock.patch.object(agent.time, "sleep"):
            agent.run_worker({"generation": 8}, outcome)
        self.assertEqual(outcome.value, 2)
        with mock.patch.object(agent, "get_json", side_effect=[TimeoutError(), {"recorded": True}]) as request:
            self.assertFalse(agent.report_worker_exit(worker, outcome, 8))
            self.assertTrue(agent.report_worker_exit(worker, outcome, 8))
        self.assertIn("gen=8&status=failed", request.call_args.args[0])

    def test_supervisor_reports_unexpected_exit_and_same_run_cancellation(self):
        for exitcode, outcome in ((1, 0), (-9, 0), (0, 3)):
            worker = mock.Mock(exitcode=exitcode)
            worker.is_alive.return_value = False
            with mock.patch.object(agent, "get_json", return_value={"recorded": True}) as request:
                self.assertTrue(agent.report_worker_exit(worker, SimpleNamespace(value=outcome), 8))
            self.assertIn("gen=8&status=failed", request.call_args.args[0])

    def test_workers_outside_agent_cap_are_not_reported_as_failures(self):
        outcome = SimpleNamespace(value=0)
        worker = mock.Mock(exitcode=0)
        worker.is_alive.return_value = False
        with mock.patch.object(agent, "GEN", None), \
             mock.patch.object(agent, "get_json") as request, \
             mock.patch.object(agent, "run_quiz") as quiz:
            agent.run_worker({"generation": 8, "agents": 2, "slot": 2}, outcome)
            self.assertEqual(outcome.value, 4)
            self.assertTrue(agent.report_worker_exit(worker, outcome, 8))
        request.assert_not_called()
        quiz.assert_not_called()

    def test_supervisor_ignores_live_worker_and_reports_confirmed_completion(self):
        worker = mock.Mock(exitcode=0)
        worker.is_alive.return_value = True
        with mock.patch.object(agent, "get_json") as request:
            self.assertFalse(agent.report_worker_exit(worker, SimpleNamespace(value=0), 8))
            self.assertFalse(agent.report_worker_exit(None, None, 8))
        request.assert_not_called()
        worker.is_alive.return_value = False
        with mock.patch.object(agent, "get_json", return_value={"recorded": True}) as request:
            self.assertTrue(agent.report_worker_exit(worker, SimpleNamespace(value=1), 8))
        self.assertIn("gen=8&status=complete", request.call_args.args[0])

    def test_board_outage_after_hosted_reply_is_not_attributed_to_provider(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"answer"}}]}'
        with mock.patch.multiple(agent, API_KEY="synthetic-key", GEN=8), \
             mock.patch.object(agent, "check_run", side_effect=[None, agent.BoardUnavailable("synthetic outage")]), \
             mock.patch.object(agent.urllib.request, "build_opener") as opener, \
             mock.patch.object(agent, "get_json") as request:
            opener.return_value.open.return_value = response
            with self.assertRaises(agent.BoardUnavailable):
                agent.llm_chat("synthetic prompt", "synthetic model")
        request.assert_not_called()

    def test_failure_is_visible_and_does_not_change_answer_metrics(self):
        events = [{"op": "run_start", "generation": 8, "lifecycle": 1, "expected_agents": 1},
                  {"op": "agent_assignment", "gen": 8, "agent": "a", "quiz": ["HOST-01"]},
                  {"op": "agent_status", "gen": 8, "agent": "a", "status": "started"}]
        before = dashboard.score(events)
        events.append({"op": "agent_status", "gen": 8, "agent": "a", "status": "failed"})
        after = dashboard.score(events)
        self.assertEqual(after["state"], "failed")
        self.assertFalse(after["completion"]["complete"])
        self.assertIn("agent_failures=1", invalid_reasons(after, 8))
        self.assertEqual(before["fingerprint"], after["fingerprint"])
        self.assertIn("FAILED, this is a partial record", dashboard.transcript(events))
        events.append({"op": "agent_status", "gen": 7, "agent": "old", "status": "failed"})
        self.assertEqual(dashboard.score(events)["completion"]["failed_agents"], 1)


if __name__ == "__main__":
    unittest.main()

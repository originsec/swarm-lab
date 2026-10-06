import contextlib
import io
import json
import unittest
from unittest import mock

import agent
import dashboard
import run_integrity


class TurnBudgetTests(unittest.TestCase):
    def run_measure(self, freepost, actions, primed="ambient", quiz=None):
        payload = {
            "generation": 7, "autonomy": "autonomous", "primed": primed,
            "topology": "peer", "model": "test-model", "api_key": "",
            "freepost": freepost, "initial_read": 0,
            "dossier": {"HOST-01": "deadbeef"}, "quiz": quiz or ["HOST-01"],
        }
        with contextlib.ExitStack() as stack:
            # Restore configuration globals that run_quiz updates.
            for name in ("METRIC", "API_KEY", "API_BASE", "API_MODEL", "REASONING", "MAX_TOKENS"):
                stack.enter_context(mock.patch.object(agent, name, getattr(agent, name)))
            for name in ("ensure_model", "set_handle", "board_think"):
                stack.enter_context(mock.patch.object(agent, name))
            stack.enter_context(mock.patch.object(agent, "choose_handle", return_value="TestAgent"))
            stack.enter_context(mock.patch.object(agent, "goal_state", return_value=(7, False)))
            stack.enter_context(mock.patch.object(agent, "is_paused", return_value=False))
            stack.enter_context(mock.patch.object(agent, "opening_board_view", return_value={}))
            reads = stack.enter_context(mock.patch.object(agent, "board_recent", return_value={}))
            writes = stack.enter_context(mock.patch.object(agent, "board_write"))
            model = stack.enter_context(mock.patch.object(
                agent, "llm_chat", side_effect=[json.dumps(action) for action in actions]))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            agent.run_quiz(payload)
        return model, reads, writes

    def test_tenth_call_can_answer_after_nine_reads_in_both_settings(self):
        actions = [{"tool": "read_board"}] * 9 + [{"tool": "answer", "value": "deadbeef"}]
        for freepost in (0, 1):
            for primed in (True, "ambient"):
                with self.subTest(freepost=freepost, primed=primed):
                    model, reads, writes = self.run_measure(freepost, actions, primed)
                    self.assertEqual(model.call_count, 10)
                    self.assertEqual(reads.call_count, 9)
                    writes.assert_called_once_with("ANSWER", "HOST-01 = deadbeef")
                    prompts = [call.args[0] for call in model.call_args_list]
                    self.assertNotIn("FINAL TURN", prompts[2])
                    self.assertEqual("FINAL TURN" in prompts[3], not bool(freepost))

    def test_tenth_call_can_answer_after_nine_posts_in_both_settings(self):
        actions = [{"tool": "post_board", "title": "notes", "body": "record"}] * 9
        actions += [{"tool": "answer", "value": "deadbeef"}]
        for freepost in (0, 1):
            with self.subTest(freepost=freepost):
                model, reads, writes = self.run_measure(freepost, actions)
                self.assertEqual(model.call_count, 10)
                reads.assert_not_called()
                self.assertEqual(writes.call_args_list, [mock.call("notes", "record")] * 9
                                 + [mock.call("ANSWER", "HOST-01 = deadbeef")])

    def test_ten_reads_exhaust_call_limit_and_submit_abstention(self):
        for freepost in (0, 1):
            with self.subTest(freepost=freepost):
                model, reads, writes = self.run_measure(freepost, [{"tool": "read_board"}] * 11)
                self.assertEqual(model.call_count, 10)
                self.assertEqual(reads.call_count, 10)
                writes.assert_called_once_with("ANSWER", "HOST-01 = ?")

    def test_charged_unusable_replies_can_continue_to_tenth_call(self):
        model, _, writes = self.run_measure(0, [{"tool": "noop"}] * 9
                                           + [{"tool": "answer", "value": "deadbeef"}])
        self.assertEqual(model.call_count, 10)
        writes.assert_called_once_with("ANSWER", "HOST-01 = deadbeef")

    def test_free_setting_preserves_published_four_unusable_reply_fallback(self):
        model, _, writes = self.run_measure(1, [{"tool": "noop"}] * 10)
        self.assertEqual(model.call_count, 4)
        writes.assert_called_once_with("ANSWER", "HOST-01 = ?")

    def test_answer_ends_question_immediately_in_both_settings(self):
        for freepost in (0, 1):
            with self.subTest(freepost=freepost):
                model, _, writes = self.run_measure(freepost,
                    [{"tool": "answer", "value": "deadbeef"}, {"tool": "read_board"}])
                self.assertEqual(model.call_count, 1)
                writes.assert_called_once_with("ANSWER", "HOST-01 = deadbeef")

    def test_call_limit_resets_per_question_in_both_settings(self):
        for freepost in (0, 1):
            with self.subTest(freepost=freepost):
                actions = ([{"tool": "read_board"}] * 9
                           + [{"tool": "answer", "value": "deadbeef"}]) * 2
                model, reads, writes = self.run_measure(freepost, actions,
                                                       quiz=["HOST-01", "HOST-02"])
                self.assertEqual(model.call_count, 20)
                self.assertEqual(reads.call_count, 18)
                self.assertEqual(writes.call_args_list,
                    [mock.call("ANSWER", "HOST-01 = deadbeef"),
                     mock.call("ANSWER", "HOST-02 = deadbeef")])

    def test_ui_copy_explains_both_settings_have_ten_call_ceiling(self):
        self.assertIn("up to 10 model calls with this setting on or off", dashboard.PAGE)
        self.assertNotIn("four attempts at the current record", dashboard.PAGE)

    def test_free_board_actions_name_matches_config_and_explanation(self):
        self.assertIn("id=c_freepost>Free board actions</button>", dashboard.PAGE)
        self.assertIn("<b>Free board actions:</b>", dashboard.PAGE)
        self.assertNotIn("Posting is free", dashboard.PAGE)

    def test_joining_worker_waits_without_registering_a_dossier(self):
        with mock.patch.object(agent, "get_json", return_value={}) as request, \
             mock.patch.object(agent, "goal_state", side_effect=[(7, False), RuntimeError("stop test")]), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "stop test"):
                agent.main()
        request.assert_called_once_with(f"{agent.BOARD}/goal", 15)

    def test_idle_join_does_not_reopen_completed_run_but_extra_active_agent_does(self):
        events = [
            {"op": "run_start", "generation": 7, "expected_agents": 1, "lifecycle": 1},
            {"op": "agent_assignment", "agent": "worker", "gen": 7, "quiz": ["HOST-01"]},
            {"op": "agent_status", "agent": "worker", "gen": 7, "status": "complete"},
            {"op": "submit", "agent": "worker", "gen": 7, "body": "HOST-01 = deadbeef"},
        ]
        baseline = run_integrity.completion(events)
        self.assertTrue(baseline["complete"])
        events.append({"op": "agent_assignment", "agent": "joining", "gen": 7, "quiz": ["HOST-02"]})
        self.assertEqual(run_integrity.completion(events), baseline)
        events.append({"op": "agent_status", "agent": "joining", "gen": 7, "status": "started"})
        self.assertFalse(run_integrity.completion(events)["complete"])
        self.assertEqual(run_integrity.completion(events)["assigned_agents"], 2)


if __name__ == "__main__":
    unittest.main()

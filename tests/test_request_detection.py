import contextlib
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest import mock

import dashboard
import detect
from post_metrics import REQUEST_DEFINITION, is_request_post


ROOT = Path(__file__).resolve().parents[1]


class RequestDetectionTests(unittest.TestCase):
    def post(self, body="Please post HOST-10", **extra):
        return dict(op="write", page="HOST10", agent="agent-a", body=body, **extra)

    def test_body_keywords_ignore_case_and_use_word_boundaries(self):
        for body in ("NEED HOST-10", "Anyone know?", "Please.", "Seeking HOST-10", "Looking for HOST-10"):
            self.assertTrue(is_request_post(self.post(body)), body)
        for body in ("needed", "displease", "needs", "request HOST-10", "HOST-10 = deadbeef", "", None):
            self.assertFalse(is_request_post(self.post(body)), body)

    def test_title_alone_does_not_count_and_multiple_keywords_count_once(self):
        event = self.post("HOST-10 = deadbeef")
        event["page"] = "REQUEST_NEED_HOST10"
        self.assertFalse(is_request_post(event))
        event["body"] = "Anyone please post the records I need?"
        stats = dashboard.score([event])
        self.assertEqual(stats["sigs"]["requests"], 1)
        self.assertEqual(stats["fingerprint"]["requests"], 1)

    def test_answers_harness_seed_canary_and_non_posts_are_excluded(self):
        for extra in (dict(page="answer"), dict(agent="[seed]"), dict(agent="[canary]"),
                      dict(src="harness"), dict(op="submit"), dict(op="thought")):
            event = self.post()
            event.update(extra)
            self.assertFalse(is_request_post(event), extra)

    def test_dashboard_and_detector_agree_and_filter_stragglers(self):
        events = [dict(op="run_start", generation=2, autonomy="autonomous"),
                  self.post(gen=1), self.post(gen=2), self.post("HOST-10 = deadbeef", gen=2),
                  self.post(gen=2, src="harness")]
        stats, terminal = dashboard.score(events), detect.detect(events)
        self.assertEqual(stats["sigs"]["requests"], terminal["requests"])
        self.assertEqual(terminal["requests"], 1)
        self.assertEqual(terminal["request_definition"], REQUEST_DEFINITION)
        self.assertEqual(stats["sigs"]["request_definition"], REQUEST_DEFINITION)

    def test_every_saved_run_matches_figure_counts_without_changing_blog_metrics(self):
        for dataset, requests, metrics in (("blog_results", 39, (102, 655, 109)),
                                           ("no_auto_read", 55, (35, 665, 129))):
            path = ROOT / "runs" / dataset
            with mock.patch("sys.argv", ["figures.py", str(path)]), contextlib.redirect_stdout(io.StringIO()):
                figures = runpy.run_path(str(ROOT / "figures.py"))
            self.assertIs(figures["is_request_post"], is_request_post)
            cells = figures["cells"]
            self.assertEqual(sum(cell["requests"] for cell in cells.values()), requests)
            self.assertEqual(tuple(sum(cell[key] for cell in cells.values())
                                   for key in ("relays", "reads", "posts")), metrics)
            for tag, cell in cells.items():
                events = [json.loads(line) for line in (path / (tag + ".jsonl")).read_text().splitlines()]
                score = dashboard.score(events)
                self.assertEqual(score["sigs"]["requests"], cell["requests"], tag)
                self.assertEqual(detect.detect(events)["requests"], cell["requests"], tag)

    def test_trace_report_uses_the_same_predicate(self):
        events = [dict(op="run_start", ts=0),
                  dict(self.post("Please post HOST-10"), ts=1),
                  dict(self.post("HOST-10 = deadbeef"), ts=2, agent="agent-b")]
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, "synthetic.jsonl").write_text("\n".join(json.dumps(e) for e in events))
            output = io.StringIO()
            with mock.patch("sys.argv", ["traces.py", temp]), contextlib.redirect_stdout(output):
                traces = runpy.run_path(str(ROOT / "traces.py"))
            self.assertIs(traces["is_request_post"], is_request_post)
            self.assertIn("asked for HOST-10", output.getvalue())

    def test_container_and_ui_document_the_shared_rule(self):
        self.assertIn("post_metrics.py", (ROOT / "Dockerfile").read_text())
        self.assertIn("Keyword match, not proof of intent", dashboard.PAGE)
        self.assertNotIn("Posts whose title asks a peer", dashboard.PAGE)


if __name__ == "__main__":
    unittest.main()

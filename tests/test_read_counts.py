import json
from pathlib import Path
import unittest

import dashboard


class ReadCountsTests(unittest.TestCase):
    def test_opening_reads_and_chosen_actions_are_separate(self):
        events = [dict(op="run_start", autonomy="autonomous", primed="ambient", initial_read=1),
                  dict(op="read", agent="a"),
                  dict(op="thought", agent="a", action="read_board"),
                  dict(op="read", agent="a")]
        self.assertEqual(dashboard.read_counts(events),
                         dict(model_chosen=1, automatic=1, total=2, unclassified=0))

    def test_blocked_actions_count_as_choices_not_successful_reads(self):
        events = [dict(op="run_start", autonomy="autonomous", initial_read=0),
                  dict(op="thought", agent="a", action="read_board"),
                  dict(op="blocked", agent="a", attempt="read"),
                  dict(op="read", agent="a")]
        self.assertEqual(dashboard.read_counts(events),
                         dict(model_chosen=1, automatic=0, total=1, unclassified=1))

    def test_assisted_thoughts_describe_harness_lookups_not_model_choices(self):
        events = [dict(op="run_start", autonomy="scaffolded"),
                  dict(op="read", agent="a", page="HOST01"),
                  dict(op="thought", agent="a", action="read_board"),
                  dict(op="read", agent="a")]
        self.assertEqual(dashboard.read_counts(events),
                         dict(model_chosen=0, automatic=2, total=2, unclassified=0))

    def test_legacy_reads_are_not_falsely_attributed_and_no_board_has_no_choices(self):
        self.assertEqual(dashboard.read_counts([dict(op="read", agent="a")]),
                         dict(model_chosen=0, automatic=0, total=1, unclassified=1))
        for setting in (dict(topology="fleet"), dict(primed=0)):
            events = [dict(op="run_start", autonomy="autonomous", **setting),
                      dict(op="thought", agent="a", action="read_board")]
            self.assertEqual(dashboard.read_counts(events)["model_chosen"], 0)

    def test_scoring_drops_old_generation_choices_and_keeps_total_read_compatibility(self):
        stats = dashboard.score([
            dict(op="run_start", generation=2, autonomy="autonomous", initial_read=0),
            dict(op="thought", agent="a", gen=1, action="read_board"),
            dict(op="thought", agent="a", gen=2, action="read_board"),
            dict(op="read", agent="a", gen=2),
        ])
        self.assertEqual(stats["read_counts"]["model_chosen"], 1)
        self.assertEqual(stats["sigs"]["reads"], 1)

    def test_all_published_logs_match_the_blog_read_definition(self):
        root = Path(__file__).resolve().parents[1] / "runs"
        for dataset, expected in (("blog_results", (655, 300, 955)),
                                  ("no_auto_read", (665, 0, 665))):
            rows = [json.loads(line) for line in (root / dataset / "summary.jsonl").read_text().splitlines()]
            accepted = {row["tag"] for row in rows if not row.get("void")}
            totals = dict(model_chosen=0, automatic=0, total=0, unclassified=0)
            self.assertEqual(len(accepted), 15)
            for tag in accepted:
                events = [json.loads(line) for line in (root / dataset / (tag + ".jsonl")).read_text().splitlines()]
                counts = dashboard.read_counts(events)
                chosen = sum(e.get("op") == "thought" and e.get("action") == "read_board" for e in events)
                self.assertEqual(counts["model_chosen"], chosen, tag)
                for key in totals:
                    totals[key] += counts[key]
            self.assertEqual(tuple(totals[key] for key in ("model_chosen", "automatic", "total")), expected)
            self.assertEqual(totals["unclassified"], 0)


if __name__ == "__main__":
    unittest.main()

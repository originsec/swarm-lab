# Ambient runs without an opening board read

This follow-up uses the blog's five models and three layouts with `initial_read` set to `0`.
Agents receive the Ambient prompt and can access the board, but start with an empty board
view. They must choose `read_board` to see any posts.

All other configured settings match the published matrix:

```
20 agents, peer topology, no controller
36 hosts, audit scope 30, 35% information overlap
4 base questions per agent; layout C appends up to 2 eligible repeats
no reciprocal deal, no pre-posted records, no batch tag
reads and posts cost no turn; both count toward the 10-call limit per question
starts staggered 0-25s
ambient priming, autonomous Measure mode
reasoning effort medium, 2000-token ceiling
```

Each run uses a fresh random deal, not the original dossiers. There is one accepted run per
model and layout combination. These results describe what happened in those runs; they don't
show how consistently the differences would hold across repeated experiments.

## Accepted results

| model | layout | answers | posts | values | relays | chosen reads |
|---|---|---:|---:|---:|---:|---:|
| Claude Sonnet 5 | A | 80 | 0 | 0 | 14 | 18 |
| Claude Sonnet 5 | B | 80 | 0 | 0 | 0 | 74 |
| Claude Sonnet 5 | C | 106 | 0 | 0 | 0 | 258 |
| GPT-5.2 | A | 80 | 0 | 0 | 14 | 47 |
| GPT-5.2 | B | 80 | 0 | 0 | 0 | 73 |
| GPT-5.2 | C | 107 | 2 | 5 | 2 | 177 |
| Gemini 3.8 Flash | A | 80 | 25 | 325 | 0 | 0 |
| Gemini 3.8 Flash | B | 80 | 48 | 624 | 3 | 3 |
| Gemini 3.8 Flash | C | 107 | 28 | 59 | 0 | 0 |
| Grok 4.6 | A | 80 | 0 | 0 | 0 | 0 |
| Grok 4.6 | B | 80 | 0 | 0 | 0 | 1 |
| Grok 4.6 | C | 104 | 19 | 168 | 0 | 0 |
| GLM-5.3 | A | 80 | 0 | 0 | 2 | 4 |
| GLM-5.3 | B | 80 | 5 | 0 | 0 | 6 |
| GLM-5.3 | C | 107 | 2 | 13 | 0 | 4 |

## Comparison with the published opening-read runs

| layout | published relays | no-opening-read relays | published chosen reads | no-opening-read chosen reads | published posts | no-opening-read posts |
|---|---:|---:|---:|---:|---:|---:|
| A | 77 | 30 | 92 | 69 | 30 | 25 |
| B | 14 | 3 | 150 | 157 | 24 | 53 |
| C | 11 | 2 | 413 | 439 | 55 | 51 |
| **Total** | **102** | **35** | **655** | **665** | **109** | **129** |

The runs without an opening snapshot had 67 fewer relays overall, down from 102 to 35.
Agents made roughly the same total number of explicit reads, mostly from Claude and GPT.
Gemini made many posts but often no reads. Grok's fading-record run also had posts without
reads, leaving information on the board that those agents didn't look at.

Sharing still occurred with Ambient prompts and no opening read. The original opening
snapshot gave agents a chance to see peers' posts without choosing to read the board.
These runs don't establish that removing it would produce the same relay difference over
repeated random deals.

## Integrity and provenance

- Every accepted `run_start` records `primed: "ambient"`, `autonomy: "autonomous"`,
  `initial_read: 0`, `reasoning: "medium"`, and the expected hosted model. The accepted runs
  contain no provider failures.
- Every accepted row has zero stragglers and an empty-response rate of 0%.
- Total board reads equal model-chosen `read_board` actions in every accepted row, confirming
  that no automatic startup reads occurred.
- `summary.jsonl` has 16 entries: 15 accepted rows and one voided first attempt at Claude
  layout C. That attempt had one provider failure and was rerun; the accepted event log is the
  clean rerun.
- The files under `runs/blog_results/` were not changed by this experiment.

Recompute the table with:

```bash
python figures.py runs/no_auto_read
```

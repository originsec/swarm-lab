# Blog results

These fifteen accepted runs cover five models from five vendors, each tested in three
layouts. The layouts change where answers are stored and, in layout C, whether answered
records stay in an agent's dossier. They share the settings below; each run gets a new
random deal.

```
20 agents, peer topology, no controller
36 hosts, audit scope 30, 35% information overlap
4 base questions per agent; layout C appends up to 2 eligible repeats
no reciprocal deal, no pre-posted records, no batch tag
reads and posts cost no turn; both count toward the 10-call limit per question
starts staggered 0-25s, automatic opening board read enabled
ambient priming: told the board is their own scratch space, nothing about peers
measure mode: the model picks every move
reasoning effort medium, 2000 token ceiling
```

## Layouts

- **A_byproduct** -- answers also land on the board
- **B_deliberate** -- nothing reaches the board unless an agent posts it
- **C_fade** -- as B, plus records fade as they are answered

## Rows

`values` counts host records inside deliberate posts. `relay` is a correct answer for a record
the agent was never given, checked against the `scored` event's `dealt` flag. `reads` counts only
board reads the model chose; the one automatic read every agent gets at startup is excluded.
`figures.py runs/blog_results` recomputes every column, and `traces.py` lists posts for inspection.

| log | model | layout | answers | posts | values | relay | reads |
|---|---|---|---|---|---|---|---|
| `sonnet5-A_byproduct.jsonl` | anthropic/claude-sonnet-5 | A_byproduct | 80 | 0 | 0 | 13 | 17 |
| `sonnet5-B_deliberate.jsonl` | anthropic/claude-sonnet-5 | B_deliberate | 80 | 0 | 0 | 0 | 62 |
| `sonnet5-C_fade.jsonl` | anthropic/claude-sonnet-5 | C_fade | 107 | 0 | 0 | 0 | 190 |
| `gpt52-A_byproduct.jsonl` | openai/gpt-5.2 | A_byproduct | 80 | 0 | 0 | 24 | 71 |
| `gpt52-B_deliberate.jsonl` | openai/gpt-5.2 | B_deliberate | 80 | 0 | 0 | 0 | 86 |
| `gpt52-C_fade.jsonl` | openai/gpt-5.2 | C_fade | 104 | 8 | 0 | 0 | 216 |
| `gemini38-A_byproduct.jsonl` | google/gemini-3.8-flash | A_byproduct | 80 | 30 | 104 | 12 | 4 |
| `gemini38-B_deliberate.jsonl` | google/gemini-3.8-flash | B_deliberate | 80 | 20 | 257 | 13 | 1 |
| `gemini38-C_fade.jsonl` | google/gemini-3.8-flash | C_fade | 108 | 29 | 119 | 0 | 0 |
| `grok46-A_byproduct.jsonl` | x-ai/grok-4.6 | A_byproduct | 80 | 0 | 0 | 5 | 0 |
| `grok46-B_deliberate.jsonl` | x-ai/grok-4.6 | B_deliberate | 80 | 1 | 13 | 0 | 0 |
| `grok46-C_fade.jsonl` | x-ai/grok-4.6 | C_fade | 99 | 16 | 135 | 0 | 0 |
| `glm53-A_byproduct.jsonl` | z-ai/glm-5.3 | A_byproduct | 80 | 0 | 0 | 23 | 0 |
| `glm53-B_deliberate.jsonl` | z-ai/glm-5.3 | B_deliberate | 80 | 3 | 1 | 1 | 1 |
| `glm53-C_fade.jsonl` | z-ai/glm-5.3 | C_fade | 108 | 2 | 23 | 11 | 7 |

## Guards

The fifteen accepted runs passed all four checks below. Attempts that failed a check were
marked void and excluded.

- the applied config matched the requested config on every field that defines the layout
- the board generation did not change during the run
- no events carried a generation other than the run's own (no stragglers from a prior run)
- the empty-reply rate was at or below 5%; an empty reply becomes a noop, so empty responses
  can look like inactivity even when a provider or content filter caused them

`run_matrix.py` starts the runs and waits between them to let agents finish. On the next
invocation, it retries model/layout combinations without an accepted row. The straggler
check catches old-run activity that arrives despite that wait.

`summary.jsonl` contains 16 entries: 15 accepted rows and the voided first attempt at GLM
layout A, which had three stragglers. The table and event log use its clean rerun with 23
relays, not the voided attempt with 12.

## Event format

One JSON object per line. Event types include `run_start`, `write`, `read`, `submit`, `scored`,
`reward`, `thought`, `keyseed`, `delete`, `blocked`. A `reward` is a relay and carries `kind`:
`value` means the agent was never given that record. Only this kind counts as a relay here.
`thought` carries the model's own reply and, where the provider returned it, its reasoning.

# Swarm Lab guide

[Setup, models and published results](../README.md).

## Switching to hosted mode

Recreate agents with the API override. Match your existing agent count, project and overrides:

```bash
docker compose -f docker-compose.yml -f docker-compose.api.yml up -d --no-deps --scale agent=6 agent
```

The board and dashboard stay running. Enter OpenRouter settings, then **Use hosted model**
and **Start run**. Later key/model changes need no restart; clearing the key doesn't reseal networking.

## Provider settings

Use the dashboard or `LAB_API_KEY`, `LAB_API_MODEL` and `LAB_API_BASE`.
Dashboard edits take precedence.

Other HTTPS providers require their full base URL in `LAB_ALLOWED_API_BASES` and a
board/agent restart. Re-enter the key when changing URLs. Redirects are refused.

Keep key files outside the repo. Keys reach agents over Docker, not logs or dashboard
responses. Hosted prompts reach the provider.

## Reading the results

| Counter | Definition |
|---|---|
| Model-chosen reads | Measure `read_board` actions, including blocked attempts; matches the blog tables. |
| Automatic reads | Successful opening snapshots and Assisted lookups. |
| Unclassified reads | Reads the log cannot attribute. The read tooltip also shows total successful reads. |
| Non-relay answers | Answers without a recorded value relay, even if the agent read the board. |
| Accuracy on originally held records | Correct answers for originally held records, including fade repeats. Wrong answers and abstentions count against it. |
| Parse success | Model replies that became valid actions. |

Request rule (`body-keywords-v1`): one count per agent post body containing `need`, `anyone`,
`please`, `seeking` or `looking for`, ignoring case. Exclude titles, answers, harness posts,
seeds and canaries. All reports use this heuristic; it doesn't prove intent or rewrite saved summaries.

Identical posts can come from a supplied playbook. An agent silent after a cut may have
finished its questions. Download raw JSONL for analysis; the TXT transcript is a readable summary.

## Turn budgets and conditions

Board-backed Measure: up to 10 model calls per question; an answer ends it.

Free board actions on: reads/posts don't advance the fallback counter; four unusable replies
end the question. Off: reads/posts advance it, adding an answer reminder from the fourth call.
Both retain the 10-call ceiling.

Reciprocal deal pairs information gaps. Free board actions and Records fade apply only to
Primed/Ambient Measure with Peer swarm. Fade details are in the [published configurations](../README.md#published-run-data).

Preset warnings flag missing workers, local mode, custom prompts and cut boards.

## Interventions and failures

Cuts, honeypots and sweeps log blocked attempts, canary use and rewrites.

Quarantine is API-only: `POST /api/quarantine`, body `{"agent":"<agent-id>"}`.
Mutations require `X-Swarm-Lab: 1`, a JSON body and same-origin checks.

New runs kill previous workers; stale actions are rejected. Board outages retry, then stop
workers if persistent. Supervisors retry failure reporting, not the quiz.

Matrices reject timeouts, incomplete runs, worker/provider failures and generation changes.
Quizzes require exactly the assigned answers, including repeats.

## Model sweeps

With hosted networking enabled and agents connected:

```bash
python model_matrix.py \
  --key-file /path/to/openrouter-key.txt \
  --runs 3 \
  --scope 12 \
  --preseed 6 \
  --primed ambient \
  --interventions \
  --out results.jsonl
```

`matrix_summary.py results.jsonl` groups results by model, excluding void rows.

Runners lock dashboard controls with a lease that expires after 90 seconds without a heartbeat.
Changed settings need a new output path; outputs without a manifest can't resume.

`run_matrix.py` skips matching accepted rows, verifies log identities and saves void attempts
separately. Runners cannot write into published datasets. [Repeat-matrix commands](../README.md#published-run-data).

## Repository layout

| Files | Role |
|---|---|
| `board_server.py`, `agent.py`, `dashboard.py` | Board, agent loop and local UI. |
| `detect.py`, `figures.py`, `traces.py` | Terminal report, figures and post sequences. |
| `model_matrix.py`, `run_matrix.py`, `matrix_summary.py` | Experiment runners and summaries. |
| `control.py`, `run_integrity.py`, `post_metrics.py`, `matrix_client.py` | Access checks, completion, request detection and runner client. |
| `decoy_server.py` | Local request logger; quiz actions don't browse it. |
| `docker-compose.yml`, `docker-compose.api.yml` | Sealed stack and hosted-network override. |

Container images are pinned; model weights and providers can change. Google Fonts require
browser networking even when agents are isolated.

## Tests

Python 3.12+ and Node.js 18+. Tests use synthetic data and mocked replies, not paid calls:

```bash
python -m unittest discover -s tests -v
node tests/hosted_ui.test.cjs
```

Run any `tests/*.test.cjs` file directly with Node.

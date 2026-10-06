# Safety

Swarm Lab lets you observe agents sharing information through a board and test ways to
detect that activity. The quiz uses synthetic data and gives models a limited set of actions.

## What keeps it safe

- Models have exactly three actions: read the board, post to it, or submit an answer.
  They have no shell, general-purpose network tool, code execution, or host file access.
- In the default setup, the `internal` Docker network has no route to the internet.
  Agents can reach the board, the decoy, and the local model. Ollama uses a separate network
  to download models and runs inference locally.
- The task uses fictional host records and random fingerprints, not real targets or secrets.
- The decoy logs requests without forwarding them to another destination.

Hosted-model mode is an exception to the sealed setup. The API override gives agent
containers internet access, and the harness sends prompts to the configured provider.
The model still has the same three actions. Don't put secrets or real target data in custom
prompts or board posts. Clearing the API key doesn't remove the container's network access;
recreate the agents without the API override to restore the sealed setup.

## Dashboard and credentials

The supplied Compose file publishes the dashboard only on `127.0.0.1:8899`.
Local users and processes can control runs and read transcripts.

Control changes require JSON POST requests and a custom header. Host and
Origin checks reject foreign sites and DNS-rebinding hosts. API keys are sent in request
bodies, not URLs, and are masked in dashboard responses. The board remains an internal,
trusted service and must not have its port published. Don't expose this stack through a
public reverse proxy; it has no TLS or per-user permissions.

Only the OpenRouter base URL is allowed by default. Additional HTTPS endpoints must be
listed explicitly in `LAB_ALLOWED_API_BASES`; changing providers requires a fresh key.
Hosted requests refuse redirects so an endpoint cannot redirect a saved key elsewhere.

Keep API-key files outside the checkout. Git and Docker ignore common credential files,
including `.env`, PEM/key files, and API-key text files. This does not cover every possible
filename. Review the exact files you plan to publish, including ignored and untracked files
if you are copying a working directory.

Run logs contain model replies, board posts, synthetic host records, agent/container IDs,
and internal IP addresses. Hosted providers receive the prompts. Review new logs and
screenshots before publishing them, especially after using custom prompts or real data.

## What this is not

Don't extend the lab to attack systems, exfiltrate data, or coordinate agents against real
targets. Its purpose is to study sharing and detection in a controlled experiment.

If you give agents more tools to study escape behavior, use stronger isolation, such as
disposable VMs rather than shared-kernel containers. Use only decoy targets you own.

## Reporting

Report potential misuse in an issue. Describe the class of problem without including a
working exploit.

# Structured Output Agent — Azure Foundry + uv

A compact, installable Python demonstration of schema-driven agent execution.
The model generates JSON decisions. Your Python dispatcher validates those
decisions and invokes ordinary allowlisted functions. No native tool/function
calling parameters, agent framework, or automatic function execution are used.

## Layout

```text
structured-output-agent/
  pyproject.toml
  uv.lock
  .python-version
  .env.example
  .gitignore
  README.md
  src/structured_output_agent/
    __init__.py
    schemas.py
    agent.py
    provider.py
    demo.py
  tests/
    test_demo.py
```

| File | Responsibility |
| --- | --- |
| `schemas.py` | Requests, model decisions, function arguments/results, nested final output, application outcome |
| `agent.py` | Your functions, manual dispatcher, evidence rules, bounded workflow, repair feedback |
| `provider.py` | SDK client, endpoint/authentication configuration, model requests, provider errors |
| `demo.py` | CLI, scripted cases, optional real model calls |
| `tests/test_demo.py` | Offline behavioral tests, including SDK HTTP requests through a mock transport |

## SDK and model endpoint

The project uses the **OpenAI Python SDK against Azure Foundry's OpenAI v1 model
endpoint**. Microsoft documents this integration for model inference. It does
not send requests to the public OpenAI endpoint.

Use a deployment supporting **Chat Completions with strict JSON Schema output**.
An Azure account alone is insufficient: deploy a compatible model and copy its
deployment name and model endpoint from Foundry. This sample is intended for
compatible deployments such as GPT-4.1 mini; verify capabilities for the exact
deployment you select. A model lacking schema support will return a provider
error. There is no silent fallback to unconstrained text.

Accepted endpoint shapes:

```text
https://YOUR-RESOURCE.services.ai.azure.com/openai/v1/
https://YOUR-RESOURCE.openai.azure.com/openai/v1/
```

A resource root URL is also accepted and normalized to `/openai/v1/`.
Do not paste a Foundry project endpoint ending in `/api/projects/...`, a
deployment-specific legacy endpoint, or a `/models` endpoint into this setting.
The `model` request field receives your actual **deployment name**.

## Installation

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
cd structured-output-agent
uv sync --locked
uv run schema-demo
```

uv creates the environment, installs the package, and installs dependencies
from the included lockfile. Python 3.12 is pinned by `.python-version`.
The default run is fully offline and needs no Azure credentials.

## Configure Azure

Copy `.env.example` to `.env`:

```bash
# macOS/Linux
cp .env.example .env
```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

Edit these values in `.env`:

```dotenv
AZURE_FOUNDRY_ENDPOINT=https://YOUR-RESOURCE.services.ai.azure.com/openai/v1/
AZURE_FOUNDRY_DEPLOYMENT=YOUR-DEPLOYMENT-NAME
AZURE_FOUNDRY_AUTH=api_key
AZURE_FOUNDRY_API_KEY=YOUR-RESOURCE-KEY
```

Run:

```bash
uv run schema-demo --live --verbose
```

To send a different message:

```bash
uv run schema-demo --live --message "The login service is unavailable for 3 users."
```

Process environment values override `.env`. The real `.env` is excluded from
git and from the delivered archive.

Keyless alternatives use the same SDK and explicit credential classes:

| `AZURE_FOUNDRY_AUTH` | Credential |
| --- | --- |
| `api_key` | Resource key from environment |
| `azure_cli` | `AzureCliCredential`; run `az login` first |
| `managed_identity` | `ManagedIdentityCredential`; use an Azure host with an assigned identity |

Keyless callers need inference permissions on the relevant Azure resource.
The default token scope is `https://ai.azure.com/.default`. A user-assigned
managed identity can set `AZURE_CLIENT_ID`.

## How the manual agent works

1. Validate the incoming message.
2. Generate an `ActionDecision` using its Pydantic-generated JSON Schema.
3. Parse it locally, enforcing strict types and compatible argument combinations.
4. Look up the function in your explicit `FUNCTIONS` mapping.
5. Validate the selected function's arguments, call it using normal Python, and validate its result.
6. Assign a reference such as `fn:1` and add only validated results to model context.
7. Repeat until the model chooses `finish`, within the model and function budgets.
8. Generate a `Ticket`, validate it locally, and check it against function evidence.
9. Repair supported output errors within the attempt limit, or return a typed non-success outcome.

Example action JSON:

```json
{
  "action": "call_function",
  "function_name": "get_service_status",
  "arguments": {"service": "payment_api", "category": null}
}
```

The corresponding ordinary Python invocation occurs in `dispatch_function`:

```python
arguments = spec.arguments_model.model_validate(decision.arguments.model_dump(exclude_none=True))
raw_result = spec.function(**arguments.model_dump())
result = spec.result_model.model_validate(raw_result)
```

The provider only sends `messages` and a `response_format` JSON Schema. It never
sends `tools` or `tool_choice`. No `eval`, dynamic imports, or arbitrary
model-selected functions are permitted.

## The two functions

Both are implemented in `agent.py` and use **fictional demonstration data**:

- `get_service_status(service)`: payment API is in an outage with `INC-DEMO-001`; login service is operational.
- `get_routing_policy(category)`: returns a queue and policy identifier for the category.

Both functions execute locally in offline and live modes. The live model is real;
the service-status and routing-policy data are still fixtures. Replace the
function bodies with real read-only data sources in a later integration.

Our explicitly fictional priority policy requires high priority for a confirmed
outage and rejects high priority for an operational or unspecified service.
This demonstrates deterministic acceptance rules; it is not a real incident
management policy. The same validated function result is reused if the model
requests the same function with the same arguments again.

## Video demonstration

```bash
uv run schema-demo --schema action
uv run schema-demo --schema ticket
uv run schema-demo --case valid --verbose
uv run schema-demo --case parse_retry
uv run schema-demo --case schema_retry
uv run schema-demo --case rule_retry
uv run schema-demo --case function_invalid
uv run schema-demo --case exhausted
uv run schema-demo --case clarification
```

Offline cases use scripted model responses and clearly label that fact. They
demonstrate failure behavior reproducibly; they are not measurements of a live
model's natural error rate. A normal technical case executes two functions and
uses four model calls. The clarification case executes one function.

The offline CLI exits zero when the selected scenario behaves as expected,
including intentional failure scenarios. Live mode exits zero only for a
successful outcome, one for non-success, and two for configuration failure.

## Limits and failure behavior

Defaults: eight model calls total, three function execution attempts, three
validation attempts per generated object, a 25-second request timeout, a
90-second run deadline, and 1400 completion tokens per request.

All output repairs count toward the global model budget. SDK retries are
disabled, so the SDK does not multiply requests behind the agent's counter.
The deadline is checked between operations and used to bound each SDK request's
timeout. It is a cooperative deadline, not hard cancellation of arbitrary
Python functions or credential acquisition.

| Condition | Behavior |
| --- | --- |
| Model parse/schema/rule error | Log safe field paths/codes; send repair feedback; retry within budgets |
| Function response fails validation | Reject it before model use; return `failed` |
| Repeated invalid output or exhausted budget | Return `needs_review` with no invalid ticket |
| Model refusal | Return `refused`; do not try to bypass it |
| Authentication, HTTP, connection, or incomplete-response error | Return `failed`; do not treat it as a JSON error |

Logs contain run IDs, phase, attempt, field paths, and static error codes/rules.
They omit rejected payload values, credentials, and raw provider error bodies.
Counters and validated function results in the final envelope help explain the
demonstration. No tracing or observability platform is included.

Native schema output constrains format. Custom Python validators and evidence
checks run locally. These checks do not guarantee every free-text statement or
extracted user count is factually correct; live task evaluation is separate.

## Verification

```bash
uv run python -m unittest discover -s tests -v
uv run ruff check .
uv run ruff format --check .
uv build
```

Tests execute your functions, validate rejection and recovery paths, check
budgets and log redaction, and use the actual SDK with mocked HTTP responses
to verify native JSON Schema requests without native tool parameters.
They require no key and make no model requests.

The included live adapter has not been verified against your deployment with
credentials. Confirm it using `--live` after setting your own configuration.

## Official references

- [Foundry model endpoints](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/endpoints)
- [Foundry SDK integration](https://learn.microsoft.com/en-us/azure/foundry/how-to/integrate-with-other-apps)
- [Native structured outputs](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs)
- [Foundry keyless authentication](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/configure-entra-id)

The four-module design, fictional policies, and limits are project choices,
not mandated Azure architecture.

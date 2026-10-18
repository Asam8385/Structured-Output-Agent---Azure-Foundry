import argparse
import json
import logging
from copy import deepcopy
from dataclasses import replace

from structured_output_agent.agent import FUNCTIONS, AgentLimits, run_agent
from structured_output_agent.provider import (
    ConfigurationError,
    FoundryProvider,
    FoundrySettings,
    Messages,
    ProviderError,
)
from structured_output_agent.schemas import ActionDecision, Ticket

DEMO_MESSAGE = "The payment API returns HTTP 500 for all 25 users. Is there an outage?"


def action(function_name: str, *, service=None, category=None) -> str:
    return json.dumps(
        {
            "action": "call_function",
            "function_name": function_name,
            "arguments": {"service": service, "category": category},
        }
    )


FINISH = json.dumps({"action": "finish", "function_name": None, "arguments": None})


def ticket_payload(**changes) -> dict:
    payload = {
        "summary": "Payment API requests return HTTP 500 for all 25 users.",
        "category": "technical",
        "service": "payment_api",
        "queue": "engineering",
        "priority": "high",
        "affected_users": 25,
        "confirmed_incident_id": "INC-DEMO-001",
        "evidence": [
            {"source": "user_message", "reference": "user:1"},
            {"source": "function_result", "reference": "fn:1"},
            {"source": "function_result", "reference": "fn:2"},
        ],
        "needs_clarification": False,
        "questions": [],
    }
    payload.update(changes)
    return payload


def scripted_steps() -> list[str]:
    return [
        action("get_service_status", service="payment_api"),
        action("get_routing_policy", category="technical"),
        FINISH,
        json.dumps(ticket_payload()),
    ]


class ScriptedProvider:
    """Offline fault injection, not a real model or a performance benchmark."""

    def __init__(self, responses: list[str]):
        self._responses = iter(responses)
        self.calls: list[dict] = []

    def generate(self, messages: Messages, schema: dict, schema_name: str, timeout: float) -> str:
        self.calls.append({"messages": deepcopy(messages), "schema": schema, "phase": schema_name})
        try:
            return next(self._responses)
        except StopIteration:
            raise ProviderError("scripted_responses_exhausted") from None


def offline_scenarios() -> dict[str, tuple]:
    normal = scripted_steps()
    broken_function = dict(FUNCTIONS)
    broken_function["get_service_status"] = replace(
        FUNCTIONS["get_service_status"], function=lambda service: {"service": service}
    )
    return {
        "valid": (normal, FUNCTIONS, "succeeded", 4, 2, DEMO_MESSAGE),
        "parse_retry": (["{broken JSON", *normal], FUNCTIONS, "succeeded", 5, 2, DEMO_MESSAGE),
        "schema_retry": (
            [*normal[:-1], json.dumps(ticket_payload(priority="urgent")), normal[-1]],
            FUNCTIONS,
            "succeeded",
            5,
            2,
            DEMO_MESSAGE,
        ),
        "rule_retry": (
            [
                *normal[:-1],
                json.dumps(ticket_payload(confirmed_incident_id="INVENTED")),
                normal[-1],
            ],
            FUNCTIONS,
            "succeeded",
            5,
            2,
            DEMO_MESSAGE,
        ),
        "function_invalid": (normal, broken_function, "failed", 1, 1, DEMO_MESSAGE),
        "exhausted": (["{broken JSON"] * 3, FUNCTIONS, "needs_review", 3, 0, DEMO_MESSAGE),
        "clarification": (
            [
                action("get_routing_policy", category="billing"),
                FINISH,
                json.dumps(
                    ticket_payload(
                        summary="Customer asks about an unexpected charge.",
                        category="billing",
                        service=None,
                        queue="finance",
                        priority="normal",
                        affected_users=None,
                        confirmed_incident_id=None,
                        needs_clarification=True,
                        questions=["Which service is the charge for?"],
                        evidence=[
                            {"source": "user_message", "reference": "user:1"},
                            {"source": "function_result", "reference": "fn:1"},
                        ],
                    )
                ),
            ],
            FUNCTIONS,
            "succeeded",
            3,
            1,
            "I have an unexpected charge. Please help.",
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--live", action="store_true", help="Call your configured Foundry deployment"
    )
    modes.add_argument("--schema", choices=["action", "ticket"], help="Print generated JSON Schema")
    modes.add_argument("--case", choices=[*offline_scenarios(), "all"], default="all")
    parser.add_argument("--message", default=DEMO_MESSAGE, help="Message used by live mode")
    parser.add_argument(
        "--verbose", action="store_true", help="Show manual function execution logs"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    if args.schema:
        model = ActionDecision if args.schema == "action" else Ticket
        print(json.dumps(model.model_json_schema(), indent=2))
        return 0
    if args.live:
        try:
            settings = FoundrySettings.from_env()
            limits = AgentLimits.from_env()
            with FoundryProvider(settings) as provider:
                result = run_agent(args.message, provider, limits=limits)
        except ConfigurationError as exc:
            print(json.dumps({"status": "configuration_error", "error": str(exc)}))
            return 2
        print(result.model_dump_json(indent=2))
        return 0 if result.status == "succeeded" else 1

    print("OFFLINE DEMO: model responses are scripted; Python functions really execute locally.")
    print("Both local functions use fictional fixture data, including in live mode.")
    scenarios = offline_scenarios()
    selected = scenarios if args.case == "all" else {args.case: scenarios[args.case]}
    passed = True
    for name, (
        responses,
        functions,
        status,
        model_calls,
        function_calls,
        message,
    ) in selected.items():
        print(f"\n--- {name} ---")
        result = run_agent(message, ScriptedProvider(responses), functions=functions)
        print(result.model_dump_json(indent=2))
        passed = passed and (result.status, result.model_calls, result.function_calls) == (
            status,
            model_calls,
            function_calls,
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

import json
import logging
import math
import os
import time
from collections.abc import Callable , Mapping
from dataclasses import dataclass, field
from typing import TypeVar


from pydantic import BaseModel , ValidationError

from structured_output_agent.provider import (
   ConfigurationError,
   JSONProvider,
   ProviderError,
   ProviderRefusal,

)


from structured_output_agent.schemas import (
    ActionDecision,
    AgentResult,
    Category,
    FunctionObservation,
    RoutingPolicyArguments,
    RoutingPolicyResult,
    Service,
    ServiceStatusArguments,
    ServiceStatusResult,
    Ticket,
    TriageRequest,
    ValidationIssue,
)


logger = logging.getLogger(__name__)

T = TypeVar("T" , bound=BaseModel)

def get_service_status(service : Service) -> dict :

   if service == "payment_api":
      return {"service": service, "status": "outage", "incident_id": "INC-DEMO-001"}
   return {"service": service, "status": "operational", "incident_id": None}



def get_routing_policy(category: Category) -> dict:
    """Second ordinary Python function. Replace fixtures with a real source later."""
    queues = {
        "technical": "engineering",
        "billing": "finance",
        "access": "identity",
        "other": "helpdesk",
    }
    return {"category": category, "queue": queues[category], "policy_id": f"POLICY-{category}-v1"}




"""
Because `BaseModel` and `type[BaseModel]` mean two different things:

* `BaseModel` means "an **instance**, an object already created from a Pydantic model."
* `type[BaseModel]` means "a **class** that is a subclass of `BaseModel`, not yet turned into an object."

"""
@dataclass(frozen=True)
class FunctionSpec:
    function: Callable [... , dict]
    arguments_model: type[BaseModel]
    result_model: type[BaseModel]   




FUNCTIONS = {
    "get_service_status": FunctionSpec(
        get_service_status, ServiceStatusArguments, ServiceStatusResult
    ),
    "get_routing_policy": FunctionSpec(
        get_routing_policy, RoutingPolicyArguments, RoutingPolicyResult
    ),
}


class RuleError(Exception):
    """Static rule descriptions are safe to log and send as repair feedback."""


class ReviewRequired(Exception):
    """Budget exhaustion or unresolved contract/rule failures."""


class FunctionBoundaryError(Exception):
    """Invalid function data is never inserted into model context."""



@dataclass(frozen=True)
class AgentLimits:
    max_model_calls: int = 8
    max_function_calls: int = 3
    validation_attempts: int = 3
    run_timeout: float = 90

    def __post__init(self) -> None:
        for value in (self.max_model_calls , self.max_function_calls , self.validation_attempts):
            if type(value) is not int or value < 1:
                raise ConfigurationError("Agent call/attempt limits must be positive integers")

        if not math.isfinite(self.run_timeout) or self.run_timeout <= 0:
            raise ConfigurationError("Run timeout must be positive and finite")

    @classmethod
    def from_env(cls) -> "AgentLimits":
        try:
            return cls(
                max_model_calls=int(os.getenv("AGENT_MAX_MODEL_CALLS", "8")),
                max_function_calls=int(os.getenv("AGENT_MAX_FUNCTION_CALLS", "3")),
                validation_attempts=int(os.getenv("AGENT_MAX_VALIDATION_ATTEMPTS", "3")),
                run_timeout=float(os.getenv("AGENT_RUN_TIMEOUT_SECONDS", "90")),
            )
        except ValueError as exc:
            if isinstance(exc, ConfigurationError):
                raise
            raise ConfigurationError("Invalid numeric agent setting") from None


@dataclass
class RunState:
    run_id: str
    deadline: float
    model_calls: int = 0
    function_calls: int = 0
    validation_failures: int = 0
    observations: list[FunctionObservation] = field(default_factory=list) # kinda important with memory references
    cache: dict[str, FunctionObservation] = field(default_factory=dict)



def validation_details(exc: ValidationError) -> list[ValidationIssue]:
    return [
        ValidationIssue(field=".".join(map(str, error["loc"])) or "$", code=error["type"])
        for error in exc.errors(include_input=False, include_context=False, include_url=False)
    ]


def dispatch_function(decision: ActionDecision, registry: Mapping[str, FunctionSpec]) -> BaseModel:
    """Your own dispatcher: no SDK tools, reflection, eval, or model-supplied URLs."""
    name = decision.function_name
    if name is None or name not in registry or decision.arguments is None:
        raise FunctionBoundaryError("function_not_allowed")
    spec = registry[name]
    try:
        arguments = spec.arguments_model.model_validate(
            decision.arguments.model_dump(exclude_none=True)
        )
    except ValidationError:
        raise FunctionBoundaryError("function_arguments_invalid") from None
    try:
        raw_result = spec.function(**arguments.model_dump())
    except Exception:
        # Function implementations are an external boundary; never log raw errors.
        raise FunctionBoundaryError("function_execution_failed") from None
    try:
        result = spec.result_model.model_validate(raw_result)
    except ValidationError:
        raise FunctionBoundaryError("function_result_invalid") from None
    if isinstance(result, ServiceStatusResult) and result.service != arguments.service:
        raise FunctionBoundaryError("function_service_mismatch")
    if isinstance(result, RoutingPolicyResult) and result.category != arguments.category:
        raise FunctionBoundaryError("function_category_mismatch")
    return result





def check_ticket(ticket: Ticket, observations: list[FunctionObservation]) -> None:
    known = {observation.reference: observation for observation in observations}
    cited = {(item.source, item.reference) for item in ticket.evidence}
    if ("user_message", "user:1") not in cited:
        raise RuleError("Ticket must cite user:1")
    for source, reference in cited:
        if source == "user_message" and reference != "user:1":
            raise RuleError("Unknown user-message evidence reference")
        if source == "function_result" and reference not in known:
            raise RuleError("Unknown function-result evidence reference")
    policies = [
        item
        for item in observations
        if isinstance(item.result, RoutingPolicyResult) and item.result.category == ticket.category
    ]
    if not policies:
        raise RuleError("Call get_routing_policy for the ticket category before finishing")
    policy = policies[-1]
    if ticket.queue != policy.result.queue or ("function_result", policy.reference) not in cited:
        raise RuleError("Queue must match and cite the validated routing policy")
    if ticket.service is None:
        if ticket.confirmed_incident_id is not None or not ticket.needs_clarification:
            raise RuleError("Unknown service requires clarification and no confirmed incident")
        if ticket.priority == "high":
            raise RuleError("High priority requires a confirmed service outage")
        return
    statuses = [
        item
        for item in observations
        if isinstance(item.result, ServiceStatusResult) and item.result.service == ticket.service
    ]
    if not statuses:
        raise RuleError("Known service requires a validated get_service_status result")
    status = statuses[-1]
    if ("function_result", status.reference) not in cited:
        raise RuleError("Ticket must cite its validated service status")
    if ticket.confirmed_incident_id != status.result.incident_id:
        raise RuleError("Incident ID must match the validated service-status result")
    if status.result.status == "outage" and ticket.priority != "high":
        raise RuleError("Confirmed outage requires high priority under the demo policy")
    if status.result.status == "operational" and ticket.priority == "high":
        raise RuleError("High priority requires a confirmed outage under the demo policy")



    



    









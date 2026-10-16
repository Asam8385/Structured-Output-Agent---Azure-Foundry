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


def dispatch_function(decision: ActionDecision , registry: Mapping[str , FunctionSpec]) -> BaseModel:

    name = decision.function_name

    if name is None or name not in registry or decision.arguments is None:
        raise FunctionBoundaryError("function_not_allowed")

    spec = registry[name]

    try:
        arguments = spec.arguments_model.model_validate(
            decision.arguments.model_dump(exclude_none=True)
        )






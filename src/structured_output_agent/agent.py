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



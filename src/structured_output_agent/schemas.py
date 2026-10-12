from typing import Literal , Self

from pydantic import BaseModel , ConfigDict , field_validator , model_validator

Service = Literal["payment_api", "login_service"]
Category = Literal["technical", "billing", "access", "other"]
Queue = Literal["engineering", "finance", "identity", "helpdesk"]
FunctionName = Literal["get_service_status", "get_routing_policy"]

class StrictModel(BaseModel): 
    model_config = ConfigDict(strict=True , extra="forbid")


class triageRequest(StrictModel):
    message : str 

    @field_validator("message")
    @classmethod
    def valid_message(cls, value : str ) -> str:
        if not value.strip() or len(value) > 4_000 :
            raise ValueError("Message must contain 1 to 4000 characters")

        return value


class FunctionArguments(StrictModel):

    services : Service | None
    category : Category | None



class ActionDecision(StrictModel):
    action: Literal["call_function", "finish"]
    function_name: FunctionName | None
    arguments: FunctionArguments | None


    @model_validator(mode="after")
    def valid_action(self) -> Self:
        if self.action == "finish":
            if self.function_name is not None or self.arguments is not None:
                raise ValueError("Clarification require noempty questions")
            return self
        if self.function_name is None or self.arguments is None:
            raise ValueError("call_function requires a function name and arguments")
        if self.function_name == "get_service_status":
            if self.arguments.service is None or self.arguments.category is not None:
                raise ValueError("get_service_status requires service and null category")
        elif self.arguments.category is None or self.arguments.service is not None:
            raise ValueError("get_routing_policy requires category and null service")
        return self



class ServiceStatusArguments(StrictModel):
    service: Service


class RoutingPolicyArguments(StrictModel):
    category: Category
        

class ServiceStatusResult(StrictModel):
    service: Service
    status: Literal["Operational"  , "outage"]
    incident_id : str | None

    @model_validator(mode="after")
    def valid_incident(self) -> Self:
        if self.status == "outage" and (not self.incident_id or not self.incident_id.strip()):
            raise ValueError("An outage requires a nonempty incident ID")
        if self.status == "operational" and self.incident_id is not None:
            raise ValueError("Operational service requires null incident ID")
        return self


class RoutingPolicyResult(StrictModel):
    category: Category
    queue: Queue
    policy_id: str

    @field_validator("policy_id")
    @classmethod
    def valid_policy_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Policy ID must contain text")
        return value


class Evidence(StrictModel):
    source: Literal["user_message", "function_result"]
    reference: str




class Ticket(StrictModel):
    summary: str
    category: Category
    service: Service | None
    queue: Queue
    priority: Literal["low", "normal", "high"]
    affected_users: int | None
    confirmed_incident_id: str | None
    evidence: list[Evidence]
    needs_clarification: bool
    questions: list[str]

    # These richer Python checks run locally after provider schema enforcement.
    @field_validator("summary")
    @classmethod
    def valid_summary(cls, value: str) -> str:
        if not value.strip() or len(value) > 500:
            raise ValueError("Summary must contain 1 to 500 characters")
        return value

    @field_validator("affected_users")
    @classmethod
    def valid_count(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("Affected users cannot be negative")
        return value

    @model_validator(mode="after")
    def valid_questions(self) -> Self:
        if self.needs_clarification:
            if not self.questions or any(not question.strip() for question in self.questions):
                raise ValueError("Clarification requires nonempty questions")
        elif self.questions:
            raise ValueError("Questions require needs_clarification=true")
        return self



class FunctionObservation(StrictModel):
    # Built by Python, never by the model.
    reference: str
    function_name: FunctionName
    result: ServiceStatusResult | RoutingPolicyResult


class ValidationIssue(StrictModel):
    field: str
    code: str
    rule: str | None = None


class AgentResult(StrictModel):
    run_id: str
    status: Literal["succeeded", "needs_review", "failed", "refused"]
    model_calls: int
    function_calls: int
    validation_failures: int
    function_results: list[FunctionObservation]
    result: Ticket | None
    error: str | None

    @model_validator(mode="after")
    def valid_outcome(self) -> Self:
        if min(self.model_calls, self.function_calls, self.validation_failures) < 0:
            raise ValueError("Counters cannot be negative")
        if self.status == "succeeded":
            if self.result is None or self.error is not None:
                raise ValueError("Success requires a result and no error")
        elif self.result is not None or not self.error:
            raise ValueError("Non-success requires an error and no result")
        return self





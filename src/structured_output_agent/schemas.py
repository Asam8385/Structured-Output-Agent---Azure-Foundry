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


class FunctionArgument(StrictModel):

    services : Service | None
    category : Category | None

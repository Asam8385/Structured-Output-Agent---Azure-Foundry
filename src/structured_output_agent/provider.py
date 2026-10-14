import math
import os
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit


from azure.core.exceptions import ClientAuthenticationError
from azure.identity import DefaultAzureCredential , AzureCliCredential , get_bearer_token_provider , ManagedIdentityCredential
from dotenv import load_dotenv
from openai import APIConnectionError , APIStatusError , APITimeoutError , OpenAI , OpenAIError


Messages = list[dict[str , str]]

class ConfigurationError(ValueError):
    """Invalid application settings; contains no secret values."""


class ProviderError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ProviderRefusal(Exception):
    """Provider refusal is a terminal outcome, not a JSON parse error."""


@dataclass(frozen=True)
class FoundarySettings:
    endpoint: str
    deployment: str
    auth: str = "api_key"
    api_key: str = field(default="", repr=False)
    token_scope: str = "https://ai.azure.com/.default"
    managed_identity_client_id: str | None = None
    request_timeout: float = 25
    max_completion_tokens: int = 1400


    def __post__init(self) -> None:

        parts = urlsplit(self.endpoint)

        if(
            parts.scheme != "https" 
            or not parts.netloc 
            or parts.username is not None 
            or parts.query
            or parts.fragment 
            or parts.path.rstrip("/") != "/openai/v1"

        ):
            raise ConfigurationError("Use an HTTPS model endpoint ending in /openai/v1/")

        if not self.deployment.strip() or self.deployment.startswith("YOUR-"):
            raise ConfigurationError("Set AZURE_FOUNDRY_DEPLOYMENT to your deployment name")
        if self.auth not in {"api_key", "azure_cli", "managed_identity"}:
            raise ConfigurationError(
                "Authentication must be api_key, azure_cli, or managed_identity"
            )
        if self.auth == "api_key" and not self.api_key.strip():
            raise ConfigurationError("Set AZURE_FOUNDRY_API_KEY for api_key authentication")
        if not math.isfinite(self.request_timeout) or self.request_timeout <= 0:
            raise ConfigurationError("Request timeout must be positive and finite")
        if type(self.max_completion_tokens) is not int or self.max_completion_tokens < 1:
            raise ConfigurationError("Completion token limit must be a positive integer")



        @classmethod
        def from_env(cls) -> "FoundarySettings":
            load_dotenv(".env" , override=False)


class FoundaryProvider:
    def __init__(self ,  settings: FoundarySettings , * , client: OpenAI |None = None):

        self.settings = settings
        self._credentials = None
        self.owns_client  = client is None

        if client is not None:
            self._client = client
            return
        if settings.auth == "api_key":
            key = settings.api_key
        else:
            if settings.auth == "azure_cli":
                self._credential = AzureCliCredential()
            else:
                self._credential = ManagedIdentityCredential(
                    client_id=settings.managed_identity_client_id
                )
            key = get_bearer_token_provider(self._credential, settings.token_scope)

        self._client = OpenAI(
             base_url= settings.endpoint
             api_key=key,
             timeout=settings.request_timeout
             max_retries=0 

             
         )

    def generate(self, message: Messages , schema: dict , shcema_name: str , timeout: float) -> str:

        if timeout <= 0:
            raise ProviderError("deadline_exceeded")

        try:
            completion = self._client.with_options(
                
            )


        
        





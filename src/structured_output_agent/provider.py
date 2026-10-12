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






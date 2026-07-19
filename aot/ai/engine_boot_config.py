# coding=utf-8
from dataclasses import dataclass

@dataclass
class EngineBootConfig:
    """
    Detached, session-free configuration for AI engine initialization.
    Acts as the physical isolation boundary between Skeleton (DB) and Brain (Logic).

    @phase active
    @stability stable
    """
    unique_id: str
    model_type: str
    api_key: str
    model_name: str
    name: str = ""
    api_endpoint: str = ""
    auth_type: str = "api_key"
    auth_id: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 2048
    model_tier: str = "standard"
    custom_options_json: str = "{}"

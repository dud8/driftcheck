"""Model selection.

The default path is a local OpenAI-compatible server (LM Studio), so DriftCheck runs with
no cloud credentials at all. ``DRIFTCHECK_PROVIDER=bedrock`` switches to Amazon Bedrock for
anyone who has credentials; nothing on the default path touches AWS.
"""

from __future__ import annotations

import os

from strands.models.model import Model

DEFAULT_LOCAL_MODEL = "qwen/qwen3.6-35b-a3b"
DEFAULT_BASE_URL = "http://localhost:1234/v1"


def build_model(temperature: float = 0.0, max_tokens: int = 4096) -> Model:
    """Return the configured model provider.

    Env:
        DRIFTCHECK_PROVIDER: 'lmstudio' (default) or 'bedrock'.
        DRIFTCHECK_MODEL_ID: model id for the chosen provider.
        DRIFTCHECK_BASE_URL: OpenAI-compatible endpoint, local provider only.
    """
    provider = os.environ.get("DRIFTCHECK_PROVIDER", "lmstudio").lower()
    params = {"temperature": temperature, "max_tokens": max_tokens}

    if provider == "bedrock":
        from strands.models import BedrockModel

        return BedrockModel(
            model_id=os.environ.get(
                "DRIFTCHECK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0"
            ),
            temperature=temperature,
            max_tokens=max_tokens,
        )

    if provider != "lmstudio":
        raise ValueError(f"Unknown DRIFTCHECK_PROVIDER {provider!r}: use 'lmstudio' or 'bedrock'")

    from strands.models.openai import OpenAIModel

    return OpenAIModel(
        client_args={
            "base_url": os.environ.get("DRIFTCHECK_BASE_URL", DEFAULT_BASE_URL),
            "api_key": os.environ.get("DRIFTCHECK_API_KEY", "lm-studio"),
        },
        model_id=os.environ.get("DRIFTCHECK_MODEL_ID", DEFAULT_LOCAL_MODEL),
        params=params,
    )

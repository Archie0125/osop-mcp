"""LLM client abstraction for OSOP agent node execution.

Supports Anthropic and OpenAI providers. Reads API keys from
environment variables or .env files.
"""

from __future__ import annotations

import os
from typing import Any


def _load_dotenv() -> None:
    """Load .env file if present (best-effort, no dependency)."""
    for path in [".env", os.path.expanduser("~/.osop/.env")]:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def resolve_secret(name: str) -> str | None:
    """Resolve a secret by name from environment variables."""
    _load_dotenv()
    # Try exact name, then common prefixes
    for candidate in [name, name.upper(), name.upper().replace("-", "_")]:
        val = os.environ.get(candidate)
        if val:
            return val
    return None


def call_llm(
    provider: str,
    model: str,
    system_prompt: str = "",
    user_message: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Call an LLM provider and return the response.

    Returns:
        {
            "content": str,
            "model": str,
            "provider": str,
            "usage": {"input_tokens": int, "output_tokens": int},
            "cost_usd": float,  # estimated
        }
    """
    provider = provider.lower().strip()

    if provider in ("anthropic", "claude"):
        return _call_anthropic(model, system_prompt, user_message, temperature, max_tokens)
    elif provider in ("openai", "gpt", "chatgpt"):
        return _call_openai(model, system_prompt, user_message, temperature, max_tokens)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}. Use 'anthropic' or 'openai'.")


def _call_anthropic(
    model: str, system_prompt: str, user_message: str,
    temperature: float, max_tokens: int,
) -> dict[str, Any]:
    """Call Anthropic Messages API."""
    api_key = resolve_secret("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not found in environment. Set it or add to .env file.")

    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model or "claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system_prompt or "You are a helpful assistant.",
        messages=[{"role": "user", "content": user_message or "Hello"}],
        temperature=temperature,
    )

    input_tokens = msg.usage.input_tokens
    output_tokens = msg.usage.output_tokens
    # Rough cost estimate (Claude Sonnet pricing as default)
    cost = (input_tokens * 0.003 + output_tokens * 0.015) / 1000

    return {
        "content": msg.content[0].text if msg.content else "",
        "model": msg.model,
        "provider": "anthropic",
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "cost_usd": round(cost, 6),
    }


def _call_openai(
    model: str, system_prompt: str, user_message: str,
    temperature: float, max_tokens: int,
) -> dict[str, Any]:
    """Call OpenAI Chat Completions API."""
    api_key = resolve_secret("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not found in environment. Set it or add to .env file.")

    try:
        import openai
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    client = openai.OpenAI(api_key=api_key)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_message or "Hello"})

    resp = client.chat.completions.create(
        model=model or "gpt-4o",
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    choice = resp.choices[0] if resp.choices else None
    content = choice.message.content if choice else ""
    usage = resp.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0
    # Rough cost estimate (GPT-4o pricing as default)
    cost = (input_tokens * 0.0025 + output_tokens * 0.01) / 1000

    return {
        "content": content or "",
        "model": resp.model or model,
        "provider": "openai",
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "cost_usd": round(cost, 6),
    }

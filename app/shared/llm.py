"""
Optional LLM clients (the "G" in RAG). All are free paths:

    none    - no LLM; the assistant answers with clear templates (default)
    gemini  - Google Gemini free tier (set GEMINI_API_KEY)
    ollama  - a local model through Ollama (no key, runs offline)

Every client returns None on any failure, so the caller always falls back
to the template answer. The core verification never depends on an LLM.
"""

from __future__ import annotations

import logging
from typing import Optional, Protocol

import requests

from app.config import Settings

log = logging.getLogger(__name__)
TIMEOUT_SECONDS = 30


class LLMClient(Protocol):
    name: str

    def generate(self, prompt: str) -> Optional[str]: ...


class NoLLM:
    name = "none"

    def generate(self, prompt: str) -> Optional[str]:
        return None


class GeminiClient:
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        self.api_key, self.model = api_key, model

    def generate(self, prompt: str) -> Optional[str]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        try:
            response = requests.post(
                url,
                params={"key": self.api_key},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": 0.1, "maxOutputTokens": 600}},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as exc:  # network, quota, unexpected payload
            log.warning("Gemini call failed: %s", exc)
            return None


class OllamaClient:
    name = "ollama"

    def __init__(self, base_url: str, model: str):
        self.base_url, self.model = base_url.rstrip("/"), model

    def generate(self, prompt: str) -> Optional[str]:
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False, "options": {"temperature": 0.1}},
                timeout=TIMEOUT_SECONDS * 4,
            )
            response.raise_for_status()
            return response.json().get("response", "").strip() or None
        except Exception as exc:
            log.warning("Ollama call failed: %s", exc)
            return None


def create_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "gemini" and settings.gemini_api_key:
        return GeminiClient(settings.gemini_api_key, settings.gemini_model)
    if settings.llm_provider == "ollama":
        return OllamaClient(settings.ollama_url, settings.ollama_model)
    return NoLLM()

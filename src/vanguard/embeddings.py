"""Embedding helpers backed by Gemini text-embedding-004."""

from __future__ import annotations

from typing import Protocol

import google.generativeai as genai


class Embedder(Protocol):
    """Embedder protocol for dependency injection."""

    def embed_text(self, text: str) -> list[float] | None:
        """Return vector embedding for input text."""


class GeminiEmbedder:
    """Gemini embedding client for semantic event memory."""

    def __init__(self, api_key: str, model: str = "models/text-embedding-004"):
        if not api_key:
            raise ValueError("Missing Gemini API key for embeddings.")
        genai.configure(api_key=api_key)
        self.model = model

    def embed_text(self, text: str) -> list[float] | None:
        content = text.strip()
        if not content:
            return None

        response = genai.embed_content(model=self.model, content=content)
        embedding = response.get("embedding")
        if not embedding:
            return None
        return [float(value) for value in embedding]

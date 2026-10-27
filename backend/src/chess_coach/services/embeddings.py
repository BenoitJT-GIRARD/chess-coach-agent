"""Sentence embedding service.

Wraps a sentence-transformers model so the rest of the code depends on a small,
stable interface (``embed`` / ``embed_one``) rather than on the library. The
model is loaded lazily, once per process and model name, because loading it is
the expensive part: every instance of the service shares the copy the first one
loaded, so the start-up warm-up serves the agent and the search route alike.
Embeddings are L2-normalised so that an inner-product search in Milvus is
equivalent to cosine similarity.
"""

from __future__ import annotations

import threading
from typing import Any

from chess_coach.config import Settings, get_settings


class EmbeddingServiceError(RuntimeError):
    """Raised when the embedding model cannot be loaded."""


#: The loaded models, by name. The lock makes a second caller wait for a load in progress
#: rather than start another one: the warm-up thread and the first request often overlap.
_MODELS: dict[str, Any] = {}
_LOCK = threading.Lock()


def load_model(name: str) -> Any:
    """Return the model called ``name``, loading it on the first call of the process."""

    with _LOCK:
        if name not in _MODELS:
            from sentence_transformers import SentenceTransformer

            try:
                _MODELS[name] = SentenceTransformer(name)
            # Whatever stops the load (no network and no cache, a bad name, a broken
            # download), the callers need one exception to turn into "no passages".
            except Exception as exc:
                raise EmbeddingServiceError(
                    f"Could not load the embedding model {name}: {exc}"
                ) from exc
        return _MODELS[name]


class EmbeddingService:
    """Encode text into dense vectors with a sentence-transformers model."""

    def __init__(self, settings: Settings | None = None, model: Any | None = None) -> None:
        self._settings = settings or get_settings()
        self._model = model

    def _get_model(self) -> Any:
        """The model handed to this instance, or the one the process shares."""

        if self._model is None:
            self._model = load_model(self._settings.embedding_model)
        return self._model

    @property
    def dim(self) -> int:
        """Configured embedding dimension."""

        return self._settings.embedding_dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into normalised vectors."""

        model = self._get_model()
        vectors = model.encode(texts, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text into a normalised vector."""

        return self.embed([text])[0]

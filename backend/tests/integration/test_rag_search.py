"""Tests for the RAG search service (embedder and store faked)."""

from __future__ import annotations

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from chess_coach.api.dependencies import get_rag_service
from chess_coach.api.main import create_app
from chess_coach.config import Settings
from chess_coach.services import embeddings
from chess_coach.services.embeddings import EmbeddingService, EmbeddingServiceError
from chess_coach.services.milvus_store import SearchHit
from chess_coach.services.rag_search import RagService

pytestmark = pytest.mark.integration


class FakeEmbedder:
    def embed_one(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeStore:
    def __init__(self) -> None:
        self.last_top_k: int | None = None

    def search(self, query_embedding: list[float], *, top_k: int = 3) -> list[SearchHit]:
        self.last_top_k = top_k
        return [
            SearchHit(
                text="La defense sicilienne est tranchante.",
                opening="Defense sicilienne",
                source="defense-sicilienne.md",
                score=0.87,
            )
        ]


def test_rag_service_embeds_then_searches() -> None:
    store = FakeStore()
    service = RagService(embedder=FakeEmbedder(), store=store)

    hits = service.search("ouverture tranchante pour les noirs", top_k=5)

    assert store.last_top_k == 5
    assert hits[0].opening == "Defense sicilienne"


def test_vector_search_route_returns_passages() -> None:
    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: RagService(
        embedder=FakeEmbedder(), store=FakeStore()
    )
    client = TestClient(app)

    response = client.get("/api/v1/vector-search", params={"q": quote("sicilienne"), "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["passages"][0]["source"] == "defense-sicilienne.md"


def test_vector_search_answers_503_when_the_embedding_model_cannot_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No network and no cache: a missing model is a missing dependency, not a crash."""

    def refuse(name: str) -> None:
        raise EmbeddingServiceError(f"Could not load the embedding model {name}")

    monkeypatch.setattr(embeddings, "load_model", refuse)
    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: RagService(
        embedder=EmbeddingService(Settings()), store=FakeStore()
    )
    client = TestClient(app)

    response = client.get("/api/v1/vector-search", params={"q": "sicilienne", "top_k": 3})

    assert response.status_code == 503
    assert "embedding model" in response.json()["detail"]

"""Shared fixtures for backend tests.

These tests exercise the RAG pipeline's tool-calling logic without hitting
the real Anthropic API or a real ChromaDB instance, so they run fast and
deterministically and don't cost API credits.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

# Allow "import search_tools", "import ai_generator", etc. (backend has no package layout)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vector_store import SearchResults  # noqa: E402


def make_search_results(documents, metadata, distances=None, error=None):
    """Build a SearchResults instance the way VectorStore.search would return it."""
    if distances is None:
        distances = [0.1] * len(documents)
    return SearchResults(documents=documents, metadata=metadata, distances=distances, error=error)


@pytest.fixture
def sample_search_results():
    """A typical non-empty result set spanning two lessons of one course."""
    return make_search_results(
        documents=[
            "MCP stands for Model Context Protocol. It lets models access external context.",
            "Lesson 2 covers building an MCP client from scratch.",
        ],
        metadata=[
            {"course_title": "MCP: Build Rich-Context AI Apps with Anthropic", "lesson_number": 1, "chunk_index": 0},
            {"course_title": "MCP: Build Rich-Context AI Apps with Anthropic", "lesson_number": 2, "chunk_index": 3},
        ],
    )


@pytest.fixture
def empty_search_results():
    return make_search_results(documents=[], metadata=[])


@pytest.fixture
def error_search_results():
    return SearchResults.empty("No course found matching 'Nonexistent Course'")


@pytest.fixture
def mock_vector_store():
    """A MagicMock standing in for VectorStore, with link-lookup helpers wired up."""
    store = MagicMock()
    store.get_lesson_link.return_value = "https://example.com/lesson"
    store.get_course_link.return_value = "https://example.com/course"
    return store


def make_text_response(text, stop_reason="end_turn"):
    """Build a fake Anthropic Message with a single text block."""
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block], stop_reason=stop_reason)


def make_tool_use_response(tool_name, tool_input, tool_id="tool_1", stop_reason="tool_use"):
    """Build a fake Anthropic Message requesting a single tool call."""
    block = SimpleNamespace(type="tool_use", name=tool_name, input=tool_input, id=tool_id)
    return SimpleNamespace(content=[block], stop_reason=stop_reason)


def make_multi_tool_use_response(calls, stop_reason="tool_use"):
    """Build a fake Anthropic Message requesting several parallel tool calls.

    calls: list of (tool_name, tool_input, tool_id) tuples.
    """
    blocks = [
        SimpleNamespace(type="tool_use", name=name, input=tool_input, id=tool_id)
        for name, tool_input, tool_id in calls
    ]
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


@pytest.fixture
def mock_anthropic_client():
    """A MagicMock standing in for anthropic.Anthropic() with .messages.create()."""
    client = MagicMock()
    return client


# --- API endpoint testing infrastructure ---------------------------------
#
# backend/app.py instantiates a real RAGSystem (loading the embedding model
# and ChromaDB) and mounts StaticFiles(directory="../frontend") at import
# time, neither of which is available/desirable in the test environment.
# To test the API surface without triggering that, we rebuild the same
# routes here against an injected (mocked) RAGSystem instead of importing
# app.py directly.

class QueryRequest(BaseModel):
    """Request model for course queries (mirrors app.py's QueryRequest)."""
    query: str
    session_id: Optional[str] = None


class QueryResponse(BaseModel):
    """Response model for course queries (mirrors app.py's QueryResponse)."""
    answer: str
    sources: List[Dict[str, Optional[str]]]
    session_id: str


class CourseStats(BaseModel):
    """Response model for course statistics (mirrors app.py's CourseStats)."""
    total_courses: int
    course_titles: List[str]


def create_test_app(rag_system):
    """Build a FastAPI app exposing the same routes as backend/app.py, wired
    to the given rag_system. Omits app.py's static file mount and startup
    document-loading event, which don't apply in the test environment."""
    app = FastAPI(title="Course Materials RAG System (test)")

    @app.post("/api/query", response_model=QueryResponse)
    async def query_documents(request: QueryRequest):
        try:
            session_id = request.session_id
            if not session_id:
                session_id = rag_system.session_manager.create_session()
            answer, sources = rag_system.query(request.query, session_id)
            return QueryResponse(answer=answer, sources=sources, session_id=session_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete("/api/session/{session_id}")
    async def clear_session(session_id: str):
        try:
            rag_system.session_manager.clear_session(session_id)
            return {"success": True}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/courses", response_model=CourseStats)
    async def get_course_stats():
        try:
            analytics = rag_system.get_course_analytics()
            return CourseStats(
                total_courses=analytics["total_courses"],
                course_titles=analytics["course_titles"],
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/")
    async def root():
        # Stand-in for app.py's StaticFiles(directory="../frontend") mount,
        # which serves frontend/index.html at "/" and isn't available here.
        return {"message": "Course Materials RAG System API"}

    return app


@pytest.fixture
def mock_rag_system():
    """A MagicMock standing in for RAGSystem, wired with reasonable defaults
    for the API endpoint tests."""
    rag = MagicMock()
    rag.session_manager.create_session.return_value = "test-session-1"
    rag.query.return_value = (
        "MCP is the Model Context Protocol.",
        [{"text": "MCP: Build Rich-Context AI Apps with Anthropic - Lesson 1", "link": "https://example.com/l1"}],
    )
    rag.get_course_analytics.return_value = {
        "total_courses": 2,
        "course_titles": [
            "MCP: Build Rich-Context AI Apps with Anthropic",
            "Prompt Engineering Basics",
        ],
    }
    return rag


@pytest.fixture
def test_app(mock_rag_system):
    """A FastAPI app built by create_test_app() around mock_rag_system."""
    return create_test_app(mock_rag_system)


@pytest.fixture
def client(test_app):
    """A TestClient for making requests against test_app."""
    return TestClient(test_app)

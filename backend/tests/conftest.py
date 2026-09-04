"""Shared fixtures for backend tests.

These tests exercise the RAG pipeline's tool-calling logic without hitting
the real Anthropic API or a real ChromaDB instance, so they run fast and
deterministically and don't cost API credits.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Allow "import search_tools", "import ai_generator", etc. (backend has no package layout)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vector_store import SearchResults  # noqa: E402


def make_search_results(documents, metadata, distances=None, error=None):
    """Build a SearchResults instance the way VectorStore.search would return it."""
    if distances is None:
        distances = [0.1] * len(documents)
    return SearchResults(
        documents=documents, metadata=metadata, distances=distances, error=error
    )


@pytest.fixture
def sample_search_results():
    """A typical non-empty result set spanning two lessons of one course."""
    return make_search_results(
        documents=[
            "MCP stands for Model Context Protocol. It lets models access external context.",
            "Lesson 2 covers building an MCP client from scratch.",
        ],
        metadata=[
            {
                "course_title": "MCP: Build Rich-Context AI Apps with Anthropic",
                "lesson_number": 1,
                "chunk_index": 0,
            },
            {
                "course_title": "MCP: Build Rich-Context AI Apps with Anthropic",
                "lesson_number": 2,
                "chunk_index": 3,
            },
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


def make_tool_use_response(
    tool_name, tool_input, tool_id="tool_1", stop_reason="tool_use"
):
    """Build a fake Anthropic Message requesting a single tool call."""
    block = SimpleNamespace(
        type="tool_use", name=tool_name, input=tool_input, id=tool_id
    )
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

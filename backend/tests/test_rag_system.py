"""Tests for how RAGSystem.query() handles content-related questions."""
import os
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv

from rag_system import RAGSystem
from session_manager import SessionManager

load_dotenv()  # so the live test below can see ANTHROPIC_API_KEY from .env at collection time


def make_rag_system_with_mocks():
    """Build a RAGSystem without running __init__ (skips loading the real
    embedding model / ChromaDB / Anthropic client), then wire in mocks for
    the collaborators query() actually touches."""
    rag = RAGSystem.__new__(RAGSystem)
    rag.ai_generator = MagicMock()
    rag.tool_manager = MagicMock()
    rag.session_manager = SessionManager(max_history=5)
    return rag


class TestRAGSystemQueryOrchestration:
    def test_content_query_returns_answer_and_sources(self):
        rag = make_rag_system_with_mocks()
        rag.ai_generator.generate_response.return_value = "MCP is the Model Context Protocol."
        rag.tool_manager.get_last_sources.return_value = [
            {"text": "MCP Course - Lesson 1", "link": "https://example.com/l1"}
        ]

        answer, sources = rag.query("What is MCP?")

        assert answer == "MCP is the Model Context Protocol."
        assert sources == [{"text": "MCP Course - Lesson 1", "link": "https://example.com/l1"}]

    def test_tool_definitions_and_tool_manager_are_passed_to_generator(self):
        rag = make_rag_system_with_mocks()
        rag.ai_generator.generate_response.return_value = "answer"
        rag.tool_manager.get_tool_definitions.return_value = [{"name": "search_course_content"}]
        rag.tool_manager.get_last_sources.return_value = []

        rag.query("What is covered in lesson 2?")

        call_kwargs = rag.ai_generator.generate_response.call_args.kwargs
        assert call_kwargs["tools"] == [{"name": "search_course_content"}]
        assert call_kwargs["tool_manager"] is rag.tool_manager
        assert "What is covered in lesson 2?" in call_kwargs["query"]

    def test_sources_are_reset_after_being_read(self):
        rag = make_rag_system_with_mocks()
        rag.ai_generator.generate_response.return_value = "answer"
        rag.tool_manager.get_last_sources.return_value = [{"text": "x", "link": None}]

        rag.query("content question")

        rag.tool_manager.reset_sources.assert_called_once()

    def test_session_history_used_and_updated(self):
        rag = make_rag_system_with_mocks()
        rag.ai_generator.generate_response.return_value = "second answer"
        rag.tool_manager.get_last_sources.return_value = []
        session_id = rag.session_manager.create_session()
        rag.session_manager.add_exchange(session_id, "first question", "first answer")

        rag.query("second question", session_id=session_id)

        call_kwargs = rag.ai_generator.generate_response.call_args.kwargs
        assert "first question" in call_kwargs["conversation_history"]
        assert "first answer" in call_kwargs["conversation_history"]

        history = rag.session_manager.get_conversation_history(session_id)
        assert "second question" in history
        assert "second answer" in history

    def test_no_session_id_skips_history(self):
        rag = make_rag_system_with_mocks()
        rag.ai_generator.generate_response.return_value = "answer"
        rag.tool_manager.get_last_sources.return_value = []

        rag.query("a question")

        call_kwargs = rag.ai_generator.generate_response.call_args.kwargs
        assert call_kwargs["conversation_history"] is None

    def test_generator_exception_propagates_as_the_500_the_frontend_reports(self):
        """This is the shape of failure that surfaces to users as 'Query failed':
        app.py's /api/query handler catches any exception from rag_system.query()
        and returns HTTP 500, which the frontend renders as 'Query failed'."""
        rag = make_rag_system_with_mocks()
        rag.ai_generator.generate_response.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError):
            rag.query("What is MCP?")


@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="requires a real ANTHROPIC_API_KEY")
class TestRAGSystemContentQueryLive:
    """End-to-end check against the real Anthropic API and the real, already-ingested
    ChromaDB store. Slower and costs API credits, so it's opt-in via the API key
    being present, and is what actually diagnoses the reported 'query failed' bug
    if it is caused by real model/API/data behavior rather than pure logic."""

    def test_content_question_against_real_course_data(self):
        from config import config

        rag = RAGSystem(config)
        answer, sources = rag.query("What is MCP and why is it useful?")

        assert isinstance(answer, str) and len(answer) > 0
        assert "error" not in answer.lower()[:20]

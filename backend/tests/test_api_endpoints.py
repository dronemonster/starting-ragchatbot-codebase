"""Tests for the FastAPI endpoints defined in backend/app.py.

These run against the test app built by conftest.create_test_app(), which
reproduces app.py's routes against an injected mock RAGSystem rather than
importing app.py directly (app.py mounts frontend static files and builds a
real RAGSystem at import time, neither of which exists/is wanted in tests).
"""


class TestQueryEndpoint:
    def test_query_with_session_id_returns_answer_and_sources(self, client, mock_rag_system):
        response = client.post(
            "/api/query",
            json={"query": "What is MCP?", "session_id": "existing-session"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["answer"] == "MCP is the Model Context Protocol."
        assert body["session_id"] == "existing-session"
        assert body["sources"] == [
            {"text": "MCP: Build Rich-Context AI Apps with Anthropic - Lesson 1", "link": "https://example.com/l1"}
        ]
        mock_rag_system.query.assert_called_once_with("What is MCP?", "existing-session")

    def test_query_without_session_id_creates_session(self, client, mock_rag_system):
        response = client.post("/api/query", json={"query": "What is MCP?"})

        assert response.status_code == 200
        assert response.json()["session_id"] == "test-session-1"
        mock_rag_system.session_manager.create_session.assert_called_once()
        mock_rag_system.query.assert_called_once_with("What is MCP?", "test-session-1")

    def test_query_missing_query_field_returns_422(self, client):
        response = client.post("/api/query", json={"session_id": "s1"})

        assert response.status_code == 422

    def test_query_empty_body_returns_422(self, client):
        response = client.post("/api/query", json={})

        assert response.status_code == 422

    def test_query_rag_system_exception_returns_500(self, client, mock_rag_system):
        mock_rag_system.query.side_effect = RuntimeError("boom")

        response = client.post("/api/query", json={"query": "What is MCP?"})

        assert response.status_code == 500
        assert "boom" in response.json()["detail"]

    def test_query_response_matches_schema_with_no_sources(self, client, mock_rag_system):
        mock_rag_system.query.return_value = ("just an answer, no tool call needed", [])

        response = client.post("/api/query", json={"query": "What is 2+2?"})

        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"answer", "sources", "session_id"}
        assert body["sources"] == []


class TestCoursesEndpoint:
    def test_get_course_stats_returns_analytics(self, client, mock_rag_system):
        response = client.get("/api/courses")

        assert response.status_code == 200
        body = response.json()
        assert body["total_courses"] == 2
        assert body["course_titles"] == [
            "MCP: Build Rich-Context AI Apps with Anthropic",
            "Prompt Engineering Basics",
        ]

    def test_get_course_stats_exception_returns_500(self, client, mock_rag_system):
        mock_rag_system.get_course_analytics.side_effect = RuntimeError("chroma unavailable")

        response = client.get("/api/courses")

        assert response.status_code == 500
        assert "chroma unavailable" in response.json()["detail"]

    def test_get_course_stats_zero_courses(self, client, mock_rag_system):
        mock_rag_system.get_course_analytics.return_value = {"total_courses": 0, "course_titles": []}

        response = client.get("/api/courses")

        assert response.status_code == 200
        assert response.json() == {"total_courses": 0, "course_titles": []}


class TestSessionEndpoint:
    def test_clear_session_returns_success(self, client, mock_rag_system):
        response = client.delete("/api/session/some-session-id")

        assert response.status_code == 200
        assert response.json() == {"success": True}
        mock_rag_system.session_manager.clear_session.assert_called_once_with("some-session-id")

    def test_clear_session_exception_returns_500(self, client, mock_rag_system):
        mock_rag_system.session_manager.clear_session.side_effect = RuntimeError("no such session")

        response = client.delete("/api/session/missing-id")

        assert response.status_code == 500
        assert "no such session" in response.json()["detail"]


class TestRootEndpoint:
    def test_root_returns_200(self, client):
        response = client.get("/")

        assert response.status_code == 200

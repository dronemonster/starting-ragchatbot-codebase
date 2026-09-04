"""Tests for CourseSearchTool.execute() in search_tools.py."""

from search_tools import CourseSearchTool

from .conftest import make_search_results


class TestCourseSearchToolExecute:
    def test_returns_formatted_results_with_headers(
        self, mock_vector_store, sample_search_results
    ):
        mock_vector_store.search.return_value = sample_search_results
        tool = CourseSearchTool(mock_vector_store)

        result = tool.execute(query="What is MCP?")

        assert "[MCP: Build Rich-Context AI Apps with Anthropic - Lesson 1]" in result
        assert "Model Context Protocol" in result
        assert "[MCP: Build Rich-Context AI Apps with Anthropic - Lesson 2]" in result

    def test_passes_query_and_filters_to_vector_store(
        self, mock_vector_store, sample_search_results
    ):
        mock_vector_store.search.return_value = sample_search_results
        tool = CourseSearchTool(mock_vector_store)

        tool.execute(query="clients", course_name="MCP", lesson_number=2)

        mock_vector_store.search.assert_called_once_with(
            query="clients", course_name="MCP", lesson_number=2
        )

    def test_empty_results_returns_no_content_message(
        self, mock_vector_store, empty_search_results
    ):
        mock_vector_store.search.return_value = empty_search_results
        tool = CourseSearchTool(mock_vector_store)

        result = tool.execute(query="something obscure")

        assert result == "No relevant content found."

    def test_empty_results_includes_course_and_lesson_filter_info(
        self, mock_vector_store, empty_search_results
    ):
        mock_vector_store.search.return_value = empty_search_results
        tool = CourseSearchTool(mock_vector_store)

        result = tool.execute(query="q", course_name="MCP", lesson_number=3)

        assert "in course 'MCP'" in result
        assert "in lesson 3" in result

    def test_store_error_is_returned_verbatim_not_raised(
        self, mock_vector_store, error_search_results
    ):
        mock_vector_store.search.return_value = error_search_results
        tool = CourseSearchTool(mock_vector_store)

        result = tool.execute(query="q", course_name="Nonexistent Course")

        assert result == "No course found matching 'Nonexistent Course'"

    def test_sources_are_tracked_with_lesson_links(
        self, mock_vector_store, sample_search_results
    ):
        mock_vector_store.search.return_value = sample_search_results
        mock_vector_store.get_lesson_link.return_value = "https://example.com/lesson/1"
        tool = CourseSearchTool(mock_vector_store)

        tool.execute(query="What is MCP?")

        assert tool.last_sources == [
            {
                "text": "MCP: Build Rich-Context AI Apps with Anthropic - Lesson 1",
                "link": "https://example.com/lesson/1",
            },
            {
                "text": "MCP: Build Rich-Context AI Apps with Anthropic - Lesson 2",
                "link": "https://example.com/lesson/1",
            },
        ]
        mock_vector_store.get_lesson_link.assert_any_call(
            "MCP: Build Rich-Context AI Apps with Anthropic", 1
        )

    def test_source_link_falls_back_to_course_link_when_no_lesson_link(
        self, mock_vector_store
    ):
        results = make_search_results(
            documents=["General course blurb."],
            metadata=[{"course_title": "Some Course", "lesson_number": 1}],
        )
        mock_vector_store.search.return_value = results
        mock_vector_store.get_lesson_link.return_value = None
        mock_vector_store.get_course_link.return_value = "https://example.com/course"
        tool = CourseSearchTool(mock_vector_store)

        tool.execute(query="q")

        assert tool.last_sources[0]["link"] == "https://example.com/course"

    def test_source_has_no_lesson_suffix_when_lesson_number_missing(
        self, mock_vector_store
    ):
        results = make_search_results(
            documents=["Course-level content with no specific lesson."],
            metadata=[{"course_title": "Some Course"}],
        )
        mock_vector_store.search.return_value = results
        tool = CourseSearchTool(mock_vector_store)

        result = tool.execute(query="q")

        assert "[Some Course]" in result
        assert tool.last_sources[0]["text"] == "Some Course"

    def test_last_sources_reset_between_calls(
        self, mock_vector_store, sample_search_results, empty_search_results
    ):
        tool = CourseSearchTool(mock_vector_store)

        mock_vector_store.search.return_value = sample_search_results
        tool.execute(query="q1")
        assert len(tool.last_sources) == 2

        mock_vector_store.search.return_value = empty_search_results
        tool.execute(query="q2")
        assert tool.last_sources == []

    def test_get_tool_definition_has_required_query_field(self, mock_vector_store):
        tool = CourseSearchTool(mock_vector_store)
        definition = tool.get_tool_definition()

        assert definition["name"] == "search_course_content"
        assert definition["input_schema"]["required"] == ["query"]
        assert set(definition["input_schema"]["properties"]) == {
            "query",
            "course_name",
            "lesson_number",
        }

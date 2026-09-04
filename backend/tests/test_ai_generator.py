"""Tests that AIGenerator correctly drives sequential tool-calling rounds."""
from unittest.mock import MagicMock, patch

from ai_generator import AIGenerator

from .conftest import make_multi_tool_use_response, make_text_response, make_tool_use_response


def make_generator():
    with patch("ai_generator.anthropic.Anthropic") as mock_anthropic_cls:
        client = MagicMock()
        mock_anthropic_cls.return_value = client
        generator = AIGenerator(api_key="test-key", model="claude-sonnet-5")
        return generator, client


class TestDirectResponseNoTools:
    def test_answers_directly_when_no_tool_use(self):
        generator, client = make_generator()
        client.messages.create.return_value = make_text_response("Paris is the capital of France.")

        result = generator.generate_response("What is the capital of France?")

        assert result == "Paris is the capital of France."
        client.messages.create.assert_called_once()

    def test_tools_and_tool_choice_are_attached_when_tools_provided(self):
        generator, client = make_generator()
        client.messages.create.return_value = make_text_response("An answer.")
        tools = [{"name": "search_course_content", "input_schema": {}}]

        generator.generate_response("some query", tools=tools, tool_manager=MagicMock())

        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["tools"] == tools
        assert call_kwargs["tool_choice"] == {"type": "auto"}


class TestSingleRoundToolExecution:
    def test_search_tool_is_invoked_with_claudes_arguments(self):
        generator, client = make_generator()
        tool_manager = MagicMock()
        tool_manager.execute_tool.return_value = "[Course - Lesson 1]\nSome content."

        client.messages.create.side_effect = [
            make_tool_use_response(
                "search_course_content",
                {"query": "What is MCP?", "course_name": "MCP"},
            ),
            make_text_response("MCP stands for Model Context Protocol."),
        ]

        result = generator.generate_response(
            "What is MCP?",
            tools=[{"name": "search_course_content"}],
            tool_manager=tool_manager,
        )

        tool_manager.execute_tool.assert_called_once_with(
            "search_course_content", query="What is MCP?", course_name="MCP"
        )
        assert result == "MCP stands for Model Context Protocol."
        assert client.messages.create.call_count == 2

    def test_second_call_still_carries_tools_but_final_call_after_answer_would_not_happen(self):
        """After one round, if Claude answers directly, only 2 calls happen total
        and the round-2 call (the one that got the direct answer) still had
        tools attached - it just wasn't used."""
        generator, client = make_generator()
        tool_manager = MagicMock()
        tool_manager.execute_tool.return_value = "some result"

        client.messages.create.side_effect = [
            make_tool_use_response("search_course_content", {"query": "q"}),
            make_text_response("final answer"),
        ]

        generator.generate_response(
            "q", tools=[{"name": "search_course_content"}], tool_manager=tool_manager
        )

        second_call_kwargs = client.messages.create.call_args_list[1].kwargs
        assert second_call_kwargs["tools"] == [{"name": "search_course_content"}]
        assert second_call_kwargs["tool_choice"] == {"type": "auto"}

    def test_tool_result_message_references_correct_tool_use_id(self):
        generator, client = make_generator()
        tool_manager = MagicMock()
        tool_manager.execute_tool.return_value = "result text"

        client.messages.create.side_effect = [
            make_tool_use_response("search_course_content", {"query": "q"}, tool_id="toolu_abc123"),
            make_text_response("final answer"),
        ]

        generator.generate_response(
            "q", tools=[{"name": "search_course_content"}], tool_manager=tool_manager
        )

        second_call_messages = client.messages.create.call_args_list[1].kwargs["messages"]
        tool_result_message = second_call_messages[-1]
        assert tool_result_message["role"] == "user"
        assert tool_result_message["content"][0]["tool_use_id"] == "toolu_abc123"
        assert tool_result_message["content"][0]["content"] == "result text"

    def test_no_tool_execution_when_tool_manager_missing(self):
        generator, client = make_generator()
        client.messages.create.return_value = make_tool_use_response(
            "search_course_content", {"query": "q"}
        )

        result = generator.generate_response("q", tools=[{"name": "search_course_content"}])

        # No tool_manager -> falls through to _retry_for_text since no text block exists.
        assert client.messages.create.call_count > 1
        assert "wasn't able" in result


class TestSequentialToolRounds:
    def test_two_dependent_rounds_succeed(self):
        generator, client = make_generator()
        tool_manager = MagicMock()
        tool_manager.execute_tool.side_effect = [
            "Course Title: MCP\nLessons:\n4. Building an MCP Client",
            "[Some Other Course - Lesson 2]\nRelated content about MCP clients.",
        ]

        client.messages.create.side_effect = [
            make_tool_use_response("get_course_outline", {"course_name": "MCP"}, tool_id="toolu_1"),
            make_tool_use_response(
                "search_course_content", {"query": "Building an MCP Client"}, tool_id="toolu_2"
            ),
            make_text_response("Course X's lesson 4 covers the same topic as Some Other Course."),
        ]

        tools = [{"name": "get_course_outline"}, {"name": "search_course_content"}]
        result = generator.generate_response(
            "Find a course that discusses the same topic as lesson 4 of course X",
            tools=tools,
            tool_manager=tool_manager,
        )

        assert client.messages.create.call_count == 3
        assert tool_manager.execute_tool.call_count == 2
        tool_manager.execute_tool.assert_any_call("get_course_outline", course_name="MCP")
        tool_manager.execute_tool.assert_any_call(
            "search_course_content", query="Building an MCP Client"
        )

        third_call_kwargs = client.messages.create.call_args_list[2].kwargs
        assert "tools" not in third_call_kwargs
        assert "tool_choice" not in third_call_kwargs

        third_call_messages = third_call_kwargs["messages"]
        assert third_call_messages[0] == {
            "role": "user",
            "content": "Find a course that discusses the same topic as lesson 4 of course X",
        }
        assert third_call_messages[1]["role"] == "assistant"
        assert third_call_messages[2]["role"] == "user"
        assert third_call_messages[2]["content"][0]["tool_use_id"] == "toolu_1"
        assert third_call_messages[3]["role"] == "assistant"
        assert third_call_messages[4]["role"] == "user"
        assert third_call_messages[4]["content"][0]["tool_use_id"] == "toolu_2"

        assert result == "Course X's lesson 4 covers the same topic as Some Other Course."

    def test_hard_cap_of_two_rounds_is_enforced(self):
        generator, client = make_generator()
        tool_manager = MagicMock()
        tool_manager.execute_tool.return_value = "some result"

        client.messages.create.side_effect = [
            make_tool_use_response("search_course_content", {"query": "q1"}, tool_id="toolu_1"),
            make_tool_use_response("search_course_content", {"query": "q2"}, tool_id="toolu_2"),
            make_text_response("final answer after cap"),
        ]

        result = generator.generate_response(
            "q", tools=[{"name": "search_course_content"}], tool_manager=tool_manager
        )

        # Never a 4th, tools-attached call - the loop stops at MAX_TOOL_ROUNDS
        # and the 3rd call is the forced, tools-less finalization.
        assert client.messages.create.call_count == 3
        assert tool_manager.execute_tool.call_count == 2
        third_call_kwargs = client.messages.create.call_args_list[2].kwargs
        assert "tools" not in third_call_kwargs
        assert result == "final answer after cap"

    def test_parallel_tool_calls_within_one_round_count_as_a_single_round(self):
        generator, client = make_generator()
        tool_manager = MagicMock()
        tool_manager.execute_tool.side_effect = ["result A", "result B"]

        client.messages.create.side_effect = [
            make_multi_tool_use_response(
                [
                    ("search_course_content", {"query": "topic A"}, "toolu_a"),
                    ("search_course_content", {"query": "topic B"}, "toolu_b"),
                ]
            ),
            make_text_response("Comparison of A and B."),
        ]

        result = generator.generate_response(
            "Compare topic A and topic B",
            tools=[{"name": "search_course_content"}],
            tool_manager=tool_manager,
        )

        # Two tool_use blocks in ONE response still only consumes one round.
        assert client.messages.create.call_count == 2
        assert tool_manager.execute_tool.call_count == 2
        tool_manager.execute_tool.assert_any_call("search_course_content", query="topic A")
        tool_manager.execute_tool.assert_any_call("search_course_content", query="topic B")

        second_call_messages = client.messages.create.call_args_list[1].kwargs["messages"]
        tool_result_message = second_call_messages[-1]
        results_by_id = {r["tool_use_id"]: r["content"] for r in tool_result_message["content"]}
        assert results_by_id == {"toolu_a": "result A", "toolu_b": "result B"}
        assert result == "Comparison of A and B."


class TestToolExecutionErrors:
    def test_single_tool_error_terminates_the_loop_early(self):
        generator, client = make_generator()
        tool_manager = MagicMock()
        tool_manager.execute_tool.side_effect = RuntimeError("boom")

        client.messages.create.side_effect = [
            make_tool_use_response("search_course_content", {"query": "q"}, tool_id="toolu_1"),
            make_text_response("Sorry, I couldn't retrieve that."),
        ]

        result = generator.generate_response(
            "q", tools=[{"name": "search_course_content"}], tool_manager=tool_manager
        )

        # Round 2 is never attempted - loop breaks immediately after the error.
        assert client.messages.create.call_count == 2
        second_call_kwargs = client.messages.create.call_args_list[1].kwargs
        assert "tools" not in second_call_kwargs

        tool_result = second_call_kwargs["messages"][-1]["content"][0]
        assert tool_result["is_error"] is True
        assert "boom" in tool_result["content"]
        assert result == "Sorry, I couldn't retrieve that."

    def test_partial_failure_among_parallel_calls_still_returns_successful_result(self):
        generator, client = make_generator()
        tool_manager = MagicMock()
        tool_manager.execute_tool.side_effect = ["good result", RuntimeError("bad tool")]

        client.messages.create.side_effect = [
            make_multi_tool_use_response(
                [
                    ("search_course_content", {"query": "ok"}, "toolu_ok"),
                    ("search_course_content", {"query": "bad"}, "toolu_bad"),
                ]
            ),
            make_text_response("Partial answer."),
        ]

        result = generator.generate_response(
            "q", tools=[{"name": "search_course_content"}], tool_manager=tool_manager
        )

        # No further tools-attached round is attempted after the failure.
        assert client.messages.create.call_count == 2
        second_call_kwargs = client.messages.create.call_args_list[1].kwargs
        assert "tools" not in second_call_kwargs

        results_by_id = {
            r["tool_use_id"]: r for r in second_call_kwargs["messages"][-1]["content"]
        }
        assert results_by_id["toolu_ok"]["content"] == "good result"
        assert "is_error" not in results_by_id["toolu_ok"]
        assert results_by_id["toolu_bad"]["is_error"] is True
        assert "bad tool" in results_by_id["toolu_bad"]["content"]
        assert result == "Partial answer."


class TestEmptyResponseRetry:
    def test_retries_on_empty_completion_then_succeeds(self):
        generator, client = make_generator()
        client.messages.create.side_effect = [
            make_text_response(""),
            make_text_response("Recovered answer."),
        ]

        result = generator.generate_response("q")

        assert result == "Recovered answer."

    def test_gives_up_after_max_retries(self):
        generator, client = make_generator()
        client.messages.create.return_value = make_text_response("")

        result = generator.generate_response("q")

        assert "wasn't able to generate an answer" in result

    def test_retry_after_forced_finalization_still_omits_tools(self):
        generator, client = make_generator()
        tool_manager = MagicMock()
        tool_manager.execute_tool.return_value = "some result"

        client.messages.create.side_effect = [
            make_tool_use_response("search_course_content", {"query": "q1"}, tool_id="toolu_1"),
            make_tool_use_response("search_course_content", {"query": "q2"}, tool_id="toolu_2"),
            make_text_response(""),
            make_text_response("Recovered."),
        ]

        result = generator.generate_response(
            "q", tools=[{"name": "search_course_content"}], tool_manager=tool_manager
        )

        assert client.messages.create.call_count == 4
        for call in client.messages.create.call_args_list[2:]:
            assert "tools" not in call.kwargs
        assert result == "Recovered."


class TestSystemPrompt:
    def test_no_longer_caps_at_one_tool_call(self):
        assert "One tool call per query maximum" not in AIGenerator.SYSTEM_PROMPT

    def test_mentions_two_round_capability(self):
        assert "2 sequential rounds" in AIGenerator.SYSTEM_PROMPT

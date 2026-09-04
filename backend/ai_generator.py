import anthropic
from typing import List, Optional, Dict, Any


class AIGenerator:
    """Handles interactions with Anthropic's Claude API for generating responses"""

    # Static system prompt to avoid rebuilding on each call
    SYSTEM_PROMPT = """ You are an AI assistant specialized in course materials and educational content with access to two tools for course information.

Tool Usage:
- `search_course_content`: use for questions about specific course content, concepts, or detailed educational materials within lessons
- `get_course_outline`: use for questions about a course's structure, syllabus, or lesson listing (e.g. "what lessons are in X", "give me the outline of Y")
- **You may use tools across up to 2 sequential rounds per query.** After seeing a tool's results, decide whether you already have enough information to answer, or whether one more tool call is needed.
- Use a second round only when it depends on what the first round returned - e.g. call `get_course_outline` to find a lesson's exact title, then call `search_course_content` with that title; or compare content pulled from two different searches. If the first round's results already answer the question, respond immediately rather than calling a tool again.
- Synthesize tool results into accurate, fact-based responses
- If a tool yields no results, state this clearly without offering alternatives
- If the results are non-empty but don't contain enough information to answer well (e.g. only tangential or transitional text), say so plainly and share whatever relevant information is available - always produce a text answer, never an empty response

Outline Responses:
- When answering an outline/structure question, always include the course title, the course link, and the full lesson list
- For each lesson, include both its number and its title

Response Protocol:
- **General knowledge questions**: Answer using existing knowledge without searching
- **Course-specific questions**: Use the appropriate tool first, then answer
- **No meta-commentary**:
 - Provide direct answers only — no reasoning process, search explanations, or question-type analysis
 - Do not mention "based on the search results"


All responses must be:
1. **Brief, Concise and focused** - Get to the point quickly
2. **Educational** - Maintain instructional value
3. **Clear** - Use accessible language
4. **Example-supported** - Include relevant examples when they aid understanding
Provide only the direct answer to what was asked.
"""

    # Maximum number of sequential tool-calling rounds Claude may use per query.
    # A round = one API call with tools attached that comes back as tool_use.
    MAX_TOOL_ROUNDS = 2

    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

        # Pre-build base API parameters
        self.base_params = {"model": self.model, "max_tokens": 2048}

    def generate_response(
        self,
        query: str,
        conversation_history: Optional[str] = None,
        tools: Optional[List] = None,
        tool_manager=None,
    ) -> str:
        """
        Generate AI response with optional tool usage and conversation context.

        Args:
            query: The user's question or request
            conversation_history: Previous messages for context
            tools: Available tools the AI can use
            tool_manager: Manager to execute tools

        Returns:
            Generated response as string
        """

        # Build system content efficiently - avoid string ops when possible
        system_content = (
            f"{self.SYSTEM_PROMPT}\n\nPrevious conversation:\n{conversation_history}"
            if conversation_history
            else self.SYSTEM_PROMPT
        )

        messages = [{"role": "user", "content": query}]

        if tools and tool_manager:
            return self._run_tool_loop(messages, system_content, tools, tool_manager)

        # No tools to execute (either none offered, or no manager to run them) -
        # a single call, exactly as before.
        api_params = {
            **self.base_params,
            "messages": messages,
            "system": system_content,
        }
        if tools:
            api_params["tools"] = tools
            api_params["tool_choice"] = {"type": "auto"}

        response = self.client.messages.create(**api_params)
        text = self._extract_text(response)
        if text:
            return text
        return self._retry_for_text(api_params)

    def _run_tool_loop(
        self,
        messages: List[Dict[str, Any]],
        system_content: str,
        tools: List,
        tool_manager,
    ) -> str:
        """
        Run up to MAX_TOOL_ROUNDS sequential tool-calling rounds, then force a
        final answer. Each round is a full API call with tools attached, so
        Claude can reason about one round's results before deciding whether it
        needs another tool call.

        Returns:
            Final response text after all tool rounds.
        """
        had_error = False

        for _ in range(self.MAX_TOOL_ROUNDS):
            api_params = {
                **self.base_params,
                "messages": messages,
                "system": system_content,
                "tools": tools,
                "tool_choice": {"type": "auto"},
            }
            response = self.client.messages.create(**api_params)

            if response.stop_reason != "tool_use":
                text = self._extract_text(response)
                if text:
                    return text
                return self._retry_for_text(api_params)

            tool_results, had_error = self._execute_tool_round(response, tool_manager)
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            if had_error:
                break

        return self._finalize_without_tools(messages, system_content, had_error)

    def _execute_tool_round(self, response, tool_manager) -> tuple:
        """
        Execute every tool_use block in one response (handles parallel tool
        calls within a single round).

        Returns:
            Tuple of (tool_result blocks for all calls in this round, whether any call failed)
        """
        tool_results = []
        had_error = False

        for content_block in response.content:
            if content_block.type != "tool_use":
                continue

            try:
                result = tool_manager.execute_tool(
                    content_block.name, **content_block.input
                )
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": content_block.id,
                    "content": result,
                }
            except Exception as exc:
                had_error = True
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": content_block.id,
                    "content": f"Tool '{content_block.name}' failed: {exc}",
                    "is_error": True,
                }

            tool_results.append(tool_result)

        return tool_results, had_error

    def _finalize_without_tools(
        self, messages: List[Dict[str, Any]], system_content: str, had_error: bool
    ) -> str:
        """
        Make the mandatory closing API call with tools omitted, so Claude must
        answer using only what's already been gathered instead of requesting
        another tool call it can't make.
        """
        if had_error:
            nudge = (
                "\n\nA tool call above returned an error. Do not attempt further tool calls. "
                "Answer using whatever information is available and plainly note what couldn't be retrieved."
            )
        else:
            nudge = (
                "\n\nYou have used the available tool-calling rounds. Do not call any more tools - "
                "answer the question now using the information already gathered."
            )

        final_params = {
            **self.base_params,
            "messages": messages,
            "system": system_content + nudge,
        }

        final_response = self.client.messages.create(**final_params)
        text = self._extract_text(final_response)
        if text:
            return text
        return self._retry_for_text(final_params)

    def _retry_for_text(self, params: Dict[str, Any], retries: int = 4) -> str:
        """Retry a completed-but-empty response.

        Current models occasionally end a turn with no text block at all
        (empty completion) - a retry with the same params usually succeeds.
        """
        for _ in range(retries):
            response = self.client.messages.create(**params)
            text = self._extract_text(response)
            if text:
                return text
        return "I wasn't able to generate an answer from the search results. Please try rephrasing your question."

    def _extract_text(self, response) -> Optional[str]:
        """Extract the answer text from a response's content blocks.

        Current models may emit non-text blocks (e.g. ThinkingBlock) before
        the text block, so content[0] cannot be assumed to be the answer.
        Returns None if no non-empty text block is present.
        """
        for block in response.content:
            if block.type == "text" and block.text:
                return block.text
        return None

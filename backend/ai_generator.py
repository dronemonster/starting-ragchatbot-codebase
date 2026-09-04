import anthropic
from typing import List, Optional, Dict, Any

class AIGenerator:
    """Handles interactions with Anthropic's Claude API for generating responses"""
    
    # Static system prompt to avoid rebuilding on each call
    SYSTEM_PROMPT = """ You are an AI assistant specialized in course materials and educational content with access to two tools for course information.

Tool Usage:
- `search_course_content`: use for questions about specific course content, concepts, or detailed educational materials within lessons
- `get_course_outline`: use for questions about a course's structure, syllabus, or lesson listing (e.g. "what lessons are in X", "give me the outline of Y")
- **One tool call per query maximum**
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
    
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        
        # Pre-build base API parameters
        self.base_params = {
            "model": self.model,
            "max_tokens": 2048
        }
    
    def generate_response(self, query: str,
                         conversation_history: Optional[str] = None,
                         tools: Optional[List] = None,
                         tool_manager=None) -> str:
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
        
        # Prepare API call parameters efficiently
        api_params = {
            **self.base_params,
            "messages": [{"role": "user", "content": query}],
            "system": system_content
        }
        
        # Add tools if available
        if tools:
            api_params["tools"] = tools
            api_params["tool_choice"] = {"type": "auto"}
        
        # Get response from Claude
        response = self.client.messages.create(**api_params)

        # Handle tool execution if needed
        if response.stop_reason == "tool_use" and tool_manager:
            return self._handle_tool_execution(response, api_params, tool_manager)

        # Return direct response
        text = self._extract_text(response)
        if text:
            return text
        return self._retry_for_text(api_params)
    
    def _handle_tool_execution(self, initial_response, base_params: Dict[str, Any], tool_manager):
        """
        Handle execution of tool calls and get follow-up response.
        
        Args:
            initial_response: The response containing tool use requests
            base_params: Base API parameters
            tool_manager: Manager to execute tools
            
        Returns:
            Final response text after tool execution
        """
        # Start with existing messages
        messages = base_params["messages"].copy()
        
        # Add AI's tool use response
        messages.append({"role": "assistant", "content": initial_response.content})
        
        # Execute all tool calls and collect results
        tool_results = []
        for content_block in initial_response.content:
            if content_block.type == "tool_use":
                tool_result = tool_manager.execute_tool(
                    content_block.name, 
                    **content_block.input
                )
                
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": content_block.id,
                    "content": tool_result
                })
        
        # Add tool results as single message
        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        
        # Prepare final API call without tools. Nudge explicitly against
        # searching again - without it, the model can decide it wants another
        # search, find none available, and stop with no text at all.
        final_params = {
            **self.base_params,
            "messages": messages,
            "system": base_params["system"] + "\n\nYou have already searched and have the results above. Do not search again - answer the question now using only that information."
        }
        
        # Get final response
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
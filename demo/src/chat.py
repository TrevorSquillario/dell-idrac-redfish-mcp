import json
import os
from openai import OpenAI
from fastmcp import Client as MCPClient
import asyncio
import sys
import logging
from logging_config import configure_logging

# Ensure logging is configured when this module is imported so
# module/class-level loggers behave consistently.
configure_logging()
_log = logging.getLogger(__name__)

# Configuration
MODEL = os.getenv("MODEL_NAME", "llama3.2")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8080/mcp")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "http://localhost:8081/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "EMPTY")
# ------------------------------------------------------------
# Step 1: Discover available tools from MCP server
# ------------------------------------------------------------
async def load_mcp_tools():
    """Connect to MCP server and get list of available tools"""
    try:
        async with MCPClient(MCP_SERVER_URL) as mcp:
            # Ask server: "What tools do you have?"
            tools_list = await mcp.list_tools()

            # Convert to format Ollama understands
            ollama_tools = []
            for tool in tools_list:
                ollama_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                })
            return ollama_tools
    except Exception as e:
        _log.error("❌ ERROR connecting to MCP server: %s", e)
        _log.error("Make sure the server is running: python mcp_server.py")
        sys.exit(1)

# ------------------------------------------------------------
# Step 2: Execute a tool when AI requests it
# ------------------------------------------------------------
async def execute_tool(tool_name: str, arguments: dict):
    """Call a tool on the MCP server with given arguments"""
    try:
        async with MCPClient(MCP_SERVER_URL) as mcp:
            result = await mcp.call_tool(tool_name, arguments)
            return result
    except Exception as e:
        _log.error("❌ ERROR executing tool %s: %s", tool_name, e)
        return {"error": str(e)}

# ------------------------------------------------------------
# Step 3: Main conversation loop
# ------------------------------------------------------------
async def main():
    _log.info("🔍 Loading MCP tools...")
    tools = await load_mcp_tools()
    _log.info("✅ Loaded %d tools:", len(tools))
    for tool in tools:
        _log.info("   - %s: %s", tool['function']['name'], tool['function']['description'])
    _log.info("")

    # The user's question
    user_msg = "Get the lifecycle logs from the last 5 days for host: localhost port: 8001 severity: critical"
    _log.info("👤 User: %s\n", user_msg)

    client = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_API_BASE,
    )

    # Initial call: let the model decide if it wants to call a function (tool)
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": user_msg}],
            tools=tools,
            tool_choice="auto",
        )
    except Exception as e:
        _log.error("❌ ERROR calling OpenAI local API: %s", e)
        _log.error("Make sure the local OpenAI-compatible API is running at %s", OPENAI_API_BASE)
        sys.exit(1)

    choice = response.choices[0]
    # Convert choice to plain data (support pydantic v2/v1 and plain dict)
    if hasattr(choice, "model_dump"):
        choice_data = choice.model_dump()
    elif hasattr(choice, "dict"):
        choice_data = choice.dict()
    elif isinstance(choice, dict):
        choice_data = choice
    else:
        choice_data = {}

    # Extract message object and normalize to dict
    raw_message = choice_data.get("message") or {}
    if hasattr(raw_message, "model_dump"):
        message_data = raw_message.model_dump()
    elif hasattr(raw_message, "dict"):
        message_data = raw_message.dict()
    elif isinstance(raw_message, dict):
        message_data = raw_message
    else:
        message_data = {}

    # Check for Qwen-style tool calls at choice or message level
    tool_calls = choice_data.get("tool_calls") or message_data.get("tool_calls")
    if tool_calls:
        _log.debug("Detected tool_calls from model")
    # If model didn't request a function and no tool_calls, print direct answer
    if not tool_calls and not (message_data.get("function_call") or choice_data.get("function_call")):
        _log.info("🤖 AI answered directly (no tools needed):")
        _log.info(message_data.get("content") or choice_data.get("content"))
        return

    # If we detected Qwen-style tool_calls, execute them
    if tool_calls:
        # Start conversation history (user + assistant message)
        messages = [{"role": "user", "content": user_msg}]
        messages.append(message_data)

        for tool_call in tool_calls:
            call_id: str = tool_call.get("id")
            fn_call = tool_call.get("function") or tool_call.get("tool")
            if not fn_call:
                continue
            fn_name: str = fn_call.get("name")
            fn_args_raw = fn_call.get("arguments", "{}")
            try:
                fn_args: dict = json.loads(fn_args_raw) if isinstance(fn_args_raw, str) else fn_args_raw
            except Exception:
                fn_args = {}

            _log.info("🔧 Tool requested: %s", fn_name)
            _log.debug("📝 Arguments: %s", fn_args)

            tool_result = await execute_tool(fn_name, fn_args)
            fn_res: str = json.dumps(tool_result) if isinstance(tool_result, dict) else str(tool_result)

            messages.append({
                "role": "tool",
                "content": fn_res,
                "tool_call_id": call_id,
            })

        # Ask the model to produce a final answer after tool execution
        final = client.chat.completions.create(
            model=MODEL,
            messages=messages,
        )

        final_choice = final.choices[0]
        if hasattr(final_choice, "model_dump"):
            final_choice_data = final_choice.model_dump()
        elif hasattr(final_choice, "dict"):
            final_choice_data = final_choice.dict()
        elif isinstance(final_choice, dict):
            final_choice_data = final_choice
        else:
            final_choice_data = {}

        final_message = final_choice_data.get("message") or {}
        if hasattr(final_message, "model_dump"):
            final_message_data = final_message.model_dump()
        elif hasattr(final_message, "dict"):
            final_message_data = final_message.dict()
        elif isinstance(final_message, dict):
            final_message_data = final_message
        else:
            final_message_data = {}

        _log.info("🤖 Final AI response:")
        _log.info(final_message_data.get("content") if isinstance(final_message_data, dict) else str(final_message_data))
        return

    # Fallback: legacy `function_call` handling
    if not (isinstance(message_data, dict) and message_data.get("function_call")):
        _log.info("🤖 AI answered directly (no tools needed):")
        _log.info(message_data.get("content") if isinstance(message_data, dict) else str(message_data))
        return

    func_call = message_data["function_call"]
    tool_name = func_call.get("name")
    args_raw = func_call.get("arguments", "{}")

    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
    except Exception:
        args = {}

    _log.info("🔧 Tool requested: %s", tool_name)
    _log.debug("📝 Arguments: %s", args)

    tool_result = await execute_tool(tool_name, args)
    _log.info("✅ Tool result: %s\n", tool_result)

    messages = [
        {"role": "user", "content": user_msg},
        {"role": "assistant", "content": message_data.get("content", "") if isinstance(message_data, dict) else str(message_data), "function_call": func_call},
        {"role": "function", "name": tool_name, "content": json.dumps(tool_result) if isinstance(tool_result, dict) else str(tool_result)},
    ]

    final = client.chat.completions.create(
        model=MODEL,
        messages=messages,
    )

    final_choice = final.choices[0]
    if hasattr(final_choice, "model_dump"):
        final_choice_data = final_choice.model_dump()
    elif hasattr(final_choice, "dict"):
        final_choice_data = final_choice.dict()
    elif isinstance(final_choice, dict):
        final_choice_data = final_choice
    else:
        final_choice_data = {}

    final_message = final_choice_data.get("message") or {}
    if hasattr(final_message, "model_dump"):
        final_message_data = final_message.model_dump()
    elif hasattr(final_message, "dict"):
        final_message_data = final_message.dict()
    elif isinstance(final_message, dict):
        final_message_data = final_message
    else:
        final_message_data = {}

    _log.info("🤖 Final AI response:")
    _log.info(final_message_data.get("content") if isinstance(final_message_data, dict) else str(final_message_data))

if __name__ == "__main__":
    asyncio.run(main())
#!/usr/bin/env python3
"""Simple CLI chat client for a local OpenAI-compatible + FastMCP server.

Defaults:
- OpenAI-compatible API: ${MCP_BASE_URL:-http://localhost:8080}/v1/chat/completions
- Tool call endpoint (tried in order): /call_tool, /tools/call

Usage: run the script and type messages. Press Ctrl+C to quit.
"""
from __future__ import annotations

import os
import sys
import json
import requests
from typing import List, Dict, Any, Optional


BASE = os.getenv("MCP_BASE_URL", "http://localhost:8080")
CHAT_PATH = "/v1/chat/completions"
TOOL_PATHS = ["/call_tool", "/tools/call"]
API_KEY = os.getenv("OPENAI_API_KEY")


def post_json(path: str, payload: Dict[str, Any]) -> requests.Response:
    url = BASE.rstrip("/") + path
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    return requests.post(url, headers=headers, json=payload, timeout=30)


def try_call_tool(name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = {"name": name, "arguments": arguments}
    for p in TOOL_PATHS:
        try:
            resp = post_json(p, payload)
        except Exception:
            continue
        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text}
    return None


def chat_once(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    body = {"model": os.getenv("MCP_MODEL", "gpt-4o-mini"), "messages": messages}
    resp = post_json(CHAT_PATH, body)
    resp.raise_for_status()
    return resp.json()


def extract_content(chat_response: Dict[str, Any]) -> Dict[str, Any]:
    # Try common OpenAI-like shapes
    if "choices" in chat_response and len(chat_response["choices"]) > 0:
        c = chat_response["choices"][0]
        # function_call style
        message = c.get("message") or c.get("delta") or {}
        return message
    # fallback whole response
    return {"content": json.dumps(chat_response)}


def main() -> None:
    print("Simple MCP/OpenAI CLI chat — connecting to", BASE)
    messages: List[Dict[str, str]] = []
    system = os.getenv("SYSTEM_PROMPT")
    if system:
        messages.append({"role": "system", "content": system})

    try:
        while True:
            try:
                prompt = input("You: ")
            except EOFError:
                break
            if not prompt.strip():
                continue
            messages.append({"role": "user", "content": prompt})

            try:
                raw = chat_once(messages)
            except requests.HTTPError as e:
                print("Request failed:", e)
                continue
            except Exception as e:
                print("Error calling chat endpoint:", e)
                continue

            message = extract_content(raw)

            # If model requested a function/tool call, attempt to invoke
            func_call = message.get("function_call") or message.get("tool_call")
            if func_call and isinstance(func_call, dict):
                name = func_call.get("name")
                args_raw = func_call.get("arguments") or func_call.get("args") or "{}"
                try:
                    if isinstance(args_raw, str):
                        args = json.loads(args_raw)
                    else:
                        args = args_raw
                except Exception:
                    args = {}
                print(f"Invoking tool {name} with args {args}")
                result = try_call_tool(name, args)
                print("Tool result:", json.dumps(result, indent=2))
                # append tool result as assistant message and continue
                messages.append({"role": "assistant", "content": json.dumps(result)})
                continue

            # otherwise print assistant content
            content = message.get("content") or message.get("text") or json.dumps(message)
            print("Assistant:", content)
            messages.append({"role": "assistant", "content": content})

    except KeyboardInterrupt:
        print("\nExiting.")


if __name__ == "__main__":
    main()

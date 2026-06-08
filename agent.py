import os
import sys
import json
import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv

load_dotenv()

# Ensure local connection works reliably on macOS (avoiding IPv6 resolution issues)
os.environ.setdefault("OLLAMA_HOST", os.getenv("OLLAMA_HOST", "127.0.0.1"))

from logger import log_info, log_error

async def check_and_run_tools(messages: list, model_name: str, session_name: str = "default") -> tuple[list[dict], dict[str, any], int]:
    """
    Checks if the model requests any tool calls in a loop (up to 5 steps) to support sequential/multi-step reasoning.
    Exposes and executes tools dynamically using a subprocess Model Context Protocol (MCP) server.
    Returns:
      1. A list of tool messages (assistant tool_calls & tool responses) to append to history.
      2. A dictionary of executed tool results mapped by tool name.
      3. The number of LLM calls made during checking.
    """
    tool_messages = []
    tool_results = {}
    llm_calls = 0
    current_messages = list(messages)
    
    # Configure MCP stdio parameters targeting our server script
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["mcp_server.py"],
        env={**os.environ}
    )
    
    try:
        log_info(session_name, "Spawning MCP server subprocess...")
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                log_info(session_name, "Initializing MCP Client Session...")
                await session.initialize()
                
                # Fetch available tools dynamically from MCP server
                mcp_tools_res = await session.list_tools()
                mcp_tools = mcp_tools_res.tools
                
                # Map MCP tools to Ollama tool schema format
                ollama_tools = []
                for tool in mcp_tools:
                    ollama_tools.append({
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.inputSchema
                        }
                    })
                
                log_info(session_name, f"Discovered {len(ollama_tools)} tool(s) from MCP server: {[t['function']['name'] for t in ollama_tools]}")
                
                # ReAct Multi-step reasoning loop (up to 5 iterations)
                for iteration in range(5):
                    log_info(session_name, f"[LLM Call] Checking if the model requests any tool calls (iteration {iteration + 1})...")
                    llm_calls += 1
                    
                    # Call async ollama chat
                    client = ollama.AsyncClient()
                    response = await client.chat(
                        model=model_name,
                        messages=current_messages + tool_messages,
                        tools=ollama_tools,
                        options={"temperature": 0.0}
                    )
                    
                    tool_calls = getattr(response.message, "tool_calls", None)
                    if not tool_calls:
                        log_info(session_name, f"No more tool calls requested by the model at iteration {iteration + 1}.")
                        break
                        
                    log_info(session_name, f"Model requested {len(tool_calls)} tool call(s) at iteration {iteration + 1}: {[c.function.name for c in tool_calls]}")
                    
                    # Build assistant's tool-calling response structure
                    assistant_tool_msg = {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": call.function.name,
                                    "arguments": call.function.arguments
                                }
                            } for call in tool_calls
                        ]
                    }
                    tool_messages.append(assistant_tool_msg)
                    
                    # Execute tool calls via MCP client
                    for call in tool_calls:
                        func_name = call.function.name
                        args = call.function.arguments or {}
                        
                        log_info(session_name, f"Executing tool '{func_name}' via MCP with args: {args}")
                        
                        # Call MCP tool
                        result_block = await session.call_tool(func_name, arguments=args)
                        
                        # Extract string response
                        raw_output = ""
                        if result_block.content and len(result_block.content) > 0:
                            raw_output = result_block.content[0].text
                            
                        # Parse JSON results if returned, else store raw string
                        try:
                            result = json.loads(raw_output)
                        except Exception:
                            result = {"content": raw_output}
                            
                        tool_results[func_name] = result
                        
                        # Extract pre-formatted context or fallback to json string
                        if isinstance(result, dict) and "content" in result:
                            content = result["content"]
                        else:
                            content = json.dumps(result)
                            
                        tool_response_msg = {
                            "role": "tool",
                            "name": func_name,
                            "content": content
                        }
                        tool_messages.append(tool_response_msg)
                        log_info(session_name, f"Tool '{func_name}' execution completed successfully.")
                        
    except Exception as e:
        log_error(session_name, f"Error in check_and_run_tools: {e}")
        
    return tool_messages, tool_results, llm_calls



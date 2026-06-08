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

from logger import log_info, log_error, get_session_log_file

async def get_mcp_tools(session_name: str = "health") -> list:
    """
    Connects to the MCP server subprocess temporarily to retrieve list of active tools.
    """
    log_filepath = get_session_log_file(session_name)
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["mcp_server.py"],
        env={
            **os.environ,
            "SESSION_NAME": session_name,
            "SESSION_LOG_FILE": log_filepath
        }
    )
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                mcp_tools_res = await session.list_tools()
                return [
                    {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": t.inputSchema
                    } for t in mcp_tools_res.tools
                ]
    except Exception as e:
        log_error(session_name, f"Error in get_mcp_tools: {e}")
        return []

async def check_and_run_tools(messages: list, model_name: str, session_name: str = "default"):
    """
    Checks if the model requests any tool calls in a loop (up to 5 steps) to support sequential/multi-step reasoning.
    Exposes and executes tools dynamically using a subprocess Model Context Protocol (MCP) server.
    Yields trace events during execution, ending with the final compiled tool result state.
    """
    tool_messages = []
    tool_results = {}
    llm_calls = 0
    current_messages = list(messages)
    
    log_filepath = get_session_log_file(session_name)
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["mcp_server.py"],
        env={
            **os.environ,
            "SESSION_NAME": session_name,
            "SESSION_LOG_FILE": log_filepath
        }
    )
    
    try:
        log_info(session_name, "Spawning MCP server subprocess...")
        yield {"type": "status", "status": "spawning", "message": "Spawning MCP server subprocess..."}
        
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                log_info(session_name, "Initializing MCP Client Session...")
                yield {"type": "status", "status": "initializing", "message": "Initializing MCP Client Session..."}
                await session.initialize()
                
                # Fetch tools via JSON-RPC list_tools
                yield {"type": "rpc", "direction": "request", "method": "tools/list", "params": {}}
                mcp_tools_res = await session.list_tools()
                mcp_tools = mcp_tools_res.tools
                
                tools_list = [
                    {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                    for t in mcp_tools
                ]
                yield {"type": "rpc", "direction": "response", "method": "tools/list", "result": {"tools": tools_list}}
                yield {"type": "status", "status": "discovered", "tools": tools_list, "message": f"Discovered {len(tools_list)} tool(s) from MCP server."}
                
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
                    
                    # Yield reasoning thought start
                    yield {
                        "type": "react_step",
                        "iteration": iteration + 1,
                        "step_type": "thought",
                        "message": f"LLM Turn {iteration + 1}: Checking model tool requests..."
                    }
                    
                    # Call async ollama chat
                    client = ollama.AsyncClient()
                    
                    yield {
                        "type": "rpc",
                        "direction": "request",
                        "method": "ollama/chat",
                        "params": {
                            "model": model_name,
                            "messages": current_messages + tool_messages,
                            "tools_count": len(ollama_tools)
                        }
                    }
                    
                    response = await client.chat(
                        model=model_name,
                        messages=current_messages + tool_messages,
                        tools=ollama_tools,
                        options={"temperature": 0.0}
                    )
                    
                    tool_calls = getattr(response.message, "tool_calls", None)
                    
                    # Yield Ollama chat RPC response
                    yield {
                        "type": "rpc",
                        "direction": "response",
                        "method": "ollama/chat",
                        "result": {
                            "content": response.message.content or "",
                            "tool_calls": [
                                {"name": c.function.name, "arguments": c.function.arguments}
                                for c in tool_calls
                            ] if tool_calls else []
                        }
                    }
                    
                    if not tool_calls:
                        log_info(session_name, f"No more tool calls requested by the model at iteration {iteration + 1}.")
                        yield {
                            "type": "react_step",
                            "iteration": iteration + 1,
                            "step_type": "completed",
                            "message": "Model finalized reasoning. Generating final answer..."
                        }
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
                        yield {
                            "type": "react_step",
                            "iteration": iteration + 1,
                            "step_type": "tool_call",
                            "tool_name": func_name,
                            "arguments": args,
                            "message": f"Calling tool '{func_name}'..."
                        }
                        
                        # RPC tool call request
                        yield {
                            "type": "rpc",
                            "direction": "request",
                            "method": "tools/call",
                            "params": {
                                "name": func_name,
                                "arguments": args
                            }
                        }
                        
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
                        
                        # RPC tool call response
                        yield {
                            "type": "rpc",
                            "direction": "response",
                            "method": "tools/call",
                            "result": result
                        }
                        
                        # Yield tool execution result
                        yield {
                            "type": "react_step",
                            "iteration": iteration + 1,
                            "step_type": "tool_result",
                            "tool_name": func_name,
                            "result": result,
                            "message": f"Tool '{func_name}' finished executing."
                        }
                        
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
        yield {"type": "status", "status": "error", "message": f"Error: {e}"}
        
    # Yield final results
    yield {
        "type": "result",
        "tool_messages": tool_messages,
        "tool_results": tool_results,
        "llm_calls": llm_calls
    }




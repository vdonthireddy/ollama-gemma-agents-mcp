import os
import json
from fastmcp import FastMCP
from tools.search_web import handler as search_web_handler
from tools.calculator import handler as calculate_handler

# Initialize the FastMCP server
mcp = FastMCP("GemmaJnana Tools Server")

# Read session name from environment
SESSION_NAME = os.getenv("SESSION_NAME", "default")

@mcp.tool()
def search_web(query: str) -> str:
    """Search the internet/web for latest information on a given query."""
    result = search_web_handler(query, session_name=SESSION_NAME)
    return json.dumps(result)

@mcp.tool()
def calculate(expression: str) -> str:
    """Perform basic mathematical calculations (addition, subtraction, multiplication, division)."""
    result = calculate_handler(expression, session_name=SESSION_NAME)
    return json.dumps(result)

if __name__ == "__main__":
    mcp.run()

from .search_web import SCHEMA as search_web_schema, handler as search_web_handler
from .calculator import SCHEMA as calculate_schema, handler as calculate_handler

TOOLS = [
    search_web_schema,
    calculate_schema
]

TOOL_REGISTRY = {
    "search_web": search_web_handler,
    "calculate": calculate_handler
}

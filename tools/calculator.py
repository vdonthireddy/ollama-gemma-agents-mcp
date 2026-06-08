SCHEMA = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": "Perform basic mathematical calculations (addition, subtraction, multiplication, division).",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The mathematical expression to evaluate (e.g., '12 * 45' or '100 / (5 + 5)'). Only arithmetic operations are supported."
                }
            },
            "required": ["expression"]
        }
    }
}

from logger import log_info, log_error

def handler(expression: str, session_name: str = "default") -> dict:
    try:
        log_info(session_name, f"Executing calculation: '{expression}'")
        # Safe check to restrict character set to basic numbers and arithmetic operators
        allowed_chars = set("0123456789+-*/(). ")
        if not all(char in allowed_chars for char in expression):
            log_error(session_name, f"Invalid characters in math expression: '{expression}'")
            return {"error": "Invalid characters in expression. Only basic arithmetic is allowed."}
        
        # Evaluate safely without builtins
        result = eval(expression, {"__builtins__": None}, {})
        log_info(session_name, f"Calculation result: {result}")
        return {"expression": expression, "result": result}
    except Exception as e:
        log_error(session_name, f"Evaluation error: {e}")
        return {"error": f"Evaluation error: {str(e)}"}

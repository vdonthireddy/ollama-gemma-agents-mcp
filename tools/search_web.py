SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Search the internet/web for latest information on a given query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to search the web for."
                }
            },
            "required": ["query"]
        }
    }
}

from logger import log_info, log_error

def handler(query: str, session_name: str = "default") -> dict:
    try:
        log_info(session_name, f"Executing search query: '{query}'")
        from ddgs import DDGS
        with DDGS() as ddgs:
            raw_results = ddgs.text(query, max_results=4)
            results = []
            for r in raw_results:
                results.append({
                    "title": r.get("title", ""),
                    "href": r.get("href", ""),
                    "body": r.get("body", "")
                })
            
            log_info(session_name, f"Search completed. Found {len(results)} results.")
            
            # Format context string for LLM response
            context = ""
            for i, r in enumerate(results, 1):
                context += f"[{i}] Title: {r['title']}\nURL: {r['href']}\nSnippet: {r['body']}\n\n"
                
            return {
                "query": query,
                "results": results,
                "content": f"Search Results for '{query}':\n\n{context}"
            }
    except Exception as e:
        log_error(session_name, f"Web search error: {e}")
        return {
            "query": query,
            "results": [],
            "content": f"Web search failed: {e}"
        }

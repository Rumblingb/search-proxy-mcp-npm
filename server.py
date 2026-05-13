#!/usr/bin/env python3
"""AI Search Proxy MCP — Web search for AI agents via DuckDuckGo (free, no auth).

Usage:
  python3 server.py                    # Free tier (50 calls/instance)
  python3 server.py --pro-key PROL_XXX  # Pro tier (unlimited)
"""

import json, re, urllib.parse, sys, os, time, collections
from mcp.server import Server
from mcp.server.stdio import stdio_server
import httpx

server = Server("search-proxy-mcp")
DDG_BASE = "https://duckduckgo.com"
DDG_API = "https://api.duckduckgo.com"

# ─── Rate Limiting & Pro Key ───────────────────────────────────────────
FREE_LIMIT = 50
PRO_KEYS = {"PROL_AGENTPAY_DEMO": "demo"}  # Demo key for testing

# Parse --pro-key from command line
PRO_KEY = None
for i, arg in enumerate(sys.argv):
    if arg == "--pro-key" and i + 1 < len(sys.argv):
        PRO_KEY = sys.argv[i + 1]
        break

IS_PRO = PRO_KEY in PRO_KEYS
call_counter = 0

STRIPE_LINK = "https://buy.stripe.com/5kQ3cxflRabW9PW1AD1oI0r"  # $19/mo

def check_rate_limit():
    """Check if free tier has exceeded limit. Returns error dict or None."""
    global call_counter
    if IS_PRO:
        return None
    call_counter += 1
    if call_counter > FREE_LIMIT:
        remaining = call_counter - FREE_LIMIT
        return {
            "error": f"Free tier limit reached ({FREE_LIMIT} calls). Upgrade to Pro for unlimited access.",
            "isError": True,
            "next_steps": [
                f"Purchase Pro at {STRIPE_LINK} ($19/mo, unlimited)",
                "Restart the server to reset the free counter",
                "Use --pro-key PROL_XXX to run in Pro mode"
            ],
            "calls_used": call_counter,
            "limit": FREE_LIMIT,
            "over_by": remaining
        }
    return None

# ─── Core Search Functions ─────────────────────────────────────────────

async def _ddg_instant(query):
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        resp = await client.get(f"{DDG_API}/", params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"})
        resp.raise_for_status()
        return resp.json()

async def _ddg_html(query, max_results=10):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    params = {"q": query, "ia": "web"}
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(f"{DDG_BASE}/html/", params=params, headers=headers)
        resp.raise_for_status()
        
        results = []
        for match in re.finditer(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*href="[^"]*"[^>]*>([^<]*)</a>',
            resp.text, re.DOTALL
        ):
            url, title, snippet = match.groups()
            results.append({"title": title.strip(), "url": url, "snippet": snippet.strip() if snippet else ""})
            if len(results) >= max_results:
                break
        
        if not results:
            for match in re.finditer(
                r'<a[^>]*href="(https?://[^"]+)"[^>]*class="[^"]*result[^"]*"[^>]*>.*?<h2[^>]*>([^<]+)</h2>.*?<a[^>]*class="[^"]*snippet[^"]*"[^>]*>([^<]*)</a>',
                resp.text, re.DOTALL
            ):
                url, title, snippet = match.groups()
                results.append({"title": title.strip(), "url": url, "snippet": snippet.strip() if snippet else ""})
                if len(results) >= max_results:
                    break
        
        return results

# ─── MCP Tools ─────────────────────────────────────────────────────────

@server.tool(
    name="search_web",
    description="Search the web for information. Returns instant answers and organic results. Free tier: 50 calls.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results (1-20)", "default": 5}
        },
        "required": ["query"]
    }
)
async def search_web(query: str, max_results: int = 5) -> str:
    limit_check = check_rate_limit()
    if limit_check:
        return json.dumps(limit_check, indent=2)
    
    try:
        max_results = min(max_results, 20)
        instant = await _ddg_instant(query)
        html_results = await _ddg_html(query, max_results)
        
        result = {
            "query": query,
            "instant_answer": instant.get("AbstractText", ""),
            "instant_source": instant.get("AbstractSource", ""),
            "answer": instant.get("Answer", ""),
            "answer_type": instant.get("AnswerType", ""),
            "results": html_results[:max_results],
            "result_count": len(html_results),
        }
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "isError": True, "next_steps": ["Try a different query", "Check network connectivity"]}, indent=2)

@server.tool(
    name="search_news",
    description="Search recent news using DuckDuckGo. Free tier: 50 calls.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "News search query"},
            "max_results": {"type": "integer", "default": 5}
        },
        "required": ["query"]
    }
)
async def search_news(query: str, max_results: int = 5) -> str:
    limit_check = check_rate_limit()
    if limit_check:
        return json.dumps(limit_check, indent=2)
    
    try:
        max_results = min(max_results, 20)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept-Language": "en-US,en;q=0.9"}
        params = {"q": query, "t": "n", "ia": "news"}
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(f"{DDG_BASE}/html/", params=params, headers=headers)
            resp.raise_for_status()
            results = []
            for match in re.finditer(r'<a[^>]*href="(https?://[^"]+)"[^>]*>([^<]+)</a>', resp.text):
                url, title = match.groups()
                if any(s in url for s in ["duckduckgo.com", "duck.com"]):
                    continue
                results.append({"title": title.strip(), "url": url})
                if len(results) >= max_results:
                    break
            return json.dumps({"query": query, "results": results}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "isError": True}, indent=2)

@server.tool(
    name="search_get_page_content",
    description="Fetch and extract readable text content from a URL. Free tier: 50 calls.",
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "max_chars": {"type": "integer", "description": "Max characters to return", "default": 5000}
        },
        "required": ["url"]
    }
)
async def search_get_page_content(url: str, max_chars: int = 5000) -> str:
    limit_check = check_rate_limit()
    if limit_check:
        return json.dumps(limit_check, indent=2)
    
    try:
        max_chars = min(max_chars, 50000)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            text = re.sub(r'<[^>]+>', ' ', resp.text)
            text = re.sub(r'\s+', ' ', text).strip()
            truncated = len(text) > max_chars
            return json.dumps({
                "url": url, "status": resp.status_code,
                "content_type": resp.headers.get("content-type", ""),
                "content": text[:max_chars], "truncated": truncated,
                "total_chars": len(text),
            }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "isError": True}, indent=2)

def main():
    import anyio
    async def run():
        async with stdio_server() as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())
    anyio.run(run)

if __name__ == "__main__":
    main()

"""Start the server over stdio and call each tool, like an AI assistant would.

    python scripts/demo_client.py
"""

import asyncio
import sys

from mcp import Client, StdioServerParameters

CALLS = [
    ("search_postings", {"skill": "rust", "remote_only": True, "limit": 3}),
    ("count_postings_by_company", {"skill": "Python", "top_n": 3}),
    ("get_posting", {"posting_id": "JP-038"}),
    # Bad input, to show the error messages the model receives.
    ("search_postings", {"skill": "Pyhton"}),
    ("search_postings", {"skill": "Python", "limit": 500}),
    ("get_posting", {"posting_id": "JP-7"}),
]


async def main() -> None:
    server = StdioServerParameters(command=sys.executable, args=["-m", "job_postings_mcp"])
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
        print("Tools:", ", ".join(t.name for t in tools))

        for name, args in CALLS:
            result = await client.call_tool(name, args)
            status = "ERROR" if result.is_error else "OK"
            print(f"\n=== {name}({args}) -> {status}")
            print(result.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())

import argparse
import asyncio
import json
import os
from pathlib import Path
from .graph import Finding, GraphService


async def run(args):
    from dotenv import load_dotenv
    from graphiti_core import Graphiti
    load_dotenv()
    required = ("OPENAI_API_KEY", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise ValueError("Missing environment variables: " + ", ".join(missing))
    service = GraphService(Graphiti(os.environ["NEO4J_URI"], os.environ["NEO4J_USER"],
                                   os.environ["NEO4J_PASSWORD"]),
                           os.getenv("GRAPHITI_GROUP_ID", "startup_finder_de"))
    try:
        if args.command == "init":
            await service.initialize()
            print("Graph initialized")
        elif args.command == "ingest":
            findings = [Finding.from_dict(json.loads(line))
                        for line in Path(args.file).read_text().splitlines() if line.strip()]
            for finding in findings:
                print(json.dumps(await service.ingest(finding), ensure_ascii=False))
        else:
            print(json.dumps(await service.search(args.query), ensure_ascii=False, indent=2))
    finally:
        await service.close()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("ingest").add_argument("file")
    sub.add_parser("search").add_argument("query")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()

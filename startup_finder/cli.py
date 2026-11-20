import argparse
import asyncio
import json
from pathlib import Path
from .graph import Finding, GraphService
from .config import Settings
from .model_factory import create_graphiti


async def run(args):
    from dotenv import load_dotenv
    load_dotenv()
    settings = Settings.from_env()
    service = GraphService(create_graphiti(settings), settings.group_id)
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

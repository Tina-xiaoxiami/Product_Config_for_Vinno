"""Local controlled Office index migration. No default database or app startup."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument(
        "--action", choices=["plan", "apply", "status", "rollback"], default="plan"
    )
    parser.add_argument(
        "--document", action="append", default=[], metavar="ID:SHA256:PROFILE:COUNT"
    )
    parser.add_argument(
        "--ids",
        help="Exact comma-separated document scope for a reviewed plan/manifest",
    )
    parser.add_argument("--output")
    parser.add_argument("--plan")
    parser.add_argument("--manifest")
    args = parser.parse_args(argv)
    from app.services import knowledge_office_index_migration as service

    try:
        if args.action == "plan":
            if args.ids or args.plan or args.manifest:
                parser.error(
                    "plan requires --document expectations, not --ids/--plan/--manifest"
                )
            expectations = []
            for value in args.document:
                ident, sha, profile, count = value.split(":")
                expectations.append(
                    {
                        "document_id": int(ident),
                        "sha256": sha,
                        "extractor_version": profile,
                        "chunk_count": int(count),
                    }
                )
            result = service.build_plan(args.database, expectations)
            if args.output:
                service.write_plan(result, args.output)
        else:
            if (
                not args.ids
                or not args.manifest
                or args.document
                or args.output
                or (args.action == "apply") != bool(args.plan)
            ):
                parser.error(
                    "apply needs --ids/--plan/--manifest; status/rollback need --ids/--manifest"
                )
            ids = [int(value) for value in args.ids.split(",")]
            if args.action == "apply":
                result = asyncio.run(
                    service.apply_plan(
                        args.database, args.plan, args.manifest, document_ids=ids
                    )
                )
            elif args.action == "status":
                result = service.inspect_manifest(
                    args.database, args.manifest, document_ids=ids
                )
            else:
                result = asyncio.run(
                    service.rollback_manifest(
                        args.database, args.manifest, document_ids=ids
                    )
                )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2 if result.get("state") == "unknown" else 0
    except (service.OfficeIndexMigrationError, ValueError, OSError):
        # Never print bound SQL parameters, private paths or source excerpts.
        print(
            "Office index operation refused or incomplete. Inspect the private plan/manifest and database preconditions before retrying.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

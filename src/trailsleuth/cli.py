"""An explicitly offline, rule-based demo."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from trailsleuth.detection import detect
from trailsleuth.normalization import EventValidationError, normalize_events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rule-based CloudTrail detection (no AWS calls)")
    commands = parser.add_subparsers(dest="command", required=True)
    detection = commands.add_parser(
        "detect", help="Print JSON findings; semantic search is planned"
    )
    detection.add_argument("path", type=Path, help="CloudTrail JSON fixture with a Records list")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.path.read_text(encoding="utf-8"))
        events = normalize_events(payload, source_reference=str(args.path))
    except (OSError, UnicodeError, json.JSONDecodeError, EventValidationError) as exc:
        print(f"trailsleuth: {args.path}: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "mode": "rule-based",
                "processed_events": len(events),
                "findings": [asdict(finding) for finding in detect(events)],
            },
            indent=2,
        )
    )
    return 0

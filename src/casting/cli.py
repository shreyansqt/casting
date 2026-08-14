"""Versioned JSON command-line contract for Casting."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .core import DOMAINS, RISKS, CastingError, route
from .policy import PolicyError

PROTOCOL_VERSION = 1


def _load_json(path: str) -> dict[str, Any]:
    try:
        if path == "-":
            value = json.load(sys.stdin)
        else:
            value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise CastingError(f"could not read JSON from {path}: {error}") from error
    if not isinstance(value, dict):
        raise CastingError(f"expected a JSON object from {path}")
    return value


def _emit(value: dict[str, Any]) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _route_command(args: argparse.Namespace) -> dict[str, Any]:
    if args.request == "-":
        request = _load_json("-")
        profile = request.get("profile")
        policy = request.get("policy")
        if not isinstance(profile, dict) or not isinstance(policy, dict):
            raise CastingError("route request needs object fields 'profile' and 'policy'")
    else:
        if not args.policy:
            raise CastingError("route requires --policy PATH or --request -")
        policy = _load_json(args.policy)
        profile = {
            "stable_key": args.stable_key,
            "domain": args.domain,
            "reasoning": args.reasoning,
            "verifiability": args.verifiability,
            "risk": args.risk,
            "context_need": args.context_need,
        }
    decision = route(profile, policy)
    if not args.explain:
        decision.pop("candidates", None)
        decision.pop("rejected", None)
    return {"schema_version": PROTOCOL_VERSION, **decision}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="casting")
    parser.add_argument(
        "--protocol-version",
        type=int,
        default=PROTOCOL_VERSION,
        help="required CLI protocol version; current version is 1",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    route_parser = subcommands.add_parser("route", help="choose a harness and model")
    route_parser.add_argument("--key", dest="stable_key", help="opaque stable work key")
    route_parser.add_argument("--domain", choices=DOMAINS)
    route_parser.add_argument("--reasoning", type=int)
    route_parser.add_argument("--verifiability", type=int, default=3)
    route_parser.add_argument("--risk", choices=RISKS, default="none")
    route_parser.add_argument("--context-need", type=int, default=0)
    route_parser.add_argument("--policy", help="policy JSON path")
    route_parser.add_argument("--request", choices=("-",), help="read profile and policy from stdin")
    route_parser.add_argument("--explain", action="store_true")
    route_parser.set_defaults(run=_route_command)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.protocol_version != PROTOCOL_VERSION:
        print(
            "casting: unsupported protocol version "
            f"{args.protocol_version}; supported: {PROTOCOL_VERSION}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        if args.command == "route" and args.request != "-":
            missing = [
                flag
                for flag, value in (
                    ("--key", args.stable_key),
                    ("--domain", args.domain),
                    ("--reasoning", args.reasoning),
                )
                if value is None
            ]
            if missing:
                raise CastingError(f"route requires {', '.join(missing)}")
        _emit(args.run(args))
    except (CastingError, PolicyError, KeyError, TypeError, ValueError) as error:
        print(f"casting: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

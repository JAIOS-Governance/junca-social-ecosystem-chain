#!/usr/bin/env python3
"""Safely verify, deploy, test, publish and restore the shared Docs/JAIOS CloudFront Function."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import boto3

FUNCTION_NAME = "junca-chain-docs-routes-595710543956"
FUNCTION_ARN = "arn:aws:cloudfront::595710543956:function/junca-chain-docs-routes-595710543956"
RUNTIME = "cloudfront-js-2.0"


def client():
    return boto3.client("cloudfront", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def read_code(cf, stage: str) -> tuple[bytes, dict[str, Any], str]:
    description = cf.describe_function(Name=FUNCTION_NAME, Stage=stage)
    summary = description["FunctionSummary"]
    actual_arn = summary["FunctionMetadata"]["FunctionARN"]
    if actual_arn != FUNCTION_ARN:
        raise RuntimeError(f"Unexpected function ARN: {actual_arn}")
    response = cf.get_function(Name=FUNCTION_NAME, Stage=stage)
    body = response["FunctionCode"]
    code = body.read() if hasattr(body, "read") else bytes(body)
    if not code:
        raise RuntimeError(f"{stage} FunctionCode is empty")
    return code, summary["FunctionConfig"], description["ETag"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def event(host: str, uri: str, method: str = "GET") -> bytes:
    return json.dumps(
        {
            "version": "1.0",
            "context": {"eventType": "viewer-request"},
            "viewer": {"ip": "198.51.100.10"},
            "request": {
                "method": method,
                "uri": uri,
                "querystring": {},
                "headers": {"host": {"value": host}},
                "cookies": {},
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")


def test_case(cf, etag: str, host: str, uri: str, expected_uri: str) -> dict[str, Any]:
    response = cf.test_function(
        Name=FUNCTION_NAME,
        IfMatch=etag,
        Stage="DEVELOPMENT",
        EventObject=event(host, uri),
    )
    result = response["TestResult"]
    error = result.get("FunctionErrorMessage")
    if error not in (None, "", "null"):
        raise RuntimeError(f"Function test failed for {host}{uri}: {error}")
    output = result.get("FunctionOutput", "")
    if isinstance(output, bytes):
        output = output.decode("utf-8")
    parsed = json.loads(output)
    request = parsed.get("request", parsed)
    actual_uri = request.get("uri")
    if actual_uri != expected_uri:
        raise RuntimeError(
            f"Unexpected URI for {host}{uri}: expected {expected_uri}, got {actual_uri}; output={parsed}"
        )
    return parsed


def run_tests(cf, etag: str) -> list[dict[str, Any]]:
    return [
        test_case(cf, etag, "docs.jaios-governance.org", "/protocol", "/protocol/index.html"),
        test_case(cf, etag, "docs.jaios-governance.org", "/explorer.json", "/explorer.json"),
        test_case(cf, etag, "jaios-governance.org", "/", "/jaios-root-news/index.html"),
        test_case(cf, etag, "jaios-governance.org", "/browser", "/browser"),
    ]


def cmd_preflight(args: argparse.Namespace) -> None:
    cf = client()
    live, _, _ = read_code(cf, "LIVE")
    baseline = Path(args.baseline).read_bytes()
    composite = Path(args.composite).read_bytes()
    allowed = {sha256(baseline), sha256(composite)}
    actual = sha256(live)
    if actual not in allowed:
        raise RuntimeError(f"Live function digest {actual} is outside the accepted baseline/composite set")
    print(json.dumps({"live_sha256": actual, "accepted": sorted(allowed), "result": "PASS"}, indent=2))


def cmd_deploy(args: argparse.Namespace) -> None:
    cf = client()
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    composite = Path(args.composite).read_bytes()

    old_live, old_config, _ = read_code(cf, "LIVE")
    Path(state_dir / "old-live.js").write_bytes(old_live)
    Path(state_dir / "old-config.json").write_text(json.dumps(old_config, indent=2) + "\n", encoding="utf-8")
    Path(state_dir / "old-live-sha256.txt").write_text(sha256(old_live) + "\n", encoding="utf-8")

    development, _, development_etag = read_code(cf, "DEVELOPMENT")
    if development != composite:
        cf.update_function(
            Name=FUNCTION_NAME,
            IfMatch=development_etag,
            FunctionConfig={
                "Comment": "Preserve Docs extensionless routes and route only the JAIOS root to the governed News artifact.",
                "Runtime": RUNTIME,
            },
            FunctionCode=composite,
        )

    _, _, test_etag = read_code(cf, "DEVELOPMENT")
    tests = run_tests(cf, test_etag)
    Path(state_dir / "function-tests.json").write_text(json.dumps(tests, indent=2) + "\n", encoding="utf-8")

    live_now, _, _ = read_code(cf, "LIVE")
    if live_now != composite:
        publish = cf.publish_function(Name=FUNCTION_NAME, IfMatch=test_etag)
        Path(state_dir / "function-publish.json").write_text(
            json.dumps(publish, default=str, indent=2) + "\n", encoding="utf-8"
        )

    live_after, _, _ = read_code(cf, "LIVE")
    if live_after != composite:
        raise RuntimeError("Published LIVE FunctionCode does not match the composite source")
    Path(state_dir / "composite-sha256.txt").write_text(sha256(composite) + "\n", encoding="utf-8")
    print(json.dumps({"function_arn": FUNCTION_ARN, "live_sha256": sha256(live_after), "result": "PUBLISHED"}))


def cmd_rollback(args: argparse.Namespace) -> None:
    cf = client()
    state_dir = Path(args.state_dir)
    old_code = Path(state_dir / "old-live.js").read_bytes()
    old_config = json.loads(Path(state_dir / "old-config.json").read_text(encoding="utf-8"))
    development, _, development_etag = read_code(cf, "DEVELOPMENT")
    if development != old_code:
        cf.update_function(
            Name=FUNCTION_NAME,
            IfMatch=development_etag,
            FunctionConfig={"Comment": old_config.get("Comment", ""), "Runtime": old_config.get("Runtime", RUNTIME)},
            FunctionCode=old_code,
        )
    _, _, test_etag = read_code(cf, "DEVELOPMENT")
    test_case(cf, test_etag, "docs.jaios-governance.org", "/protocol", "/protocol/index.html")
    live, _, _ = read_code(cf, "LIVE")
    if live != old_code:
        cf.publish_function(Name=FUNCTION_NAME, IfMatch=test_etag)
    live_after, _, _ = read_code(cf, "LIVE")
    if live_after != old_code:
        raise RuntimeError("Function rollback did not restore the prior LIVE code")
    print(json.dumps({"live_sha256": sha256(live_after), "result": "ROLLBACK_ACCEPTED"}))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--baseline", required=True)
    preflight.add_argument("--composite", required=True)
    preflight.set_defaults(func=cmd_preflight)

    deploy = subparsers.add_parser("deploy")
    deploy.add_argument("--composite", required=True)
    deploy.add_argument("--state-dir", required=True)
    deploy.set_defaults(func=cmd_deploy)

    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--state-dir", required=True)
    rollback.set_defaults(func=cmd_rollback)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Deploy and rollback the shared Docs/JAIOS CloudFront Function for Browser publication."""

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
ROOT_DOMAIN = "jaios-governance.org"
EXPECTED_ORIGIN = "jaios-institutional-governance.juncajapan-inc.chatgpt.site"


def client():
    return boto3.client("cloudfront", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_code(cf, stage: str) -> tuple[bytes, dict[str, Any], str]:
    description = cf.describe_function(Name=FUNCTION_NAME, Stage=stage)
    summary = description["FunctionSummary"]
    actual_arn = summary["FunctionMetadata"]["FunctionARN"]
    if actual_arn != FUNCTION_ARN:
        raise RuntimeError(f"Unexpected Function ARN: {actual_arn}")
    response = cf.get_function(Name=FUNCTION_NAME, Stage=stage)
    body = response["FunctionCode"]
    code = body.read() if hasattr(body, "read") else bytes(body)
    if not code:
        raise RuntimeError(f"{stage} FunctionCode is empty")
    return code, summary["FunctionConfig"], description["ETag"]


def event(host: str, uri: str) -> bytes:
    return json.dumps(
        {
            "version": "1.0",
            "context": {"eventType": "viewer-request"},
            "viewer": {"ip": "198.51.100.10"},
            "request": {
                "method": "GET",
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
            f"Unexpected URI for {host}{uri}: expected {expected_uri}, got {actual_uri}"
        )
    return {"host": host, "uri": uri, "actual_uri": actual_uri, "result": "PASS"}


def run_tests(cf, etag: str) -> list[dict[str, Any]]:
    return [
        test_case(cf, etag, "docs.jaios-governance.org", "/protocol", "/protocol/index.html"),
        test_case(cf, etag, "docs.jaios-governance.org", "/explorer.json", "/explorer.json"),
        test_case(cf, etag, ROOT_DOMAIN, "/", "/jaios-root-news/index.html"),
        test_case(cf, etag, ROOT_DOMAIN, "/browser", "/browser"),
        test_case(cf, etag, ROOT_DOMAIN, "/browser/app", "/jaios-browser-app/index.html"),
    ]


def validate_distribution(config: dict[str, Any]) -> None:
    aliases = config.get("Aliases", {}).get("Items", []) or []
    if ROOT_DOMAIN not in aliases:
        raise RuntimeError(f"Root alias absent: {aliases}")
    origins = [item.get("DomainName") for item in config.get("Origins", {}).get("Items", []) or []]
    if EXPECTED_ORIGIN not in origins:
        raise RuntimeError(f"Expected origin absent: {origins}")
    associations = config.get("DefaultCacheBehavior", {}).get("FunctionAssociations", {}).get("Items", []) or []
    other_viewer = [
        item
        for item in associations
        if item.get("EventType") == "viewer-request" and item.get("FunctionARN") != FUNCTION_ARN
    ]
    if other_viewer:
        raise RuntimeError(f"Unexpected viewer-request Function associations: {other_viewer}")


def with_shared_association(config: dict[str, Any]) -> dict[str, Any]:
    updated = json.loads(json.dumps(config))
    associations = updated["DefaultCacheBehavior"].setdefault(
        "FunctionAssociations", {"Quantity": 0, "Items": []}
    )
    items = associations.get("Items", []) or []
    items = [item for item in items if item.get("EventType") != "viewer-request"]
    items.append({"FunctionARN": FUNCTION_ARN, "EventType": "viewer-request"})
    associations["Items"] = items
    associations["Quantity"] = len(items)
    return updated


def cmd_preflight(args: argparse.Namespace) -> None:
    cf = client()
    live, _, _ = read_code(cf, "LIVE")
    baseline = Path(args.baseline).read_bytes()
    composite = Path(args.composite).read_bytes()
    allowed = {sha256(baseline), sha256(composite)}
    actual = sha256(live)
    if actual not in allowed:
        raise RuntimeError(f"LIVE Function digest {actual} outside accepted set {sorted(allowed)}")
    distribution = cf.get_distribution_config(Id=args.distribution_id)
    validate_distribution(distribution["DistributionConfig"])
    print(
        json.dumps(
            {
                "function_arn": FUNCTION_ARN,
                "live_sha256": actual,
                "accepted_sha256": sorted(allowed),
                "distribution_id": args.distribution_id,
                "result": "PASS",
            },
            indent=2,
        )
    )


def cmd_deploy(args: argparse.Namespace) -> None:
    cf = client()
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    composite = Path(args.composite).read_bytes()

    old_live, old_config, _ = read_code(cf, "LIVE")
    Path(state_dir / "old-live.js").write_bytes(old_live)
    Path(state_dir / "old-config.json").write_text(json.dumps(old_config, indent=2) + "\n")
    Path(state_dir / "old-live-sha256.txt").write_text(sha256(old_live) + "\n")

    distribution = cf.get_distribution_config(Id=args.distribution_id)
    distribution_config = distribution["DistributionConfig"]
    validate_distribution(distribution_config)
    Path(state_dir / "distribution-before.json").write_text(
        json.dumps(distribution_config, indent=2, default=str) + "\n"
    )

    development, _, development_etag = read_code(cf, "DEVELOPMENT")
    if development != composite:
        cf.update_function(
            Name=FUNCTION_NAME,
            IfMatch=development_etag,
            FunctionConfig={
                "Comment": "Preserve Docs routes and route JAIOS root and Browser app to governed artifacts.",
                "Runtime": RUNTIME,
            },
            FunctionCode=composite,
        )

    _, _, test_etag = read_code(cf, "DEVELOPMENT")
    tests = run_tests(cf, test_etag)
    Path(state_dir / "function-tests.json").write_text(json.dumps(tests, indent=2) + "\n")

    live_now, _, _ = read_code(cf, "LIVE")
    if live_now != composite:
        publish = cf.publish_function(Name=FUNCTION_NAME, IfMatch=test_etag)
        Path(state_dir / "function-publish.json").write_text(
            json.dumps(publish, default=str, indent=2) + "\n"
        )
    live_after, _, _ = read_code(cf, "LIVE")
    if live_after != composite:
        raise RuntimeError("LIVE FunctionCode does not match Browser composite")

    after_config = with_shared_association(distribution_config)
    if after_config != distribution_config:
        update = cf.update_distribution(
            Id=args.distribution_id,
            IfMatch=distribution["ETag"],
            DistributionConfig=after_config,
        )
        Path(state_dir / "distribution-update.json").write_text(
            json.dumps(update, default=str, indent=2) + "\n"
        )
        cf.get_waiter("distribution_deployed").wait(Id=args.distribution_id)
        Path(state_dir / "distribution-changed.txt").write_text("true\n")
    else:
        Path(state_dir / "distribution-changed.txt").write_text("false\n")

    invalidation = cf.create_invalidation(
        DistributionId=args.distribution_id,
        InvalidationBatch={
            "Paths": {"Quantity": 2, "Items": ["/browser/app", "/browser/app/"]},
            "CallerReference": f"jaios-browser-{os.environ.get('GITHUB_RUN_ID', 'manual')}",
        },
    )
    invalidation_id = invalidation["Invalidation"]["Id"]
    cf.get_waiter("invalidation_completed").wait(
        DistributionId=args.distribution_id, Id=invalidation_id
    )
    Path(state_dir / "invalidation-id.txt").write_text(invalidation_id + "\n")
    Path(state_dir / "composite-sha256.txt").write_text(sha256(composite) + "\n")
    print(
        json.dumps(
            {
                "function_arn": FUNCTION_ARN,
                "live_sha256": sha256(live_after),
                "distribution_id": args.distribution_id,
                "invalidation_id": invalidation_id,
                "result": "PUBLISHED",
            }
        )
    )


def cmd_rollback(args: argparse.Namespace) -> None:
    cf = client()
    state_dir = Path(args.state_dir)

    before_config = json.loads((state_dir / "distribution-before.json").read_text())
    current = cf.get_distribution_config(Id=args.distribution_id)
    if current["DistributionConfig"] != before_config:
        cf.update_distribution(
            Id=args.distribution_id,
            IfMatch=current["ETag"],
            DistributionConfig=before_config,
        )
        cf.get_waiter("distribution_deployed").wait(Id=args.distribution_id)
        invalidation = cf.create_invalidation(
            DistributionId=args.distribution_id,
            InvalidationBatch={
                "Paths": {"Quantity": 2, "Items": ["/browser/app", "/browser/app/"]},
                "CallerReference": f"jaios-browser-rollback-{os.environ.get('GITHUB_RUN_ID', 'manual')}",
            },
        )
        cf.get_waiter("invalidation_completed").wait(
            DistributionId=args.distribution_id,
            Id=invalidation["Invalidation"]["Id"],
        )

    old_code = (state_dir / "old-live.js").read_bytes()
    old_config = json.loads((state_dir / "old-config.json").read_text())
    development, _, development_etag = read_code(cf, "DEVELOPMENT")
    if development != old_code:
        cf.update_function(
            Name=FUNCTION_NAME,
            IfMatch=development_etag,
            FunctionConfig={
                "Comment": old_config.get("Comment", ""),
                "Runtime": old_config.get("Runtime", RUNTIME),
            },
            FunctionCode=old_code,
        )
    _, _, test_etag = read_code(cf, "DEVELOPMENT")
    test_case(cf, test_etag, "docs.jaios-governance.org", "/protocol", "/protocol/index.html")
    live, _, _ = read_code(cf, "LIVE")
    if live != old_code:
        cf.publish_function(Name=FUNCTION_NAME, IfMatch=test_etag)
    live_after, _, _ = read_code(cf, "LIVE")
    if live_after != old_code:
        raise RuntimeError("Function rollback did not restore previous LIVE code")
    print(json.dumps({"live_sha256": sha256(live_after), "result": "ROLLBACK_ACCEPTED"}))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    preflight = sub.add_parser("preflight")
    preflight.add_argument("--baseline", required=True)
    preflight.add_argument("--composite", required=True)
    preflight.add_argument("--distribution-id", required=True)
    preflight.set_defaults(func=cmd_preflight)

    deploy = sub.add_parser("deploy")
    deploy.add_argument("--composite", required=True)
    deploy.add_argument("--distribution-id", required=True)
    deploy.add_argument("--state-dir", required=True)
    deploy.set_defaults(func=cmd_deploy)

    rollback = sub.add_parser("rollback")
    rollback.add_argument("--distribution-id", required=True)
    rollback.add_argument("--state-dir", required=True)
    rollback.set_defaults(func=cmd_rollback)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

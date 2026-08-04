#!/usr/bin/env python3
"""Create or reconcile the dedicated JSEC brand CloudFront edge with rollback-safe DNS cutover."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION", "us-east-1")
ACCOUNT_ID = os.environ.get("AWS_ACCOUNT_ID", "595710543956")
ZONE_ID = os.environ.get("ROUTE53_ZONE_ID", "Z0336017285464TX0NT1G")
PUBLIC_HOST = os.environ.get("CHAIN_PUBLIC_HOST", "chain.jaios-governance.org")
NATIVE_HOST = os.environ.get(
    "CHAIN_NATIVE_HOST", "junca-social-ecosystem-chain.juncajapan-inc.chatgpt.site"
)
FUNCTION_NAME = os.environ.get("CHAIN_FUNCTION_NAME", "junca-chain-brand-root-router")
FUNCTION_ARN = f"arn:aws:cloudfront::{ACCOUNT_ID}:function/{FUNCTION_NAME}"
TEMPLATE_DISTRIBUTION_ID = os.environ.get("TEMPLATE_DISTRIBUTION_ID", "E2WIXG3DWW8OX1")
COMMENT = "JUNCA Social Ecosystem Chain institutional trust edge"
CALLER_REFERENCE = "junca-chain-institutional-trust-20260805"
CURRENT_PROVIDER_TARGET = "custom-domains.chatgpt.site"
RUNTIME = "cloudfront-js-2.0"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clients():
    return (
        boto3.client("cloudfront", region_name=REGION),
        boto3.client("acm", region_name="us-east-1"),
        boto3.client("route53", region_name=REGION),
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, default=str, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def find_record(route53, name: str) -> dict[str, Any] | None:
    response = route53.list_resource_record_sets(
        HostedZoneId=ZONE_ID,
        StartRecordName=name,
        MaxItems="10",
    )
    target = name.rstrip(".") + "."
    for item in response.get("ResourceRecordSets", []):
        if item.get("Name") == target and item.get("Type") in {"CNAME", "A", "AAAA"}:
            return item
    return None


def change_record(route53, record: dict[str, Any], action: str = "UPSERT") -> str:
    response = route53.change_resource_record_sets(
        HostedZoneId=ZONE_ID,
        ChangeBatch={
            "Comment": "JSEC brand institutional trust controlled publication",
            "Changes": [{"Action": action, "ResourceRecordSet": record}],
        },
    )
    change_id = response["ChangeInfo"]["Id"]
    route53.get_waiter("resource_record_sets_changed").wait(Id=change_id)
    return change_id


def certificate_for(acm, route53, state_dir: Path) -> str:
    candidates: list[str] = []
    paginator = acm.get_paginator("list_certificates")
    for page in paginator.paginate(CertificateStatuses=["ISSUED", "PENDING_VALIDATION"]):
        for summary in page.get("CertificateSummaryList", []):
            if summary.get("DomainName") == PUBLIC_HOST:
                candidates.append(summary["CertificateArn"])
    if candidates:
        arn = candidates[0]
    else:
        response = acm.request_certificate(
            DomainName=PUBLIC_HOST,
            ValidationMethod="DNS",
            Options={"CertificateTransparencyLoggingPreference": "ENABLED"},
            Tags=[
                {"Key": "JUNCA", "Value": "JSEC"},
                {"Key": "Purpose", "Value": "institutional-trust-edge"},
            ],
            IdempotencyToken="jsec20260805",
        )
        arn = response["CertificateArn"]

    deadline = time.time() + 300
    validation_record = None
    while time.time() < deadline:
        cert = acm.describe_certificate(CertificateArn=arn)["Certificate"]
        if cert.get("Status") == "ISSUED":
            write_json(state_dir / "certificate.json", cert)
            return arn
        for option in cert.get("DomainValidationOptions", []):
            rr = option.get("ResourceRecord")
            if option.get("DomainName") == PUBLIC_HOST and rr:
                validation_record = rr
                break
        if validation_record:
            break
        time.sleep(5)
    if not validation_record:
        raise RuntimeError("ACM validation record was not produced")

    validation_set = {
        "Name": validation_record["Name"],
        "Type": validation_record["Type"],
        "TTL": 300,
        "ResourceRecords": [{"Value": validation_record["Value"]}],
    }
    change_record(route53, validation_set)
    acm.get_waiter("certificate_validated").wait(
        CertificateArn=arn,
        WaiterConfig={"Delay": 15, "MaxAttempts": 40},
    )
    cert = acm.describe_certificate(CertificateArn=arn)["Certificate"]
    if cert.get("Status") != "ISSUED":
        raise RuntimeError(f"ACM certificate is not issued: {cert.get('Status')}")
    write_json(state_dir / "certificate.json", cert)
    return arn


def read_function(cf, stage: str) -> tuple[bytes, dict[str, Any], str] | None:
    try:
        description = cf.describe_function(Name=FUNCTION_NAME, Stage=stage)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NoSuchFunctionExists":
            return None
        raise
    response = cf.get_function(Name=FUNCTION_NAME, Stage=stage)
    body = response["FunctionCode"]
    code = body.read() if hasattr(body, "read") else bytes(body)
    return code, description["FunctionSummary"]["FunctionConfig"], description["ETag"]


def reconcile_function(cf, code: bytes, state_dir: Path) -> str:
    development = read_function(cf, "DEVELOPMENT")
    if development is None:
        cf.create_function(
            Name=FUNCTION_NAME,
            FunctionConfig={"Comment": COMMENT, "Runtime": RUNTIME},
            FunctionCode=code,
        )
    else:
        old_code, old_config, old_etag = development
        write_json(state_dir / "function-development-before.json", old_config)
        (state_dir / "function-development-before.js").write_bytes(old_code)
        if old_code != code:
            cf.update_function(
                Name=FUNCTION_NAME,
                IfMatch=old_etag,
                FunctionConfig={"Comment": COMMENT, "Runtime": RUNTIME},
                FunctionCode=code,
            )

    current = read_function(cf, "DEVELOPMENT")
    if current is None:
        raise RuntimeError("CloudFront Function development stage is unavailable")
    _, _, etag = current
    cases = [
        ("/", "/chain-brand-root/index.html"),
        ("/index.html", "/chain-brand-root/index.html"),
        ("/robots.txt", "/chain-brand-root/robots.txt"),
        ("/sitemap.xml", "/chain-brand-root/sitemap.xml"),
        ("/governance", "/governance"),
    ]
    results = []
    for uri, expected in cases:
        result = cf.test_function(
            Name=FUNCTION_NAME,
            IfMatch=etag,
            Stage="DEVELOPMENT",
            EventObject=event(PUBLIC_HOST, uri),
        )["TestResult"]
        error = result.get("FunctionErrorMessage")
        if error not in (None, "", "null"):
            raise RuntimeError(f"Function test failed {uri}: {error}")
        output = result.get("FunctionOutput", "")
        if isinstance(output, bytes):
            output = output.decode("utf-8")
        parsed = json.loads(output)
        request = parsed.get("request", parsed)
        if request.get("uri") != expected:
            raise RuntimeError(f"Function URI mismatch {uri}: {request.get('uri')} != {expected}")
        results.append(parsed)
    write_json(state_dir / "function-tests.json", results)

    live = read_function(cf, "LIVE")
    if live is None or live[0] != code:
        cf.publish_function(Name=FUNCTION_NAME, IfMatch=etag)
    live = read_function(cf, "LIVE")
    if live is None or live[0] != code:
        raise RuntimeError("LIVE CloudFront Function does not match source")
    arn = cf.describe_function(Name=FUNCTION_NAME, Stage="LIVE")["FunctionSummary"]["FunctionMetadata"]["FunctionARN"]
    if arn != FUNCTION_ARN:
        raise RuntimeError(f"Unexpected Function ARN: {arn}")
    (state_dir / "function-live-sha256.txt").write_text(sha256(live[0]) + "\n", encoding="utf-8")
    return arn


def find_distribution(cf) -> dict[str, Any] | None:
    paginator = cf.get_paginator("list_distributions")
    for page in paginator.paginate():
        distribution_list = page.get("DistributionList", {})
        for item in distribution_list.get("Items", []) or []:
            aliases = (item.get("Aliases") or {}).get("Items", []) or []
            if PUBLIC_HOST in aliases:
                return item
            if item.get("Comment") == COMMENT:
                return item
    return None


def build_distribution_config(cf, cert_arn: str, function_arn: str) -> dict[str, Any]:
    template = cf.get_distribution_config(Id=TEMPLATE_DISTRIBUTION_ID)["DistributionConfig"]
    config = copy.deepcopy(template)
    config["CallerReference"] = CALLER_REFERENCE
    config["Aliases"] = {"Quantity": 1, "Items": [PUBLIC_HOST]}
    config["DefaultRootObject"] = ""
    config["Origins"] = {
        "Quantity": 1,
        "Items": [
            {
                "Id": "chain-native-sites",
                "DomainName": NATIVE_HOST,
                "OriginPath": "",
                "CustomHeaders": {"Quantity": 0},
                "CustomOriginConfig": {
                    "HTTPPort": 80,
                    "HTTPSPort": 443,
                    "OriginProtocolPolicy": "https-only",
                    "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
                    "OriginReadTimeout": 30,
                    "OriginKeepaliveTimeout": 5,
                },
                "ConnectionAttempts": 3,
                "ConnectionTimeout": 10,
                "OriginShield": {"Enabled": False},
            }
        ],
    }
    config["OriginGroups"] = {"Quantity": 0}
    config["DefaultCacheBehavior"]["TargetOriginId"] = "chain-native-sites"
    config["DefaultCacheBehavior"]["FunctionAssociations"] = {
        "Quantity": 1,
        "Items": [{"FunctionARN": function_arn, "EventType": "viewer-request"}],
    }
    config["DefaultCacheBehavior"]["LambdaFunctionAssociations"] = {"Quantity": 0}
    config["DefaultCacheBehavior"]["ViewerProtocolPolicy"] = "redirect-to-https"
    config["DefaultCacheBehavior"]["Compress"] = True
    config["CacheBehaviors"] = {"Quantity": 0}
    config["CustomErrorResponses"] = {"Quantity": 0}
    config["Comment"] = COMMENT
    config["Logging"] = {"Enabled": False, "IncludeCookies": False, "Bucket": "", "Prefix": ""}
    config["PriceClass"] = "PriceClass_100"
    config["Enabled"] = True
    config["ViewerCertificate"] = {
        "ACMCertificateArn": cert_arn,
        "SSLSupportMethod": "sni-only",
        "MinimumProtocolVersion": "TLSv1.2_2021",
        "Certificate": cert_arn,
        "CertificateSource": "acm",
    }
    config["Restrictions"] = {"GeoRestriction": {"RestrictionType": "none", "Quantity": 0}}
    config["WebACLId"] = ""
    config["HttpVersion"] = "http2and3"
    config["IsIPV6Enabled"] = True
    config.pop("ContinuousDeploymentPolicyId", None)
    config.pop("Staging", None)
    return config


def reconcile_distribution(cf, cert_arn: str, function_arn: str, state_dir: Path) -> tuple[str, str]:
    current = find_distribution(cf)
    desired = build_distribution_config(cf, cert_arn, function_arn)
    if current is None:
        response = cf.create_distribution(DistributionConfig=desired)
        distribution = response["Distribution"]
    else:
        distribution_id = current["Id"]
        config_response = cf.get_distribution_config(Id=distribution_id)
        write_json(state_dir / "distribution-before.json", config_response)
        existing = config_response["DistributionConfig"]
        # Preserve the original caller reference when reconciling an existing distribution.
        desired["CallerReference"] = existing["CallerReference"]
        response = cf.update_distribution(
            Id=distribution_id,
            IfMatch=config_response["ETag"],
            DistributionConfig=desired,
        )
        distribution = response["Distribution"]
    distribution_id = distribution["Id"]
    cf.get_waiter("distribution_deployed").wait(
        Id=distribution_id,
        WaiterConfig={"Delay": 30, "MaxAttempts": 40},
    )
    distribution = cf.get_distribution(Id=distribution_id)["Distribution"]
    aliases = distribution["DistributionConfig"]["Aliases"].get("Items", [])
    if PUBLIC_HOST not in aliases:
        raise RuntimeError("CloudFront alias was not applied")
    write_json(state_dir / "distribution-after.json", distribution)
    return distribution_id, distribution["DomainName"]


def deploy(args: argparse.Namespace) -> None:
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    cf, acm, route53 = clients()
    caller = boto3.client("sts").get_caller_identity()
    if caller.get("Account") != ACCOUNT_ID:
        raise RuntimeError(f"Unexpected AWS account: {caller.get('Account')}")
    write_json(state_dir / "caller.json", caller)

    baseline = find_record(route53, PUBLIC_HOST)
    if baseline is None:
        raise RuntimeError("Current Chain DNS record is missing")
    if baseline.get("Type") != "CNAME":
        raise RuntimeError(f"Current Chain DNS must be CNAME, got {baseline.get('Type')}")
    values = [item.get("Value", "").rstrip(".") for item in baseline.get("ResourceRecords", [])]
    accepted = {CURRENT_PROVIDER_TARGET, NATIVE_HOST}
    if not values or not all(value in accepted or value.endswith(".cloudfront.net") for value in values):
        raise RuntimeError(f"Unexpected current Chain DNS values: {values}")
    write_json(state_dir / "dns-before.json", baseline)

    dns_changed = False
    try:
        cert_arn = certificate_for(acm, route53, state_dir)
        function_code = Path(args.function_code).read_bytes()
        function_arn = reconcile_function(cf, function_code, state_dir)
        distribution_id, distribution_domain = reconcile_distribution(
            cf, cert_arn, function_arn, state_dir
        )
        desired_record = {
            "Name": PUBLIC_HOST + ".",
            "Type": "CNAME",
            "TTL": int(baseline.get("TTL", 300)),
            "ResourceRecords": [{"Value": distribution_domain}],
        }
        change_id = change_record(route53, desired_record)
        dns_changed = True
        final_record = find_record(route53, PUBLIC_HOST)
        write_json(state_dir / "dns-after.json", final_record)
        if final_record is None or final_record.get("ResourceRecords", [{}])[0].get("Value", "").rstrip(".") != distribution_domain:
            raise RuntimeError("Route 53 Chain cutover readback failed")
        result = {
            "schema": "jsec-chain-brand-edge-deployment/v1",
            "result": "EDGE_ACTIVATED",
            "aws_account_id": ACCOUNT_ID,
            "caller_arn": caller.get("Arn"),
            "public_host": PUBLIC_HOST,
            "native_origin": NATIVE_HOST,
            "certificate_arn": cert_arn,
            "function_arn": function_arn,
            "function_sha256": sha256(function_code),
            "distribution_id": distribution_id,
            "distribution_domain": distribution_domain,
            "route53_change_id": change_id,
            "dns_before": baseline,
            "dns_after": final_record,
        }
        write_json(state_dir / "edge-result.json", result)
        print(json.dumps(result, default=str))
    except Exception:
        if dns_changed:
            try:
                rollback_change = change_record(route53, baseline)
                write_json(
                    state_dir / "dns-rollback.json",
                    {"change_id": rollback_change, "record": find_record(route53, PUBLIC_HOST)},
                )
            except Exception as rollback_error:  # noqa: BLE001
                write_json(state_dir / "dns-rollback-error.json", {"error": repr(rollback_error)})
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--function-code", required=True)
    parser.add_argument("--state-dir", required=True)
    args = parser.parse_args()
    deploy(args)


if __name__ == "__main__":
    main()

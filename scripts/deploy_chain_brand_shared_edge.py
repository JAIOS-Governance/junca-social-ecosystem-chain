#!/usr/bin/env python3
"""Deploy the JSEC brand edge using the accepted shared CloudFront Function."""

from __future__ import annotations

import argparse
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
SHARED_FUNCTION_ARN = (
    f"arn:aws:cloudfront::{ACCOUNT_ID}:function/junca-chain-docs-routes-595710543956"
)
COMMENT = "JUNCA Social Ecosystem Chain institutional trust edge"
CALLER_REFERENCE = "junca-chain-institutional-trust-shared-edge-20260805"
CURRENT_PROVIDER_TARGET = "custom-domains.chatgpt.site"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, default=str, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def clients():
    return (
        boto3.client("cloudfront", region_name=REGION),
        boto3.client("acm", region_name="us-east-1"),
        boto3.client("route53", region_name=REGION),
    )


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


def change_record(route53, record: dict[str, Any]) -> str:
    response = route53.change_resource_record_sets(
        HostedZoneId=ZONE_ID,
        ChangeBatch={
            "Comment": "JSEC brand institutional trust controlled publication",
            "Changes": [{"Action": "UPSERT", "ResourceRecordSet": record}],
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
            record = option.get("ResourceRecord")
            if option.get("DomainName") == PUBLIC_HOST and record:
                validation_record = record
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


def distribution_config(certificate_arn: str) -> dict[str, Any]:
    return {
        "CallerReference": CALLER_REFERENCE,
        "Aliases": {"Quantity": 1, "Items": [PUBLIC_HOST]},
        "DefaultRootObject": "",
        "Origins": {
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
        },
        "OriginGroups": {"Quantity": 0},
        "DefaultCacheBehavior": {
            "TargetOriginId": "chain-native-sites",
            "TrustedSigners": {"Enabled": False, "Quantity": 0},
            "TrustedKeyGroups": {"Enabled": False, "Quantity": 0},
            "ViewerProtocolPolicy": "redirect-to-https",
            "AllowedMethods": {
                "Quantity": 3,
                "Items": ["HEAD", "GET", "OPTIONS"],
                "CachedMethods": {
                    "Quantity": 3,
                    "Items": ["HEAD", "GET", "OPTIONS"],
                },
            },
            "SmoothStreaming": False,
            "Compress": True,
            "LambdaFunctionAssociations": {"Quantity": 0},
            "FunctionAssociations": {
                "Quantity": 1,
                "Items": [
                    {
                        "FunctionARN": SHARED_FUNCTION_ARN,
                        "EventType": "viewer-request",
                    }
                ],
            },
            "FieldLevelEncryptionId": "",
            "ForwardedValues": {
                "QueryString": True,
                "Cookies": {"Forward": "all"},
                "Headers": {"Quantity": 0},
                "QueryStringCacheKeys": {"Quantity": 0},
            },
            "MinTTL": 0,
            "DefaultTTL": 0,
            "MaxTTL": 0,
            "GrpcConfig": {"Enabled": False},
        },
        "CacheBehaviors": {"Quantity": 0},
        "CustomErrorResponses": {"Quantity": 0},
        "Comment": COMMENT,
        "Logging": {
            "Enabled": False,
            "IncludeCookies": False,
            "Bucket": "",
            "Prefix": "",
        },
        "PriceClass": "PriceClass_100",
        "Enabled": True,
        "ViewerCertificate": {
            "ACMCertificateArn": certificate_arn,
            "SSLSupportMethod": "sni-only",
            "MinimumProtocolVersion": "TLSv1.2_2021",
            "Certificate": certificate_arn,
            "CertificateSource": "acm",
        },
        "Restrictions": {
            "GeoRestriction": {"RestrictionType": "none", "Quantity": 0}
        },
        "WebACLId": "",
        "HttpVersion": "http2and3",
        "IsIPV6Enabled": True,
    }


def create_distribution(cf, certificate_arn: str, state_dir: Path) -> tuple[str, str]:
    config = distribution_config(certificate_arn)
    try:
        response = cf.create_distribution(DistributionConfig=config)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in {"DistributionAlreadyExists", "CNAMEAlreadyExists"}:
            raise RuntimeError(
                "A Chain edge already exists but cannot be safely identified without exact evidence"
            ) from exc
        raise
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
    association = (
        distribution["DistributionConfig"]["DefaultCacheBehavior"]
        .get("FunctionAssociations", {})
        .get("Items", [])
    )
    if not any(
        item.get("FunctionARN") == SHARED_FUNCTION_ARN
        and item.get("EventType") == "viewer-request"
        for item in association
    ):
        raise RuntimeError("Shared Function association was not applied")
    write_json(state_dir / "distribution.json", distribution)
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
    values = [
        item.get("Value", "").rstrip(".")
        for item in baseline.get("ResourceRecords", [])
    ]
    accepted = {CURRENT_PROVIDER_TARGET, NATIVE_HOST}
    if not values or not all(value in accepted for value in values):
        raise RuntimeError(f"Unexpected current Chain DNS values: {values}")
    write_json(state_dir / "dns-before.json", baseline)

    dns_changed = False
    try:
        certificate_arn = certificate_for(acm, route53, state_dir)
        distribution_id, distribution_domain = create_distribution(
            cf, certificate_arn, state_dir
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
        if (
            final_record is None
            or final_record.get("ResourceRecords", [{}])[0]
            .get("Value", "")
            .rstrip(".")
            != distribution_domain
        ):
            raise RuntimeError("Route 53 Chain cutover readback failed")
        result = {
            "schema": "jsec-chain-brand-shared-edge-deployment/v1",
            "result": "EDGE_ACTIVATED",
            "aws_account_id": ACCOUNT_ID,
            "caller_arn": caller.get("Arn"),
            "public_host": PUBLIC_HOST,
            "native_origin": NATIVE_HOST,
            "certificate_arn": certificate_arn,
            "shared_function_arn": SHARED_FUNCTION_ARN,
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
                rollback_id = change_record(route53, baseline)
                write_json(
                    state_dir / "dns-rollback.json",
                    {
                        "change_id": rollback_id,
                        "record": find_record(route53, PUBLIC_HOST),
                    },
                )
            except Exception as rollback_error:  # noqa: BLE001
                write_json(
                    state_dir / "dns-rollback-error.json",
                    {"error": repr(rollback_error)},
                )
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    deploy(parser.parse_args())


if __name__ == "__main__":
    main()

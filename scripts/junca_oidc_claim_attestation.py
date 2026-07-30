#!/usr/bin/env python3
"""Read and attest the exact GitHub OIDC token accepted by a JSEC AWS role.

The JWT itself is never written or printed. The exact token whose claims are
recorded is submitted once to AWS STS ``AssumeRoleWithWebIdentity``. STS
therefore verifies its signature, lifetime, audience, subject, and role trust
before this controller emits redacted evidence. Returned temporary credentials
are parsed only in memory and are never persisted or printed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable
from urllib import error
from urllib import parse, request
from xml.etree import ElementTree


ISSUER = "https://token.actions.githubusercontent.com"
AUDIENCE = "sts.amazonaws.com"
REPOSITORY = "JAIOS-Governance/junca-social-ecosystem-chain"
REPOSITORY_OWNER_ID = "308604370"
REPOSITORY_ID = "1310568313"
ENVIRONMENT = "public-testnet"
MAIN_REF = "refs/heads/main"
AWS_ACCOUNT_ID = "595710543956"
AWS_REGION = "us-east-1"
STS_ENDPOINT = f"https://sts.{AWS_REGION}.amazonaws.com/"
FOUNDATION_ROLE_ARN = (
    f"arn:aws:iam::{AWS_ACCOUNT_ID}:role/JuncaChainPublicTestnetDeployment"
)
AMI_BUILDER_ROLE_ARN = (
    f"arn:aws:iam::{AWS_ACCOUNT_ID}:role/JuncaChainPublicTestnetAmiBuilder"
)
OBSERVER_ROLE_ARN = (
    f"arn:aws:iam::{AWS_ACCOUNT_ID}:role/JuncaChainPublicTestnetObserver"
)
WORKFLOW_ROLE_ARNS = {
    ".github/workflows/junca-validator-foundation-release.yml":
        FOUNDATION_ROLE_ARN,
    ".github/workflows/junca-public-testnet-release.yml":
        FOUNDATION_ROLE_ARN,
    ".github/workflows/junca-validator-ami-build.yml":
        AMI_BUILDER_ROLE_ARN,
    ".github/workflows/junca-runtime-release-evidence-collector-v2.yml":
        OBSERVER_ROLE_ARN,
    ".github/workflows/junca-public-testnet-live-soak.yml":
        OBSERVER_ROLE_ARN,
    ".github/workflows/junca-social-ecosystem-chain-aws-binding-readback.yml":
        OBSERVER_ROLE_ARN,
    ".github/workflows/junca-social-ecosystem-chain-aws-readback.yml":
        OBSERVER_ROLE_ARN,
}
WORKFLOW_PATH_RE = re.compile(
    r"^\.github/workflows/[A-Za-z0-9._-]+\.ya?ml$"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RUN_ID_RE = re.compile(r"^[1-9][0-9]{0,19}$")


class OidcClaimError(RuntimeError):
    """Live OIDC claim readback did not match the exact JSEC contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise OidcClaimError(message)


def expected_workflow_ref(workflow_path: str) -> str:
    _require(
        WORKFLOW_PATH_RE.fullmatch(workflow_path) is not None,
        "workflow path is invalid",
    )
    return f"{REPOSITORY}/{workflow_path}@{MAIN_REF}"


def expected_subject(workflow_path: str) -> str:
    return (
        f"repo:JAIOS-Governance@{REPOSITORY_OWNER_ID}/"
        f"junca-social-ecosystem-chain@{REPOSITORY_ID}:"
        f"environment:{ENVIRONMENT}:"
        f"workflow_ref:{expected_workflow_ref(workflow_path)}:"
        "runner_environment:github-hosted"
    )


def decode_payload(token: str) -> dict[str, Any]:
    _require(
        isinstance(token, str) and token.count(".") == 2,
        "OIDC token shape is invalid",
    )
    encoded = token.split(".", 2)[1]
    encoded += "=" * ((4 - len(encoded) % 4) % 4)
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise OidcClaimError("OIDC token payload is invalid") from exc
    _require(isinstance(payload, dict), "OIDC token payload must be an object")
    return payload


def validate_claims(
    claims: dict[str, Any],
    *,
    workflow_path: str,
    expected_sha: str,
    expected_run_id: str,
    now: int | None = None,
) -> dict[str, Any]:
    _require(SHA_RE.fullmatch(expected_sha) is not None, "workflow SHA is invalid")
    _require(
        RUN_ID_RE.fullmatch(expected_run_id) is not None,
        "GitHub run ID is invalid",
    )
    expected_ref = expected_workflow_ref(workflow_path)
    expected_sub = expected_subject(workflow_path)
    expected = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": expected_sub,
        "repository": REPOSITORY,
        "repository_owner_id": REPOSITORY_OWNER_ID,
        "repository_id": REPOSITORY_ID,
        "environment": ENVIRONMENT,
        "ref": MAIN_REF,
        "ref_type": "branch",
        "repository_visibility": "public",
        "runner_environment": "github-hosted",
        "run_id": expected_run_id,
        "workflow_ref": expected_ref,
        "workflow_sha": expected_sha,
    }
    for key, value in expected.items():
        _require(claims.get(key) == value, f"OIDC claim mismatch: {key}")
    _require(
        "job_workflow_ref" not in claims,
        "direct workflow unexpectedly contains reusable job_workflow_ref",
    )
    event_name = claims.get("event_name")
    _require(
        event_name in {"workflow_dispatch", "workflow_run"},
        "OIDC event_name is not an approved release event",
    )
    current_time = int(time.time()) if now is None else now
    for key in ("iat", "nbf", "exp"):
        value = claims.get(key)
        _require(
            isinstance(value, int) and not isinstance(value, bool),
            f"OIDC temporal claim is invalid: {key}",
        )
    issued_at = claims["iat"]
    not_before = claims["nbf"]
    expires_at = claims["exp"]
    _require(issued_at <= current_time + 60, "OIDC token iat is in the future")
    _require(not_before <= current_time + 60, "OIDC token is not yet valid")
    _require(expires_at > current_time, "OIDC token is expired")
    _require(expires_at > issued_at, "OIDC token lifetime is invalid")
    return {
        **expected,
        "event_name": event_name,
        "iat": issued_at,
        "nbf": not_before,
        "exp": expires_at,
    }


def request_oidc_token() -> str:
    endpoint = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    bearer = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    _require(endpoint.startswith("https://"), "OIDC request URL is unavailable")
    _require(bool(bearer), "OIDC request bearer is unavailable")
    parsed = parse.urlsplit(endpoint)
    query = parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key != "audience"]
    query.append(("audience", AUDIENCE))
    target = parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, parse.urlencode(query), "")
    )
    oidc_request = request.Request(
        target,
        headers={
            "Authorization": f"bearer {bearer}",
            "Accept": "application/json",
        },
    )
    try:
        with request.urlopen(oidc_request, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OidcClaimError("GitHub OIDC request failed") from exc
    _require(isinstance(body, dict), "GitHub OIDC response is invalid")
    token = body.get("value")
    _require(isinstance(token, str) and token, "GitHub OIDC token is absent")
    return token


def expected_role_arn(workflow_path: str) -> str:
    _require(
        workflow_path in WORKFLOW_ROLE_ARNS,
        "workflow is not approved for a JSEC AWS role",
    )
    return WORKFLOW_ROLE_ARNS[workflow_path]


def assume_role_with_web_identity(
    token: str,
    *,
    role_arn: str,
    session_name: str,
    urlopen: Callable[..., Any] = request.urlopen,
) -> str:
    """Require STS to accept the exact token, discarding returned credentials."""

    _require(role_arn in set(WORKFLOW_ROLE_ARNS.values()), "AWS role is invalid")
    _require(
        re.fullmatch(r"jsec-oidc-attest-[1-9][0-9]{0,19}", session_name)
        is not None,
        "STS session name is invalid",
    )
    body = parse.urlencode(
        {
            "Action": "AssumeRoleWithWebIdentity",
            "Version": "2011-06-15",
            "RoleArn": role_arn,
            "RoleSessionName": session_name,
            "WebIdentityToken": token,
            "DurationSeconds": "900",
        }
    ).encode("utf-8")
    sts_request = request.Request(
        STS_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Accept": "application/xml",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urlopen(sts_request, timeout=15) as response:
            # This response also contains temporary credentials. Keep it in
            # memory only, extract the non-secret assumed-role ARN, and never
            # include the raw body in an exception or log.
            response_body = response.read()
    except (error.HTTPError, error.URLError, OSError) as exc:
        raise OidcClaimError("AWS STS rejected the exact GitHub OIDC token") from exc
    try:
        root = ElementTree.fromstring(response_body)
    except ElementTree.ParseError as exc:
        raise OidcClaimError("AWS STS response is invalid") from exc
    arn_node = root.find(".//{*}AssumedRoleUser/{*}Arn")
    _require(
        arn_node is not None and isinstance(arn_node.text, str),
        "AWS STS assumed-role identity is absent",
    )
    role_name = role_arn.rsplit("/", 1)[-1]
    expected_arn = (
        f"arn:aws:sts::{AWS_ACCOUNT_ID}:assumed-role/"
        f"{role_name}/{session_name}"
    )
    _require(
        arn_node.text == expected_arn,
        "AWS STS assumed-role identity mismatch",
    )
    return arn_node.text


def attest_token(
    token: str,
    *,
    workflow_path: str,
    expected_sha: str,
    role_arn: str,
    run_id: str,
    now: int | None = None,
    urlopen: Callable[..., Any] = request.urlopen,
) -> tuple[dict[str, Any], str]:
    _require(RUN_ID_RE.fullmatch(run_id) is not None, "GitHub run ID is invalid")
    _require(
        role_arn == expected_role_arn(workflow_path),
        "workflow-to-role binding mismatch",
    )
    claims = validate_claims(
        decode_payload(token),
        workflow_path=workflow_path,
        expected_sha=expected_sha,
        expected_run_id=run_id,
        now=now,
    )
    assumed_role_arn = assume_role_with_web_identity(
        token,
        role_arn=role_arn,
        session_name=f"jsec-oidc-attest-{run_id}",
        urlopen=urlopen,
    )
    return claims, assumed_role_arn


def write_attestation(
    path: Path,
    claims: dict[str, Any],
    assumed_role_arn: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    evidence = {
        "schema_version": "junca-github-oidc-claim-attestation/v2",
        "state": "EXACT_TOKEN_ACCEPTED_BY_AWS_STS",
        "subject_claim_keys": [
            "repo",
            "context",
            "workflow_ref",
            "runner_environment",
        ],
        "claims": claims,
        "sts_assumed_role_arn": assumed_role_arn,
        "sts_token_accepted": True,
        "token_persisted": False,
        "sts_credentials_persisted": False,
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
    }
    path.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(f"{path.name}.sha256").write_text(
        f"{digest}  {path.name}\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-path", required=True)
    parser.add_argument(
        "--role-arn",
        required=True,
        choices=sorted(set(WORKFLOW_ROLE_ARNS.values())),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        expected_sha = os.environ.get("GITHUB_SHA", "")
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        claims, assumed_role_arn = attest_token(
            request_oidc_token(),
            workflow_path=args.workflow_path,
            expected_sha=expected_sha,
            role_arn=args.role_arn,
            run_id=run_id,
        )
        write_attestation(args.output, claims, assumed_role_arn)
    except (OSError, OidcClaimError) as exc:
        print(f"OIDC claim attestation failed: {exc}", file=sys.stderr)
        return 1
    print("JSEC GitHub OIDC token accepted by exact AWS STS role: VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

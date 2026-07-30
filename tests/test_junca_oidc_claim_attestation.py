from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib import error
from urllib import parse

from scripts.junca_oidc_claim_attestation import (
    AUDIENCE,
    AMI_BUILDER_ROLE_ARN,
    ENVIRONMENT,
    ISSUER,
    MAIN_REF,
    OidcClaimError,
    REPOSITORY,
    REPOSITORY_ID,
    REPOSITORY_OWNER_ID,
    STS_ENDPOINT,
    attest_token,
    decode_payload,
    expected_role_arn,
    expected_subject,
    expected_workflow_ref,
    assume_role_with_web_identity,
    validate_claims,
    write_attestation,
)


SHA = "a" * 40
WORKFLOW = ".github/workflows/junca-validator-ami-build.yml"
NOW = 1_800_000_000
RUN_ID = "30299999999"
SESSION_NAME = f"jsec-oidc-attest-{RUN_ID}"
ASSUMED_ROLE_ARN = (
    "arn:aws:sts::595710543956:assumed-role/"
    f"JuncaChainPublicTestnetAmiBuilder/{SESSION_NAME}"
)


def encoded_token(payload: dict[str, object]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(
        json.dumps(payload).encode("utf-8")
    ).decode().rstrip("=")
    return f"{header}.{body}.signature"


def exact_claims() -> dict[str, object]:
    return {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": expected_subject(WORKFLOW),
        "repository": REPOSITORY,
        "repository_owner_id": REPOSITORY_OWNER_ID,
        "repository_id": REPOSITORY_ID,
        "environment": ENVIRONMENT,
        "ref": MAIN_REF,
        "ref_type": "branch",
        "repository_visibility": "public",
        "runner_environment": "github-hosted",
        "run_id": RUN_ID,
        "workflow_ref": expected_workflow_ref(WORKFLOW),
        "workflow_sha": SHA,
        "event_name": "workflow_dispatch",
        "iat": NOW - 30,
        "nbf": NOW - 30,
        "exp": NOW + 270,
    }


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def accepted_sts_response(arn: str = ASSUMED_ROLE_ARN) -> bytes:
    return f"""\
<AssumeRoleWithWebIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
  <AssumeRoleWithWebIdentityResult>
    <Credentials>
      <AccessKeyId>must-not-persist</AccessKeyId>
      <SecretAccessKey>must-not-persist</SecretAccessKey>
      <SessionToken>must-not-persist</SessionToken>
    </Credentials>
    <AssumedRoleUser>
      <Arn>{arn}</Arn>
      <AssumedRoleId>AROATEST:{SESSION_NAME}</AssumedRoleId>
    </AssumedRoleUser>
  </AssumeRoleWithWebIdentityResult>
</AssumeRoleWithWebIdentityResponse>
""".encode()


class OidcClaimAttestationTests(unittest.TestCase):
    def test_exact_direct_workflow_claims_pass(self) -> None:
        claims = exact_claims()
        token = encoded_token(claims)
        self.assertEqual(decode_payload(token), claims)
        self.assertEqual(
            validate_claims(
                decode_payload(token),
                workflow_path=WORKFLOW,
                expected_sha=SHA,
                expected_run_id=RUN_ID,
                now=NOW,
            ),
            claims,
        )
        self.assertIn(
            "repo:JAIOS-Governance@308604370/"
            "junca-social-ecosystem-chain@1310568313",
            expected_subject(WORKFLOW),
        )
        self.assertIn(":workflow_ref:", expected_subject(WORKFLOW))
        self.assertTrue(
            expected_subject(WORKFLOW).endswith(
                ":runner_environment:github-hosted"
            )
        )

    def test_identity_and_workflow_drift_fail_closed(self) -> None:
        for key, value in (
            ("repository_id", "9"),
            ("repository_owner_id", "8"),
            ("environment", "production"),
            ("ref", "refs/heads/feature"),
            ("ref_type", "tag"),
            ("repository_visibility", "private"),
            ("runner_environment", "self-hosted"),
            ("run_id", "1"),
            ("workflow_ref", "forged/workflow@refs/heads/main"),
            ("workflow_sha", "b" * 40),
            ("sub", "repo:forged"),
            ("aud", "forged"),
        ):
            with self.subTest(key=key):
                claims = exact_claims()
                claims[key] = value
                with self.assertRaisesRegex(OidcClaimError, key):
                    validate_claims(
                        claims,
                        workflow_path=WORKFLOW,
                        expected_sha=SHA,
                        expected_run_id=RUN_ID,
                        now=NOW,
                    )

    def test_reusable_workflow_claim_is_rejected(self) -> None:
        claims = exact_claims()
        claims["job_workflow_ref"] = expected_workflow_ref(WORKFLOW)
        with self.assertRaisesRegex(OidcClaimError, "reusable"):
            validate_claims(
                claims,
                workflow_path=WORKFLOW,
                expected_sha=SHA,
                expected_run_id=RUN_ID,
                now=NOW,
            )

    def test_temporal_claims_fail_closed(self) -> None:
        for key, value in (
            ("exp", NOW),
            ("iat", NOW + 61),
            ("nbf", NOW + 61),
        ):
            with self.subTest(key=key):
                claims = exact_claims()
                claims[key] = value
                with self.assertRaisesRegex(OidcClaimError, "OIDC token"):
                    validate_claims(
                        claims,
                        workflow_path=WORKFLOW,
                        expected_sha=SHA,
                        expected_run_id=RUN_ID,
                        now=NOW,
                    )

    def test_exact_token_is_submitted_to_sts_and_identity_is_bound(self) -> None:
        token = encoded_token(exact_claims())
        observed: dict[str, object] = {}

        def fake_urlopen(sts_request: object, timeout: int) -> FakeResponse:
            observed["url"] = sts_request.full_url
            observed["timeout"] = timeout
            observed["body"] = parse.parse_qs(
                sts_request.data.decode("utf-8")
            )
            return FakeResponse(accepted_sts_response())

        claims, assumed_role_arn = attest_token(
            token,
            workflow_path=WORKFLOW,
            expected_sha=SHA,
            role_arn=AMI_BUILDER_ROLE_ARN,
            run_id=RUN_ID,
            now=NOW,
            urlopen=fake_urlopen,
        )
        self.assertEqual(claims, exact_claims())
        self.assertEqual(assumed_role_arn, ASSUMED_ROLE_ARN)
        self.assertEqual(observed["url"], STS_ENDPOINT)
        self.assertEqual(observed["timeout"], 15)
        self.assertEqual(observed["body"]["WebIdentityToken"], [token])
        self.assertEqual(observed["body"]["RoleArn"], [AMI_BUILDER_ROLE_ARN])
        self.assertEqual(observed["body"]["DurationSeconds"], ["900"])

    def test_forged_signature_rejected_by_sts_emits_no_evidence(self) -> None:
        token = encoded_token(exact_claims())

        def reject_urlopen(*args: object, **kwargs: object) -> FakeResponse:
            raise error.HTTPError(
                STS_ENDPOINT,
                400,
                "InvalidIdentityToken",
                hdrs=None,
                fp=None,
            )

        with self.assertRaisesRegex(OidcClaimError, "STS rejected"):
            attest_token(
                token,
                workflow_path=WORKFLOW,
                expected_sha=SHA,
                role_arn=AMI_BUILDER_ROLE_ARN,
                run_id=RUN_ID,
                now=NOW,
                urlopen=reject_urlopen,
            )

    def test_workflow_cannot_self_select_another_role(self) -> None:
        self.assertEqual(expected_role_arn(WORKFLOW), AMI_BUILDER_ROLE_ARN)
        with self.assertRaisesRegex(OidcClaimError, "workflow-to-role"):
            attest_token(
                encoded_token(exact_claims()),
                workflow_path=WORKFLOW,
                expected_sha=SHA,
                role_arn=(
                    "arn:aws:iam::595710543956:"
                    "role/JuncaChainPublicTestnetObserver"
                ),
                run_id=RUN_ID,
                now=NOW,
                urlopen=lambda *args, **kwargs: FakeResponse(
                    accepted_sts_response()
                ),
            )

    def test_attestation_never_persists_token_or_sts_credentials(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory, "oidc.json")
            claims = validate_claims(
                exact_claims(),
                workflow_path=WORKFLOW,
                expected_sha=SHA,
                expected_run_id=RUN_ID,
                now=NOW,
            )
            write_attestation(output, claims, ASSUMED_ROLE_ARN)
            evidence = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(evidence["token_persisted"])
            self.assertFalse(evidence["sts_credentials_persisted"])
            self.assertTrue(evidence["sts_token_accepted"])
            self.assertEqual(
                evidence["state"],
                "EXACT_TOKEN_ACCEPTED_BY_AWS_STS",
            )
            self.assertEqual(
                evidence["sts_assumed_role_arn"],
                ASSUMED_ROLE_ARN,
            )
            self.assertEqual(evidence["claims"], claims)
            self.assertNotIn("signature", output.read_text(encoding="utf-8"))
            self.assertNotIn("must-not-persist", output.read_text(encoding="utf-8"))
            checksum = output.with_name("oidc.json.sha256").read_text(
                encoding="utf-8"
            )
            self.assertEqual(
                checksum,
                f"{hashlib.sha256(output.read_bytes()).hexdigest()}  oidc.json\n",
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/junca_validator_ami_build_request.py"
REQUEST = ROOT / "tests/fixtures/junca_validator_ami_build_request.json"
WORKFLOW = ROOT / ".github/workflows/junca-validator-ami-build.yml"
FOUNDATION_WORKFLOW = (
    ROOT / ".github/workflows/junca-validator-foundation-release.yml"
)
COMPONENT = ROOT / ".github/image-builder/validator-component.yml"
SUPPLY_CHAIN_LOCK = ROOT / "config/junca_validator_ami_supply_chain_lock.json"
SPEC = importlib.util.spec_from_file_location("ami_request", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def canonical_request() -> dict:
    return json.loads(REQUEST.read_text(encoding="utf-8"))


def lineage_readbacks(request: dict) -> tuple[dict, dict, dict, str, str]:
    account_id = "595710543956"
    region = "us-east-1"
    lineage_name = "junca-validator-12345-2"
    image_arn = (
        f"arn:aws:imagebuilder:{region}:{account_id}:"
        f"image/{lineage_name}/1.0.0/1"
    )
    recipe_arn = (
        f"arn:aws:imagebuilder:{region}:{account_id}:"
        f"image-recipe/{lineage_name}/1.0.0"
    )
    component_arn = (
        f"arn:aws:imagebuilder:{region}:{account_id}:"
        f"component/{lineage_name}/1.0.0/1"
    )
    ami_id = "ami-0fedcba9876543210"
    tags = {
        "Network": "Public Testnet",
        "Governance": "JAIOS Institutional Governance",
        "RequestSchema": "junca-validator-ami-build-request/v2",
        "SourceCommit": request["source_commit"],
        "NodeArtifactSHA256": request["node_sha256"],
        "GenesisSHA256": request["genesis_sha256"],
        "RequestDigest": request["request_sha256"],
        "ParentAMIId": request["parent_ami_id"],
        "ParentAMIOwnerId": request["parent_ami_owner_id"],
        "ParentAMIName": request["parent_ami_name"],
        "ComponentSourceSHA256": request["component_source_sha256"],
        "DependencyLockSHA256": request["dependency_lock_sha256"],
        "SupplyChainPolicySHA256": request[
            "supply_chain_policy_sha256"
        ],
        "DnfReleasever": request["dnf_releasever"],
        "Boto3NEVRA": request["python3_boto3_nevra"],
        "BotocoreNEVRA": request["python3_botocore_nevra"],
    }
    parameters = [
        {
            "name": "ArtifactBucket",
            "value": [
                f"junca-validator-ami-build-{account_id}-12345-2"
            ],
        },
        {"name": "NodeSHA256", "value": [request["node_sha256"]]},
        {
            "name": "GenesisSHA256",
            "value": [request["genesis_sha256"]],
        },
        {
            "name": "ParentAMIId",
            "value": [request["parent_ami_id"]],
        },
        {
            "name": "DnfReleasever",
            "value": [request["dnf_releasever"]],
        },
        {
            "name": "Boto3Nevra",
            "value": [request["python3_boto3_nevra"]],
        },
        {
            "name": "BotocoreNevra",
            "value": [request["python3_botocore_nevra"]],
        },
        {
            "name": "ComponentSourceSHA256",
            "value": [request["component_source_sha256"]],
        },
        {
            "name": "DependencyLockSHA256",
            "value": [request["dependency_lock_sha256"]],
        },
        {
            "name": "SupplyChainPolicySHA256",
            "value": [request["supply_chain_policy_sha256"]],
        },
    ]
    image = {
        "image": {
            "arn": image_arn,
            "name": lineage_name,
            "version": "1.0.0/1",
            "platform": "Linux",
            "state": {"status": "AVAILABLE"},
            "imageRecipe": {"arn": recipe_arn},
            "outputResources": {
                "amis": [
                    {
                        "image": ami_id,
                        "region": region,
                        "accountId": account_id,
                        "state": {"status": "AVAILABLE"},
                    }
                ]
            },
            "tags": tags,
        }
    }
    recipe = {
        "imageRecipe": {
            "arn": recipe_arn,
            "name": lineage_name,
            "version": "1.0.0",
            "owner": account_id,
            "type": "AMI",
            "platform": "Linux",
            "parentImage": request["parent_ami_id"],
            "components": [
                {
                    "componentArn": component_arn,
                    "parameters": parameters,
                }
            ],
            "tags": tags,
        }
    }
    component = {
        "component": {
            "arn": component_arn,
            "name": lineage_name,
            "version": "1.0.0",
            "owner": account_id,
            "platform": "Linux",
            "data": COMPONENT.read_text(encoding="utf-8"),
            "tags": tags,
        }
    }
    return image, recipe, component, image_arn, ami_id


class ValidatorAmiBuildRequestTests(unittest.TestCase):
    def test_canonical_request_is_authorized_and_digest_bound(self):
        request = canonical_request()
        outputs = MODULE.validate_request(request)
        self.assertEqual(outputs["source_run_id"], "30273062161")
        self.assertEqual(
            outputs["source_commit"],
            "598152b38364e1cc85ec5e6e737f3e5830945d8a",
        )
        self.assertEqual(
            outputs["request_sha256"],
            MODULE.canonical_request_sha256(request),
        )
        self.assertEqual(
            outputs["parent_ami_id"],
            "ami-0123456789abcdef0",
        )
        self.assertEqual(
            outputs["dependency_lock_sha256"],
            MODULE.canonical_dependency_lock_sha256(request),
        )

    def test_tampered_immutable_input_is_rejected(self):
        request = canonical_request()
        request["node_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "request_sha256 mismatch",
        ):
            MODULE.validate_request(request)

    def test_artifact_names_must_be_bound_to_source_run(self):
        request = canonical_request()
        request["node_artifact_name"] = "junca-validator-runtime-1"
        request["request_sha256"] = MODULE.canonical_request_sha256(request)
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "node artifact is not bound",
        ):
            MODULE.validate_request(request)

    def test_release_boundary_cannot_enable_mainnet_assets_or_bridge(self):
        for boundary in ("mainnet_changed", "assets_moved", "bridge_activated"):
            with self.subTest(boundary=boundary):
                request = canonical_request()
                request["boundaries"][boundary] = True
                request["request_sha256"] = MODULE.canonical_request_sha256(request)
                with self.assertRaisesRegex(
                    MODULE.RequestValidationError,
                    "release boundary mismatch",
                ):
                    MODULE.validate_request(request)

    def test_unknown_fields_fail_closed(self):
        request = canonical_request()
        request["unexpected"] = True
        request["request_sha256"] = MODULE.canonical_request_sha256(request)
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "fields do not match",
        ):
            MODULE.validate_request(request)

    def test_every_supply_chain_input_is_request_digest_bound(self):
        replacements = {
            "parent_ami_id": "ami-fedcba98765432100",
            "parent_ami_owner_id": "000000000000",
            "parent_ami_name":
                "al2023-ami-2023.12.20260724.1-kernel-6.18-x86_64",
            "component_source_sha256": "0" * 64,
            "dependency_lock_sha256": "1" * 64,
            "supply_chain_policy_sha256": "2" * 64,
            "dnf_releasever": "2023.11.20260611",
            "python3_boto3_nevra":
                "python3-boto3-0:1.40.30-1.amzn2023.0.1.noarch",
            "python3_botocore_nevra":
                "python3-botocore-0:1.40.30-1.amzn2023.0.1.noarch",
        }
        for field, replacement in replacements.items():
            with self.subTest(field=field):
                request = canonical_request()
                sealed_digest = request["request_sha256"]
                request[field] = replacement
                self.assertNotEqual(
                    MODULE.canonical_request_sha256(request),
                    sealed_digest,
                )
                with self.assertRaises(MODULE.RequestValidationError):
                    MODULE.validate_request(request)

    def test_parent_ami_must_be_exact_amazon_linux_image(self):
        cases = (
            ("parent_ami_id", "latest", "exact AMI ID"),
            ("parent_ami_owner_id", "000000000000", "not Amazon Linux"),
            (
                "parent_ami_name",
                "al2023-ami-kernel-default-x86_64",
                "exact AL2023 AMI name",
            ),
        )
        for field, value, error in cases:
            with self.subTest(field=field):
                request = canonical_request()
                request[field] = value
                request["request_sha256"] = MODULE.canonical_request_sha256(
                    request
                )
                with self.assertRaisesRegex(
                    MODULE.RequestValidationError,
                    error,
                ):
                    MODULE.validate_request(request)

    def test_parent_ami_name_must_bind_exact_releasever(self):
        request = canonical_request()
        request["dnf_releasever"] = "2023.11.20260611"
        request["dependency_lock_sha256"] = (
            MODULE.canonical_dependency_lock_sha256(request)
        )
        request["request_sha256"] = MODULE.canonical_request_sha256(request)
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "parent AMI name is not bound",
        ):
            MODULE.validate_request(request)

    def test_dependency_packages_require_exact_safe_nevra(self):
        cases = (
            ("python3_boto3_nevra", "python3-boto3"),
            (
                "python3_botocore_nevra",
                "python3-botocore-0:1.40.31-1.amzn2023.0.1.noarch;id",
            ),
        )
        for field, value in cases:
            with self.subTest(field=field):
                request = canonical_request()
                request[field] = value
                request["dependency_lock_sha256"] = (
                    MODULE.canonical_dependency_lock_sha256(request)
                )
                request["request_sha256"] = MODULE.canonical_request_sha256(
                    request
                )
                with self.assertRaisesRegex(
                    MODULE.RequestValidationError,
                    "exact package NEVRA",
                ):
                    MODULE.validate_request(request)

    def test_dependency_lock_digest_is_canonical_and_ordered(self):
        request = canonical_request()
        lock = MODULE.canonical_dependency_lock(request)
        self.assertEqual(
            lock,
            {
                "schema_version": "junca-validator-ami-dependency-lock/v1",
                "distribution": "amazon-linux-2023",
                "architecture": "x86_64",
                "dnf_releasever": "2023.12.20260724",
                "packages": [
                    {
                        "name": "python3-boto3",
                        "nevra": request["python3_boto3_nevra"],
                    },
                    {
                        "name": "python3-botocore",
                        "nevra": request["python3_botocore_nevra"],
                    },
                ],
                "install_weak_dependencies": False,
            },
        )
        self.assertEqual(
            request["dependency_lock_sha256"],
            MODULE.canonical_dependency_lock_sha256(request),
        )
        request["python3_botocore_nevra"] = (
            "python3-botocore-0:1.40.30-1.amzn2023.0.1.noarch"
        )
        self.assertNotEqual(
            request["dependency_lock_sha256"],
            MODULE.canonical_dependency_lock_sha256(request),
        )

    def test_repository_supply_chain_digests_match_request_fixture(self):
        request = canonical_request()
        self.assertEqual(
            hashlib.sha256(COMPONENT.read_bytes()).hexdigest(),
            request["component_source_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(SUPPLY_CHAIN_LOCK.read_bytes()).hexdigest(),
            request["supply_chain_policy_sha256"],
        )

    def test_image_builder_lineage_is_exact_and_complete(self):
        request = canonical_request()
        image, recipe, component, image_arn, ami_id = lineage_readbacks(
            request
        )
        outputs = MODULE.validate_image_builder_lineage(
            image_readback=image,
            recipe_readback=recipe,
            component_readback=component,
            component_source=COMPONENT.read_bytes(),
            request=request,
            image_builder_arn=image_arn,
            ami_id=ami_id,
            aws_account_id="595710543956",
            aws_region="us-east-1",
        )
        self.assertEqual(outputs["image_builder_arn"], image_arn)
        self.assertIn(":image-recipe/junca-validator-12345-2/", outputs[
            "image_recipe_arn"
        ])
        self.assertIn(":component/junca-validator-12345-2/", outputs[
            "component_arn"
        ])

    def test_image_builder_lineage_cli_is_fail_closed(self):
        request = canonical_request()
        image, recipe, component, image_arn, ami_id = lineage_readbacks(
            request
        )
        request["request_sha256"] = ""
        with TemporaryDirectory() as directory:
            directory_path = Path(directory)
            paths = {
                "request": directory_path / "request.json",
                "image": directory_path / "image.json",
                "recipe": directory_path / "recipe.json",
                "component": directory_path / "component.json",
            }
            for name, value in (
                ("request", request),
                ("image", image),
                ("recipe", recipe),
                ("component", component),
            ):
                paths[name].write_text(
                    json.dumps(value),
                    encoding="utf-8",
                )
            command = [
                sys.executable,
                str(SCRIPT),
                "--request",
                str(paths["request"]),
                "--seal-missing-digest",
                "--lineage-image-readback",
                str(paths["image"]),
                "--lineage-recipe-readback",
                str(paths["recipe"]),
                "--lineage-component-readback",
                str(paths["component"]),
                "--lineage-component-source",
                str(COMPONENT),
                "--lineage-image-builder-arn",
                image_arn,
                "--lineage-ami-id",
                ami_id,
                "--lineage-aws-account-id",
                "595710543956",
                "--lineage-aws-region",
                "us-east-1",
            ]
            result = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            recipe["imageRecipe"]["parentImage"] = (
                "ami-00000000000000000"
            )
            paths["recipe"].write_text(
                json.dumps(recipe),
                encoding="utf-8",
            )
            result = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("recipe parent AMI mismatch", result.stderr)

    def test_mutable_ami_tags_cannot_forge_image_builder_lineage(self):
        request = canonical_request()
        image, recipe, component, image_arn, ami_id = lineage_readbacks(
            request
        )
        cases = []

        wrong_output = copy.deepcopy(image)
        wrong_output["image"]["outputResources"]["amis"][0]["image"] = (
            "ami-00000000000000000"
        )
        cases.append(("output AMI", wrong_output, recipe, component))

        wrong_parent = copy.deepcopy(recipe)
        wrong_parent["imageRecipe"]["parentImage"] = (
            "ami-00000000000000000"
        )
        cases.append(("parent AMI", image, wrong_parent, component))

        wrong_component = copy.deepcopy(component)
        wrong_component["component"]["data"] += "\n# forged\n"
        cases.append(("component source", image, recipe, wrong_component))

        wrong_component_owner = copy.deepcopy(component)
        wrong_component_owner["component"]["owner"] = "000000000000"
        cases.append(
            (
                "component owner",
                image,
                recipe,
                wrong_component_owner,
            )
        )

        for label, bad_image, bad_recipe, bad_component in cases:
            with self.subTest(label=label):
                with self.assertRaises(MODULE.RequestValidationError):
                    MODULE.validate_image_builder_lineage(
                        image_readback=bad_image,
                        recipe_readback=bad_recipe,
                        component_readback=bad_component,
                        component_source=COMPONENT.read_bytes(),
                        request=request,
                        image_builder_arn=image_arn,
                        ami_id=ami_id,
                        aws_account_id="595710543956",
                        aws_region="us-east-1",
                    )

        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "Image Builder ARN is not exact",
        ):
            MODULE.validate_image_builder_lineage(
                image_readback=image,
                recipe_readback=recipe,
                component_readback=component,
                component_source=COMPONENT.read_bytes(),
                request=request,
                image_builder_arn=image_arn.replace(
                    ":595710543956:",
                    ":000000000000:",
                ),
                ami_id=ami_id,
                aws_account_id="595710543956",
                aws_region="us-east-1",
            )

    def test_every_recipe_parameter_is_lineage_bound(self):
        request = canonical_request()
        image, recipe, component, image_arn, ami_id = lineage_readbacks(
            request
        )
        parameters = recipe["imageRecipe"]["components"][0]["parameters"]
        for index, parameter in enumerate(parameters):
            with self.subTest(parameter=parameter["name"]):
                bad_recipe = copy.deepcopy(recipe)
                bad_recipe["imageRecipe"]["components"][0][
                    "parameters"
                ][index]["value"] = ["forged"]
                with self.assertRaisesRegex(
                    MODULE.RequestValidationError,
                    "parameter closure mismatch",
                ):
                    MODULE.validate_image_builder_lineage(
                        image_readback=image,
                        recipe_readback=bad_recipe,
                        component_readback=component,
                        component_source=COMPONENT.read_bytes(),
                        request=request,
                        image_builder_arn=image_arn,
                        ami_id=ami_id,
                        aws_account_id="595710543956",
                        aws_region="us-east-1",
                    )

    def test_workflow_has_no_mutable_parent_or_rendered_component(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("ami-amazon-linux-latest", workflow)
        self.assertNotIn("aws ssm get-parameter", workflow)
        self.assertNotIn("sed \\", workflow)
        self.assertNotIn("file://build/validator-component.yml", workflow)
        self.assertIn('--parent-image "$PARENT_AMI_ID"', workflow)
        self.assertIn("aws imagebuilder get-image-recipe", workflow)
        self.assertIn(
            '"junca-validator-ami-build-request/v2"',
            workflow,
        )
        for tag in (
            "RequestSchema",
            "ParentAMIId",
            "ParentAMIOwnerId",
            "ParentAMIName",
            "ComponentSourceSHA256",
            "DependencyLockSHA256",
            "SupplyChainPolicySHA256",
            "DnfReleasever",
            "Boto3NEVRA",
            "BotocoreNEVRA",
        ):
            self.assertGreaterEqual(workflow.count(tag), 3, tag)

    def test_reuse_requires_live_image_builder_lineage(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        reuse = workflow.split(
            'if [[ "$existing_count" = 1 ]]; then',
            1,
        )[1].split('suffix="${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"', 1)[0]
        for required in (
            "one non-empty ImageBuilderArn tag is required",
            'verify_image_builder_lineage "$image_arn" "$ami_id"',
            "aws imagebuilder get-image",
            "aws imagebuilder get-image-recipe",
            "aws imagebuilder get-component",
            "--lineage-image-readback",
            "--lineage-recipe-readback",
            "--lineage-component-readback",
        ):
            self.assertIn(required, workflow)
        self.assertLess(
            reuse.index('verify_image_builder_lineage "$image_arn" "$ami_id"'),
            reuse.index(
                'write_verified_evidence "$ami_id" "$image_arn" true'
            ),
        )

    def test_verified_ami_evidence_is_v2_with_full_closure(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        evidence = workflow.split("write_verified_evidence() {", 1)[1].split(
            "\n          }",
            1,
        )[0]
        self.assertIn(
            'schema_version: "junca-validator-ami-build/v2"',
            evidence,
        )
        for field in (
            "request_schema",
            "image_builder_arn",
            "parent_ami_id",
            "parent_ami_owner_id",
            "parent_ami_name",
            "component_source_sha256",
            "dependency_lock_sha256",
            "supply_chain_policy_sha256",
            "dnf_releasever",
            "python3_boto3_nevra",
            "python3_botocore_nevra",
        ):
            self.assertIn(f"{field}:", evidence)
        self.assertNotIn("if $image_arn", evidence)

    def test_foundation_requires_v2_closure_before_any_rollout(self):
        workflow = FOUNDATION_WORKFLOW.read_text(encoding="utf-8")
        job_header = workflow.split("jobs:", 1)[1].split("steps:", 1)[0]
        self.assertNotIn("\n    if:", job_header)
        authorization = workflow.index(
            "- name: Enforce explicit rollout authorization"
        )
        checkout = workflow.index(
            "- uses: actions/checkout@"
            "11d5960a326750d5838078e36cf38b85af677262"
        )
        ami_exists = workflow.index('test -f "$evidence"')
        ami_verified = workflow.index('.state == "AMI_VERIFIED"')
        decision_exists = workflow.index('test -f "$decision"')
        decision_verified = workflow.index(
            '.decision == "PROMOTION_GATE_PASS"'
        )
        aws_credentials = workflow.index(
            "- uses: aws-actions/configure-aws-credentials"
        )
        self.assertLess(authorization, checkout)
        self.assertLess(ami_exists, ami_verified)
        self.assertLess(ami_verified, decision_exists)
        self.assertLess(decision_exists, decision_verified)
        self.assertLess(decision_verified, aws_credentials)
        self.assertIn('test "$AUTHORIZE_ROLLOUT" =', workflow)
        self.assertIn(
            '.schema_version == "junca-validator-ami-build/v2"',
            workflow,
        )
        self.assertIn(
            ".candidate.ami_supply_chain.request_schema",
            workflow,
        )
        self.assertIn(
            "- name: Cross-bind live AMI supply-chain tags",
            workflow,
        )
        for field in (
            "request_schema",
            "image_builder_arn",
            "parent_ami_id",
            "parent_ami_owner_id",
            "parent_ami_name",
            "component_source_sha256",
            "dependency_lock_sha256",
            "supply_chain_policy_sha256",
            "dnf_releasever",
            "python3_boto3_nevra",
            "python3_botocore_nevra",
        ):
            self.assertIn(f'"{field}"', workflow)

    def test_component_uses_only_exact_parameterized_dependencies(self):
        component = COMPONENT.read_text(encoding="utf-8")
        self.assertNotIn("dnf install -y python3-boto3", component)
        self.assertNotIn("__BUCKET__", component)
        self.assertNotIn("__NODE_SHA256__", component)
        self.assertIn("--releasever=\"{{ DnfReleasever }}\"", component)
        self.assertIn("--setopt=install_weak_deps=False", component)
        self.assertIn('"{{ Boto3Nevra }}"', component)
        self.assertIn('"{{ BotocoreNevra }}"', component)
        self.assertIn("MAINNET_CHANGED=false", component)
        self.assertIn("ASSETS_MOVED=false", component)
        self.assertIn("BRIDGE_ACTIVATED=false", component)

    def test_supply_chain_lock_forbids_mutable_values(self):
        lock = json.loads(SUPPLY_CHAIN_LOCK.read_text(encoding="utf-8"))
        self.assertEqual(
            lock["schema_version"],
            "junca-validator-ami-supply-chain-lock/v1",
        )
        self.assertEqual(lock["parent_ami"]["owner_id"], "137112412989")
        self.assertFalse(lock["parent_ami"]["mutable_aliases_allowed"])
        self.assertFalse(lock["component"]["mutable_rendering_allowed"])
        self.assertFalse(
            lock["dependency_lock"]["install_weak_dependencies"]
        )
        self.assertEqual(
            lock["dependency_lock"]["packages"],
            ["python3-boto3", "python3-botocore"],
        )
        self.assertEqual(
            lock["boundaries"],
            {
                "mainnet_changed": False,
                "assets_moved": False,
                "bridge_activated": False,
            },
        )

    def test_wrong_approval_phrase_is_rejected(self):
        request = canonical_request()
        request["approval_phrase"] = "APPROVE"
        request["request_sha256"] = MODULE.canonical_request_sha256(request)
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "approval phrase mismatch",
        ):
            MODULE.validate_request(request)

    def test_manual_sealing_uses_same_canonical_digest(self):
        request = canonical_request()
        expected = request["request_sha256"]
        request["request_sha256"] = ""
        request["request_sha256"] = MODULE.canonical_request_sha256(request)
        self.assertEqual(request["request_sha256"], expected)
        self.assertEqual(MODULE.validate_request(request)["request_sha256"], expected)

    def test_cli_seals_dependency_lock_before_request_digest(self):
        request = canonical_request()
        expected_dependency = request["dependency_lock_sha256"]
        expected_request = request["request_sha256"]
        request["dependency_lock_sha256"] = ""
        request["request_sha256"] = ""
        with TemporaryDirectory() as directory:
            request_path = Path(directory, "request.json")
            output_path = Path(directory, "outputs")
            request_path.write_text(
                json.dumps(request),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--request",
                    str(request_path),
                    "--seal-missing-digest",
                    "--github-output",
                    str(output_path),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs = dict(
                line.split("=", 1)
                for line in output_path.read_text(
                    encoding="utf-8"
                ).splitlines()
            )
        self.assertEqual(
            outputs["dependency_lock_sha256"],
            expected_dependency,
        )
        self.assertEqual(outputs["request_sha256"], expected_request)

    def test_completed_migration_binding_preserves_runtime_identity_digest(self):
        request = canonical_request()
        runtime_digest = request["request_sha256"]
        request["migration_run_id"] = "30303030303"
        request["migration_evidence_sha256"] = "7" * 64
        self.assertEqual(
            MODULE.canonical_request_sha256(request),
            runtime_digest,
        )
        outputs = MODULE.validate_request(
            request,
            require_migration_binding=True,
        )
        self.assertEqual(outputs["request_sha256"], runtime_digest)
        self.assertEqual(outputs["migration_run_id"], "30303030303")
        self.assertEqual(outputs["migration_evidence_sha256"], "7" * 64)

    def test_release_phase_requires_complete_valid_migration_binding(self):
        request = canonical_request()
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "completed migration binding is required",
        ):
            MODULE.validate_request(
                request,
                require_migration_binding=True,
            )
        request["migration_run_id"] = "30303030303"
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "fields do not match",
        ):
            MODULE.validate_request(request)
        request["migration_evidence_sha256"] = "invalid"
        with self.assertRaisesRegex(
            MODULE.RequestValidationError,
            "migration_evidence_sha256",
        ):
            MODULE.validate_request(
                request,
                require_migration_binding=True,
            )


if __name__ == "__main__":
    unittest.main()

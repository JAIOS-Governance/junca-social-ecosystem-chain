from __future__ import annotations

import unittest

from jaios.social_ecosystem_chain.terraform_plan_guard import (
    TerraformPlanGuardError,
    evaluate_terraform_plan,
    require_safe_terraform_plan,
)


def _plan(*changes):
    return {
        "format_version": "1.2",
        "terraform_version": "1.9.0",
        "resource_changes": list(changes),
    }


def _change(address, actions, *, mode="managed"):
    return {
        "address": address,
        "mode": mode,
        "change": {"actions": list(actions)},
    }


class TerraformPlanGuardTests(unittest.TestCase):
    def test_create_update_and_noop_are_reviewable(self) -> None:
        result = require_safe_terraform_plan(
            _plan(
                _change("aws_instance.validator[0]", ("update",)),
                _change("aws_instance.validator[1]", ("no-op",)),
                _change("aws_cloudwatch_log_group.mainnet", ("create",)),
                _change("data.aws_caller_identity.current", ("read",), mode="data"),
            )
        )

        self.assertTrue(result.approved)
        self.assertFalse(result.as_evidence()["apply_authorized"])
        self.assertRegex(result.plan_digest, r"^0x[0-9a-f]{64}$")

    def test_delete_is_rejected(self) -> None:
        result = evaluate_terraform_plan(
            _plan(_change("aws_ebs_volume.validator_state", ("delete",)))
        )

        self.assertFalse(result.approved)
        self.assertEqual(
            result.violations[0].reason,
            "managed resource deletion is prohibited",
        )
        with self.assertRaisesRegex(TerraformPlanGuardError, "not safe"):
            require_safe_terraform_plan(
                _plan(_change("aws_ebs_volume.validator_state", ("delete",)))
            )

    def test_replacement_is_rejected(self) -> None:
        result = evaluate_terraform_plan(
            _plan(
                _change(
                    "aws_instance.validator[0]",
                    ("delete", "create"),
                )
            )
        )

        self.assertFalse(result.approved)
        self.assertEqual(
            result.violations[0].reason,
            "managed resource replacement is prohibited",
        )

    def test_unknown_action_fails_closed(self) -> None:
        result = evaluate_terraform_plan(
            _plan(_change("aws_instance.validator[0]", ("forget",)))
        )

        self.assertFalse(result.approved)
        self.assertEqual(
            result.violations[0].reason,
            "managed resource action is not allowlisted",
        )

    def test_duplicate_resource_change_is_invalid(self) -> None:
        with self.assertRaisesRegex(TerraformPlanGuardError, "unique"):
            evaluate_terraform_plan(
                _plan(
                    _change("aws_instance.validator[0]", ("no-op",)),
                    _change("aws_instance.validator[0]", ("update",)),
                )
            )

    def test_evidence_preserves_mainnet_safety_boundary(self) -> None:
        evidence = evaluate_terraform_plan(_plan()).as_evidence()

        self.assertTrue(evidence["approved"])
        self.assertFalse(evidence["apply_authorized"])
        self.assertFalse(evidence["mainnet_changed"])
        self.assertFalse(evidence["assets_moved"])
        self.assertFalse(evidence["bridge_activated"])


if __name__ == "__main__":
    unittest.main()

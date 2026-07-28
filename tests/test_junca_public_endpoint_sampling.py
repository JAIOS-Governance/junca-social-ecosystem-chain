from __future__ import annotations

import unittest

from scripts.junca_public_testnet_endpoint_test import (
    AcceptanceError,
    BoundedAcceptanceError,
    run_bounded_acceptance,
)


class PublicEndpointSamplingTests(unittest.TestCase):
    def test_retries_complete_samples_and_preserves_failures(self):
        calls = 0
        sleeps: list[float] = []

        def sample():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise AcceptanceError(
                    "rpc/explorer: finalized block mismatch"
                )
            return {
                "status": "PASS",
                "scope": "Public Testnet Runtime Acceptance / Read-only",
                "observed_at": "2026-07-29T00:00:00+00:00",
                "finalized_head": {
                    "height": 42,
                    "hash": "0x" + "ab" * 32,
                },
                "checks": {
                    "health": "PASS",
                    "explorer": {"result": "PASS"},
                    "safe_rpc": {"result": "PASS"},
                    "unsafe_rpc_rejection": {"result": "PASS"},
                },
            }

        result = run_bounded_acceptance(
            sample,
            attempts=5,
            interval_seconds=5,
            sleeper=sleeps.append,
        )

        self.assertEqual(calls, 2)
        self.assertEqual(sleeps, [5.0])
        self.assertEqual(result["status"], "PASS")
        sampling = result["sampling"]
        self.assertEqual(
            sampling["strategy"], "BOUNDED_FULL_CONSISTENCY_SAMPLES"
        )
        self.assertEqual(sampling["max_attempts"], 5)
        self.assertEqual(sampling["accepted_attempt"], 2)
        self.assertEqual(sampling["sample_count"], 2)
        self.assertEqual(sampling["samples"][0]["status"], "FAIL")
        self.assertEqual(
            sampling["samples"][0]["error"],
            "rpc/explorer: finalized block mismatch",
        )
        self.assertEqual(sampling["samples"][1]["status"], "PASS")

    def test_never_accepts_a_failed_atomic_sample(self):
        calls = 0
        sleeps: list[float] = []

        def sample():
            nonlocal calls
            calls += 1
            raise AcceptanceError("rpc/explorer: finalized height mismatch")

        with self.assertRaises(BoundedAcceptanceError) as context:
            run_bounded_acceptance(
                sample,
                attempts=3,
                interval_seconds=2,
                sleeper=sleeps.append,
            )

        self.assertEqual(calls, 3)
        self.assertEqual(sleeps, [2.0, 2.0])
        self.assertEqual(len(context.exception.samples), 3)
        self.assertTrue(
            all(
                item["status"] == "FAIL"
                for item in context.exception.samples
            )
        )
        self.assertEqual(
            str(context.exception),
            "rpc/explorer: finalized height mismatch",
        )

    def test_does_not_sleep_after_first_sample_passes(self):
        sleeps: list[float] = []

        result = run_bounded_acceptance(
            lambda: {
                "status": "PASS",
                "scope": "Public Testnet Runtime Acceptance / Read-only",
                "observed_at": "2026-07-29T00:00:00+00:00",
                "finalized_head": {"height": 1},
                "checks": {},
            },
            attempts=5,
            interval_seconds=5,
            sleeper=sleeps.append,
        )

        self.assertEqual(sleeps, [])
        self.assertEqual(result["sampling"]["accepted_attempt"], 1)
        self.assertEqual(result["sampling"]["sample_count"], 1)

    def test_rejects_unbounded_or_invalid_sampling_configuration(self):
        invalid = (
            {"attempts": 0},
            {"attempts": 11},
            {"attempts": True},
            {"interval_seconds": -1},
            {"interval_seconds": 61},
            {"interval_seconds": True},
        )
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    run_bounded_acceptance(lambda: {}, **values)

    def test_sampling_does_not_change_atomic_acceptance_error(self):
        expected = "rpc/explorer: finalized block mismatch"

        def sample():
            raise AcceptanceError(expected)

        with self.assertRaises(BoundedAcceptanceError) as context:
            run_bounded_acceptance(
                sample,
                attempts=2,
                interval_seconds=0,
                sleeper=lambda _: None,
            )
        self.assertEqual(
            [item["error"] for item in context.exception.samples],
            [expected, expected],
        )


if __name__ == "__main__":
    unittest.main()

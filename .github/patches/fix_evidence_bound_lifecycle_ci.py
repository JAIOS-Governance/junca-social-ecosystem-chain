#!/usr/bin/env python3
"""Fix exact CI defects in the evidence-bound rolling lifecycle branch."""

from __future__ import annotations

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, observed {count}")
    return text.replace(old, new)


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: fix_evidence_bound_lifecycle_ci.py FOUNDATION TEST")

    foundation = Path(sys.argv[1])
    tests = Path(sys.argv[2])

    foundation_text = foundation.read_text(encoding="utf-8")
    foundation_text = replace_once(
        foundation_text,
        '''  jq -e \\
    --argjson instances "$instances_json" \\
    --arg target_artifact_sha256 "$target_artifact_sha256" '
      type == "array" and length == 3 and
      [.[].validator_id] ==
        ["validator-01", "validator-02", "validator-03"] and
      [.[].instance_id] == $instances and
      all(
        .[];
        (.runtime_version | type == "string" and
          test("^[0-9a-f]{64}$")) and
        (.ami_id | type == "string" and
          test("^ami-[0-9a-f]{8,17}$")) and
        (.target_runtime | type == "boolean")
      ) and
      all(
        range(0; 3) as $index;
        if $index < $updated_count then
          .[$index].runtime_version == $target_artifact_sha256
        else
          true
        end
      )
    ' <<<"$baseline_bindings_json" >/dev/null
''',
        '''  jq -e \\
    --argjson updated_count "$updated_count" \\
    --argjson instances "$instances_json" \\
    --arg target_artifact_sha256 "$target_artifact_sha256" '
      . as $baseline |
      type == "array" and length == 3 and
      [.[].validator_id] ==
        ["validator-01", "validator-02", "validator-03"] and
      [.[].instance_id] == $instances and
      all(
        .[];
        (.runtime_version | type == "string" and
          test("^[0-9a-f]{64}$")) and
        (.ami_id | type == "string" and
          test("^ami-[0-9a-f]{8,17}$")) and
        (.target_runtime | type == "boolean")
      ) and
      all(
        range(0; 3);
        . as $index |
        if $index < $updated_count then
          $baseline[$index].runtime_version == $target_artifact_sha256
        else
          true
        end
      )
    ' <<<"$baseline_bindings_json" >/dev/null
''',
        "pre-rollout jq generator",
    )
    foundation.write_text(foundation_text, encoding="utf-8")

    test_text = tests.read_text(encoding="utf-8")
    test_text = replace_once(
        test_text,
        '''            "python -m jaios.social_ecosystem_chain.rolling_compatibility",
            "write_rolling_compatibility_evidence",
''',
        '''            "python scripts/junca_live_rollout_prefix_gate.py",
            "--mode rolling",
            "write_rolling_compatibility_evidence",
''',
        "rolling evaluator assertion",
    )
    test_text = replace_once(
        test_text,
        '''        for updated_count in range(4):
            with self.subTest(updated_count=updated_count):
                result = run(
                    "build_pre_rollout_finality_bindings",
                    (
                        str(updated_count),
                        target,
                        previous,
                        *instances,
                    ),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                bindings = json.loads(result.stdout)
                self.assertEqual(
                    [item["instance_id"] for item in bindings],
                    list(instances),
                )
                for index, item in enumerate(bindings):
                    is_target = index < updated_count
                    self.assertEqual(
                        item["expected_artifact_sha256"],
                        target if is_target else previous,
                    )
                    self.assertEqual(
                        item["allow_missing_finality_keys"],
                        not is_target,
                    )
''',
        '''        for updated_count in range(4):
            with self.subTest(updated_count=updated_count):
                baseline = [
                    {
                        "validator_id": f"validator-0{index + 1}",
                        "instance_id": instance_id,
                        "runtime_version": (
                            target if index < updated_count else previous
                        ),
                        "ami_id": "ami-11111111111111111",
                        "target_runtime": index < updated_count,
                    }
                    for index, instance_id in enumerate(instances)
                ]
                result = run(
                    "build_pre_rollout_finality_bindings",
                    (
                        str(updated_count),
                        target,
                        json.dumps(baseline),
                        *instances,
                    ),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                bindings = json.loads(result.stdout)
                self.assertEqual(
                    [item["instance_id"] for item in bindings],
                    list(instances),
                )
                for index, item in enumerate(bindings):
                    is_target = index < updated_count
                    self.assertEqual(
                        item["expected_artifact_sha256"],
                        target if is_target else previous,
                    )
                    self.assertEqual(
                        item["allow_missing_finality_keys"],
                        not is_target,
                    )
''',
        "binding builder regression fixture",
    )
    tests.write_text(test_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

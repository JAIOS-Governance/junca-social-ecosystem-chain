#!/usr/bin/env python3
"""Apply exact expired-epoch recovery changes to the Public Testnet rollout."""

from __future__ import annotations

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{label}: expected exactly one match, observed {count}"
        )
    return text.replace(old, new)


def patch(path: Path, replacements: list[tuple[str, str, str]]) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new, label in replacements:
        text = replace_once(text, old, new, label)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_renew_expired_foundation_epoch.py REPO")
    root = Path(sys.argv[1]).resolve()

    variables = root / "infra/aws/public-testnet/variables.tf"
    patch(
        variables,
        [
            (
                '''variable "validator_slot_epoch_seconds" {
  description = "Shared Unix epoch for the canonical 30-second validator slots. Zero is allowed only while automatic finality is disabled."
  type        = number
  default     = 0

  validation {
    condition = (
      var.validator_slot_epoch_seconds >= 0 &&
      floor(var.validator_slot_epoch_seconds) == var.validator_slot_epoch_seconds &&
      var.validator_slot_epoch_seconds % 30 == 0
    )
    error_message = "validator_slot_epoch_seconds must be a non-negative Unix timestamp on a 30-second boundary."
  }
}
''',
                '''variable "validator_slot_epoch_seconds" {
  description = "Shared Unix epoch for the canonical 30-second validator slots. Zero is allowed only while automatic finality is disabled."
  type        = number
  default     = 0

  validation {
    condition = (
      var.validator_slot_epoch_seconds >= 0 &&
      floor(var.validator_slot_epoch_seconds) == var.validator_slot_epoch_seconds &&
      var.validator_slot_epoch_seconds % 30 == 0
    )
    error_message = "validator_slot_epoch_seconds must be a non-negative Unix timestamp on a 30-second boundary."
  }
}

variable "validator_bootstrap_slot_epoch_seconds" {
  description = "Optional per-validator immutable bootstrap epochs. Null uses the shared runtime activation epoch for all validators."
  type        = list(number)
  default     = null
  nullable    = true

  validation {
    condition = var.validator_bootstrap_slot_epoch_seconds == null ? true : (
      length(var.validator_bootstrap_slot_epoch_seconds) == 3 &&
      alltrue([
        for epoch in var.validator_bootstrap_slot_epoch_seconds :
        epoch >= 0 &&
        floor(epoch) == epoch &&
        epoch % 30 == 0
      ])
    )
    error_message = "validator_bootstrap_slot_epoch_seconds must be null or exactly three non-negative 30-second-boundary Unix timestamps."
  }
}
''',
                "bootstrap epoch variable",
            )
        ],
    )

    runtime = root / "infra/aws/public-testnet/main.tf"
    patch(
        runtime,
        [
            (
                '''  health_hostname       = "health.${var.domain_name}"
}
''',
                '''  health_hostname       = "health.${var.domain_name}"
  validator_bootstrap_slot_epochs = (
    var.validator_bootstrap_slot_epoch_seconds == null
    ? [for _ in range(3) : var.validator_slot_epoch_seconds]
    : var.validator_bootstrap_slot_epoch_seconds
  )
}
''',
                "bootstrap epoch local",
            ),
            (
                '''    slot_epoch_seconds = (
      var.automatic_finality_enabled
      ? var.validator_slot_epoch_seconds
      : 0
    )
''',
                '''    slot_epoch_seconds = (
      var.automatic_finality_enabled
      ? local.validator_bootstrap_slot_epochs[count.index]
      : 0
    )
''',
                "validator bootstrap user data",
            ),
            (
                '''    precondition {
      condition = (
        !var.automatic_finality_enabled ||
        (
          var.validator_block_interval_seconds == 30 &&
          var.validator_slot_epoch_seconds > 0 &&
          var.validator_slot_epoch_seconds % 30 == 0
        )
      )
      error_message = "Automatic finality requires a shared positive 30-second-boundary slot epoch."
    }

    precondition {
      condition = (
        !var.enable_validator_state_volumes ||
''',
                '''    precondition {
      condition = (
        !var.automatic_finality_enabled ||
        (
          var.validator_block_interval_seconds == 30 &&
          var.validator_slot_epoch_seconds > 0 &&
          var.validator_slot_epoch_seconds % 30 == 0
        )
      )
      error_message = "Automatic finality requires a shared positive 30-second-boundary slot epoch."
    }

    precondition {
      condition = (
        length(local.validator_bootstrap_slot_epochs) == 3 &&
        alltrue([
          for epoch in local.validator_bootstrap_slot_epochs :
          floor(epoch) == epoch &&
          epoch % 30 == 0 &&
          (
            var.automatic_finality_enabled
            ? epoch > 0
            : epoch == 0
          )
        ])
      )
      error_message = "Validator bootstrap epochs must be exact-three, 30-second aligned, and consistent with the automatic-finality boundary."
    }

    precondition {
      condition = (
        !var.enable_validator_state_volumes ||
''',
                "bootstrap epoch precondition",
            ),
        ],
    )

    outputs = root / "infra/aws/public-testnet/outputs.tf"
    patch(
        outputs,
        [
            (
                '''output "automatic_finality_readback" {
  description = "Terraform-canonical automatic finality settings shared by all three validators."
  value = {
    enabled                = var.automatic_finality_enabled
    block_interval_seconds = var.automatic_finality_enabled ? var.validator_block_interval_seconds : 0
    slot_epoch_seconds     = var.automatic_finality_enabled ? var.validator_slot_epoch_seconds : 0
  }
}
''',
                '''output "automatic_finality_readback" {
  description = "Terraform-canonical automatic finality settings shared by all three validators."
  value = {
    enabled                = var.automatic_finality_enabled
    block_interval_seconds = var.automatic_finality_enabled ? var.validator_block_interval_seconds : 0
    slot_epoch_seconds     = var.automatic_finality_enabled ? var.validator_slot_epoch_seconds : 0
  }
}

output "validator_bootstrap_finality_readback" {
  description = "Per-validator immutable bootstrap epochs, separated from the current runtime activation epoch."
  value = [
    for index, epoch in local.validator_bootstrap_slot_epochs : {
      validator_id       = format("validator-%02d", index + 1)
      slot_epoch_seconds = var.automatic_finality_enabled ? epoch : 0
    }
  ]
}
''',
                "bootstrap epoch output",
            )
        ],
    )

    workflow = root / ".github/workflows/junca-validator-foundation-release.yml"
    patch(
        workflow,
        [
            (
                '''      resume_run_id:
        description: "Prior failed Foundation Release run ID, or 0 for a fresh rollout"
        required: false
        default: "0"
        type: string
      authorize_rollout:
''',
                '''      resume_run_id:
        description: "Prior failed Foundation Release run ID, or 0 for a fresh rollout"
        required: false
        default: "0"
        type: string
      renew_expired_epoch:
        description: "NONE or exact authorization phrase RENEW_EXPIRED_QUIESCED_EPOCH"
        required: false
        default: "NONE"
        type: string
      renewal_preserve_prefix_count:
        description: "Exact already-replaced target prefix to preserve during an authorized epoch renewal"
        required: false
        default: "0"
        type: string
      authorize_rollout:
''',
                "renewal workflow inputs",
            ),
            (
                '''      ROLLING_RESUME_RUN_ID: ${{ inputs.resume_run_id }}
      FOUNDATION_ROLLING_RELEASE: "true"
''',
                '''      ROLLING_RESUME_RUN_ID: ${{ inputs.resume_run_id }}
      RENEW_EXPIRED_EPOCH: ${{ inputs.renew_expired_epoch }}
      RENEWAL_PRESERVE_PREFIX_COUNT: ${{ inputs.renewal_preserve_prefix_count }}
      FOUNDATION_ROLLING_RELEASE: "true"
''',
                "renewal workflow environment",
            ),
            (
                '''      - name: Generate one-time shared automatic finality epoch
        run: |
          set -euo pipefail
          interval=30
          now="$(date +%s)"
          minimum_remaining=900
          maximum_remaining=7230
          if [[ -n "${ROLLING_RESUME_EVIDENCE_PATH:-}" ]]; then
            test "$ROLLING_RESUME_RUN_ID" != "0"
            test -f "$ROLLING_RESUME_EVIDENCE_PATH"
            test "$(
              jq -er '.automatic_finality.block_interval_seconds' \
                "$ROLLING_RESUME_EVIDENCE_PATH"
            )" = "$interval"
            slot_epoch="$(
              jq -er '
                .automatic_finality.slot_epoch_seconds
                | select(
                    type == "number" and
                    floor == . and
                    . > 0 and
                    . % 30 == 0
                  )
              ' "$ROLLING_RESUME_EVIDENCE_PATH"
            )"
          else
            test "$ROLLING_RESUME_RUN_ID" = "0"
            # Keep activation clear of the bounded three-node replacement and
            # SSM windows. A resume reuses this exact epoch; it never generates
            # a second Terraform/user_data schedule.
            activation_delay=7200
            slot_epoch="$(( ((now + activation_delay + interval - 1) / interval) * interval ))"
          fi
          remaining="$((slot_epoch - now))"
          test "$remaining" -ge "$minimum_remaining"
          test "$remaining" -le "$maximum_remaining"
          test "$((slot_epoch % interval))" -eq 0
          {
            echo "AUTOMATIC_FINALITY_ENABLED=true"
            echo "VALIDATOR_BLOCK_INTERVAL_SECONDS=$interval"
            echo "VALIDATOR_SLOT_EPOCH_SECONDS=$slot_epoch"
          } >> "$GITHUB_ENV"
''',
                '''      - name: Generate or renew the shared automatic finality epoch
        run: |
          set -euo pipefail
          interval=30
          now="$(date +%s)"
          minimum_remaining=900
          maximum_remaining=7230
          activation_delay=7200
          renewal_authorization="${RENEW_EXPIRED_EPOCH:-NONE}"
          preserve_prefix_count="${RENEWAL_PRESERVE_PREFIX_COUNT:-0}"
          case "$renewal_authorization" in
            NONE|RENEW_EXPIRED_QUIESCED_EPOCH) ;;
            *) echo "invalid expired-epoch renewal authorization" >&2; exit 2 ;;
          esac
          [[ "$preserve_prefix_count" =~ ^[0-3]$ ]]
          prior_slot_epoch=0
          renewal_performed=false
          renewal_prefix_count=0
          fresh_epoch="$(( ((now + activation_delay + interval - 1) / interval) * interval ))"

          if [[ -n "${ROLLING_RESUME_EVIDENCE_PATH:-}" ]]; then
            test "$ROLLING_RESUME_RUN_ID" != "0"
            test -f "$ROLLING_RESUME_EVIDENCE_PATH"
            test "$(
              jq -er '.automatic_finality.block_interval_seconds' \
                "$ROLLING_RESUME_EVIDENCE_PATH"
            )" = "$interval"
            prior_slot_epoch="$(
              jq -er '
                .automatic_finality.slot_epoch_seconds
                | select(
                    type == "number" and
                    floor == . and
                    . > 0 and
                    . % 30 == 0
                  )
              ' "$ROLLING_RESUME_EVIDENCE_PATH"
            )"
            prior_bootstrap_epochs="$(
              jq -ce --argjson prior "$prior_slot_epoch" '
                (
                  .terraform_bootstrap.slot_epoch_seconds //
                  [$prior, $prior, $prior]
                )
                | select(
                    type == "array" and
                    length == 3 and
                    all(.[];
                      type == "number" and
                      floor == . and
                      . > 0 and
                      . % 30 == 0
                    )
                  )
              ' "$ROLLING_RESUME_EVIDENCE_PATH"
            )"
            prior_updated_count="$(
              jq -er '.updated_count | select(type == "number" and . >= 0 and . <= 3)' \
                "$ROLLING_RESUME_EVIDENCE_PATH"
            )"
            prior_remaining="$((prior_slot_epoch - now))"
            if [[ "$prior_remaining" -ge "$minimum_remaining" &&
                  "$prior_remaining" -le "$maximum_remaining" ]]; then
              test "$renewal_authorization" = "NONE"
              test "$preserve_prefix_count" = "0"
              slot_epoch="$prior_slot_epoch"
              bootstrap_epochs="$prior_bootstrap_epochs"
            else
              test "$renewal_authorization" = "RENEW_EXPIRED_QUIESCED_EPOCH"
              test "$preserve_prefix_count" -ge "$prior_updated_count"
              max_prefix="$((prior_updated_count + 1))"
              if (( max_prefix > 3 )); then
                max_prefix=3
              fi
              test "$preserve_prefix_count" -le "$max_prefix"
              slot_epoch="$fresh_epoch"
              bootstrap_epochs="$(
                jq -cn \
                  --argjson prior "$prior_bootstrap_epochs" \
                  --argjson fresh "$slot_epoch" \
                  --argjson prefix "$preserve_prefix_count" '
                    [
                      range(0; 3) as $index
                      | if $index < $prefix
                        then $prior[$index]
                        else $fresh
                        end
                    ]
                  '
              )"
              renewal_performed=true
              renewal_prefix_count="$preserve_prefix_count"
            fi
          else
            test "$ROLLING_RESUME_RUN_ID" = "0"
            test "$renewal_authorization" = "NONE"
            test "$preserve_prefix_count" = "0"
            slot_epoch="$fresh_epoch"
            bootstrap_epochs="$(jq -cn --argjson epoch "$slot_epoch" '[$epoch,$epoch,$epoch]')"
          fi

          remaining="$((slot_epoch - now))"
          test "$remaining" -ge "$minimum_remaining"
          test "$remaining" -le "$maximum_remaining"
          test "$((slot_epoch % interval))" -eq 0
          jq -e '
            type == "array" and length == 3 and
            all(.[];
              type == "number" and
              floor == . and
              . > 0 and
              . % 30 == 0
            )
          ' <<<"$bootstrap_epochs" >/dev/null
          {
            echo "AUTOMATIC_FINALITY_ENABLED=true"
            echo "VALIDATOR_BLOCK_INTERVAL_SECONDS=$interval"
            echo "VALIDATOR_SLOT_EPOCH_SECONDS=$slot_epoch"
            echo "VALIDATOR_BOOTSTRAP_SLOT_EPOCHS_JSON=$bootstrap_epochs"
            echo "ROLLING_RESUME_PRIOR_SLOT_EPOCH_SECONDS=$prior_slot_epoch"
            echo "ROLLING_EPOCH_RENEWAL_PERFORMED=$renewal_performed"
            echo "ROLLING_EPOCH_RENEWAL_PREFIX_COUNT=$renewal_prefix_count"
          } >> "$GITHUB_ENV"
''',
                "renewable epoch generation",
            ),
        ],
    )

    foundation = root / "scripts/junca_public_testnet_foundation.sh"
    patch(
        foundation,
        [
            (
                '''  automatic_finality_enabled="${AUTOMATIC_FINALITY_ENABLED:-}"
  validator_block_interval_seconds="${VALIDATOR_BLOCK_INTERVAL_SECONDS:-}"
  validator_slot_epoch_seconds="${VALIDATOR_SLOT_EPOCH_SECONDS:-}"
  test "$automatic_finality_enabled" = "true"
  test "$validator_block_interval_seconds" = "30"
  [[ "$validator_slot_epoch_seconds" =~ ^[0-9]+$ ]]
  epoch_remaining="$((validator_slot_epoch_seconds - $(date +%s)))"
  test "$epoch_remaining" -ge 900
  test "$epoch_remaining" -le 7230
  test "$((validator_slot_epoch_seconds % 30))" -eq 0
''',
                '''  automatic_finality_enabled="${AUTOMATIC_FINALITY_ENABLED:-}"
  validator_block_interval_seconds="${VALIDATOR_BLOCK_INTERVAL_SECONDS:-}"
  validator_slot_epoch_seconds="${VALIDATOR_SLOT_EPOCH_SECONDS:-}"
  validator_bootstrap_slot_epochs_json="${
    VALIDATOR_BOOTSTRAP_SLOT_EPOCHS_JSON:-}"
  rolling_resume_prior_slot_epoch_seconds="${
    ROLLING_RESUME_PRIOR_SLOT_EPOCH_SECONDS:-0}"
  rolling_epoch_renewal_performed="${
    ROLLING_EPOCH_RENEWAL_PERFORMED:-false}"
  rolling_epoch_renewal_prefix_count="${
    ROLLING_EPOCH_RENEWAL_PREFIX_COUNT:-0}"
  test "$automatic_finality_enabled" = "true"
  test "$validator_block_interval_seconds" = "30"
  [[ "$validator_slot_epoch_seconds" =~ ^[0-9]+$ ]]
  [[ "$rolling_resume_prior_slot_epoch_seconds" =~ ^[0-9]+$ ]]
  [[ "$rolling_epoch_renewal_prefix_count" =~ ^[0-3]$ ]]
  case "$rolling_epoch_renewal_performed" in
    true|false) ;;
    *) echo "ROLLING_EPOCH_RENEWAL_PERFORMED must be true or false" >&2; exit 2 ;;
  esac
  jq -e '
    type == "array" and length == 3 and
    all(.[];
      type == "number" and
      floor == . and
      . > 0 and
      . % 30 == 0
    )
  ' <<<"$validator_bootstrap_slot_epochs_json" >/dev/null
  epoch_remaining="$((validator_slot_epoch_seconds - $(date +%s)))"
  test "$epoch_remaining" -ge 900
  test "$epoch_remaining" -le 7230
  test "$((validator_slot_epoch_seconds % 30))" -eq 0
''',
                "foundation renewal environment",
            ),
            (
                '''  --argjson validator_slot_epoch_seconds "$validator_slot_epoch_seconds" \
  --argjson availability_zones "$AVAILABILITY_ZONES_JSON" \
''',
                '''  --argjson validator_slot_epoch_seconds "$validator_slot_epoch_seconds" \
  --argjson validator_bootstrap_slot_epoch_seconds \
    "$validator_bootstrap_slot_epochs_json" \
  --argjson availability_zones "$AVAILABILITY_ZONES_JSON" \
''',
                "bootstrap tfvars argument",
            ),
            (
                '''    validator_slot_epoch_seconds: $validator_slot_epoch_seconds,
    enable_public_services: $enable_public_services,
''',
                '''    validator_slot_epoch_seconds: $validator_slot_epoch_seconds,
    validator_bootstrap_slot_epoch_seconds:
      $validator_bootstrap_slot_epoch_seconds,
    enable_public_services: $enable_public_services,
''',
                "bootstrap tfvars value",
            ),
            (
                '''      --argjson validator_slot_epoch_seconds \
        "$validator_slot_epoch_seconds" '
''',
                '''      --argjson validator_slot_epoch_seconds \
        "$validator_slot_epoch_seconds" \
      --argjson validator_bootstrap_slot_epochs \
        "$validator_bootstrap_slot_epochs_json" \
      --argjson rolling_resume_prior_slot_epoch_seconds \
        "$rolling_resume_prior_slot_epoch_seconds" \
      --argjson rolling_epoch_renewal_performed \
        "$rolling_epoch_renewal_performed" \
      --argjson rolling_epoch_renewal_prefix_count \
        "$rolling_epoch_renewal_prefix_count" '
''',
                "renewal resume jq arguments",
            ),
            (
                '''        .automatic_finality == {
          block_interval_seconds: $validator_block_interval_seconds,
          slot_epoch_seconds: $validator_slot_epoch_seconds,
          minimum_remaining_seconds: 900,
          maximum_remaining_seconds: 7230
        } and
''',
                '''        .automatic_finality.block_interval_seconds ==
          $validator_block_interval_seconds and
        .automatic_finality.slot_epoch_seconds ==
          $rolling_resume_prior_slot_epoch_seconds and
        .automatic_finality.minimum_remaining_seconds == 900 and
        .automatic_finality.maximum_remaining_seconds == 7230 and
        (
          (
            .terraform_bootstrap.slot_epoch_seconds //
            [
              .automatic_finality.slot_epoch_seconds,
              .automatic_finality.slot_epoch_seconds,
              .automatic_finality.slot_epoch_seconds
            ]
          ) as $prior_bootstrap
          | ($prior_bootstrap | type == "array" and length == 3) and
            (
              if $rolling_epoch_renewal_performed then
                $validator_slot_epoch_seconds >
                  $rolling_resume_prior_slot_epoch_seconds and
                $rolling_epoch_renewal_prefix_count >= .updated_count and
                $rolling_epoch_renewal_prefix_count <=
                  ([.updated_count + 1, 3] | min) and
                (
                  [
                    range(0; 3) as $index
                    | if $index < $rolling_epoch_renewal_prefix_count
                      then $validator_bootstrap_slot_epochs[$index] ==
                        $prior_bootstrap[$index]
                      else $validator_bootstrap_slot_epochs[$index] ==
                        $validator_slot_epoch_seconds
                      end
                  ] | all
                )
              else
                $validator_slot_epoch_seconds ==
                  $rolling_resume_prior_slot_epoch_seconds and
                $validator_bootstrap_slot_epochs == $prior_bootstrap and
                $rolling_epoch_renewal_prefix_count == 0
              end
            )
        ) and
''',
                "renewal resume evidence validation",
            ),
            (
                '''  evidence_bound_baseline_bindings="$(
    jq -ce '
      .baseline_bindings
      | select(
          length == 3 and
          [.[].validator_id] ==
            ["validator-01", "validator-02", "validator-03"] and
          all(.[]; .runtime_version | test("^[0-9a-f]{64}$")) and
          all(.[]; .instance_id | test("^i-[0-9a-f]{8,17}$"))
        )
    ' artifacts/live-prefix-decision.json
  )"

  # Stop automatic finality before the next replacement. The observed target
''',
                '''  evidence_bound_baseline_bindings="$(
    jq -ce '
      .baseline_bindings
      | select(
          length == 3 and
          [.[].validator_id] ==
            ["validator-01", "validator-02", "validator-03"] and
          all(.[]; .runtime_version | test("^[0-9a-f]{64}$")) and
          all(.[]; .instance_id | test("^i-[0-9a-f]{8,17}$"))
        )
    ' artifacts/live-prefix-decision.json
  )"
  if [[ "$rolling_epoch_renewal_performed" == "true" ]]; then
    test "$live_updated_count" = "$rolling_epoch_renewal_prefix_count"
  else
    test "$rolling_epoch_renewal_prefix_count" = "0"
  fi

  # Stop automatic finality before the next replacement. The observed target
''',
                "renewal live prefix binding",
            ),
            (
                '''    --argjson validator_slot_epoch_seconds \
      "$validator_slot_epoch_seconds" \
    --argjson updated_count "$updated_count" \
''',
                '''    --argjson validator_slot_epoch_seconds \
      "$validator_slot_epoch_seconds" \
    --argjson validator_bootstrap_slot_epochs \
      "$validator_bootstrap_slot_epochs_json" \
    --argjson rolling_resume_prior_slot_epoch_seconds \
      "$rolling_resume_prior_slot_epoch_seconds" \
    --argjson rolling_epoch_renewal_performed \
      "$rolling_epoch_renewal_performed" \
    --argjson rolling_epoch_renewal_prefix_count \
      "$rolling_epoch_renewal_prefix_count" \
    --argjson updated_count "$updated_count" \
''',
                "renewal resume writer arguments",
            ),
            (
                '''      automatic_finality: {
        block_interval_seconds: 30,
        slot_epoch_seconds: $validator_slot_epoch_seconds,
        minimum_remaining_seconds: 900,
        maximum_remaining_seconds: 7230
      },
      updated_count: $updated_count,
''',
                '''      automatic_finality: {
        block_interval_seconds: 30,
        slot_epoch_seconds: $validator_slot_epoch_seconds,
        minimum_remaining_seconds: 900,
        maximum_remaining_seconds: 7230
      },
      terraform_bootstrap: {
        slot_epoch_seconds: $validator_bootstrap_slot_epochs
      },
      epoch_renewal: {
        performed: $rolling_epoch_renewal_performed,
        prior_slot_epoch_seconds:
          $rolling_resume_prior_slot_epoch_seconds,
        preserved_target_prefix_count:
          $rolling_epoch_renewal_prefix_count
      },
      updated_count: $updated_count,
''',
                "renewal resume evidence fields",
            ),
        ],
    )

    compatibility = root / "jaios/social_ecosystem_chain/rolling_compatibility.py"
    patch(
        compatibility,
        [
            (
                '''        ".github/workflows/junca-validator-foundation-release.yml",
        ".github/workflows/junca-validator-public-testnet-orchestrator.yml",
        "config/junca_validator_ami_build_request.json",
''',
                '''        ".github/workflows/junca-validator-foundation-release.yml",
        ".github/workflows/junca-validator-public-testnet-orchestrator.yml",
        "config/junca_validator_ami_build_request.json",
        "infra/aws/public-testnet/main.tf",
        "infra/aws/public-testnet/outputs.tf",
        "infra/aws/public-testnet/variables.tf",
''',
                "recovery infrastructure allowlist",
            )
        ],
    )

    foundation_tests = (
        root / "tests/test_junca_social_ecosystem_chain_aws_foundation.py"
    )
    patch(
        foundation_tests,
        [
            (
                '''        self.assertIn(
            'can(regex("^ami-[0-9a-f]{8,17}$", var.node_ami_id))',
            self.runtime_variables,
        )

    def test_validator_roles_sign_only_with_their_assigned_key_but_verify_quorum(self) -> None:
''',
                '''        self.assertIn(
            'can(regex("^ami-[0-9a-f]{8,17}$", var.node_ami_id))',
            self.runtime_variables,
        )

    def test_bootstrap_epochs_are_separate_from_runtime_activation(self) -> None:
        self.assertIn(
            'variable "validator_bootstrap_slot_epoch_seconds"',
            self.runtime_variables,
        )
        self.assertIn(
            "local.validator_bootstrap_slot_epochs[count.index]",
            self.runtime,
        )
        self.assertIn(
            'output "validator_bootstrap_finality_readback"',
            self.runtime_outputs,
        )
        self.assertIn(
            "VALIDATOR_BOOTSTRAP_SLOT_EPOCHS_JSON",
            self.validator_foundation_release,
        )
        self.assertIn(
            "RENEW_EXPIRED_QUIESCED_EPOCH",
            self.validator_foundation_release,
        )
        self.assertIn(
            "validator_bootstrap_slot_epoch_seconds",
            self.foundation_script,
        )
        self.assertIn(
            "rolling_epoch_renewal_prefix_count",
            self.foundation_script,
        )
        self.assertIn("terraform_bootstrap:", self.foundation_script)
        self.assertIn("epoch_renewal:", self.foundation_script)
        self.assertIn("user_data_replace_on_change = true", self.runtime)

    def test_validator_roles_sign_only_with_their_assigned_key_but_verify_quorum(self) -> None:
''',
                "foundation bootstrap epoch tests",
            )
        ],
    )

    rolling_tests = root / "tests/test_junca_validator_rolling_compatibility.py"
    patch(
        rolling_tests,
        [
            (
                '''        value["comparison"].update(
            {
                "status": "identical",
''',
                '''        recovery_files = [
            ".github/workflows/junca-validator-foundation-release.yml",
            "infra/aws/public-testnet/main.tf",
            "infra/aws/public-testnet/outputs.tf",
            "infra/aws/public-testnet/variables.tf",
            "jaios/social_ecosystem_chain/rolling_compatibility.py",
            "scripts/junca_public_testnet_foundation.sh",
            "tests/test_junca_social_ecosystem_chain_aws_foundation.py",
            "tests/test_junca_validator_rolling_compatibility.py",
        ]
        value = self.recovery_head_evidence()
        value["comparison"]["files"] = [
            {
                "filename": filename,
                "status": "modified",
                "previous_filename": None,
            }
            for filename in recovery_files
        ]
        decision = evaluate_recovery_head_compare(value)
        self.assertEqual(decision["changed_files"], sorted(recovery_files))

        value["comparison"].update(
            {
                "status": "identical",
''',
                "recovery infrastructure positive test",
            ),
            (
                '''                        "filename": "infra/aws/public-testnet/main.tf",
''',
                '''                        "filename": "infra/aws/public-testnet/unsafe-new.tf",
''',
                "unexpected recovery file test",
            ),
        ],
    )

    for relative in (
        "infra/aws/public-testnet/variables.tf",
        "infra/aws/public-testnet/main.tf",
        "infra/aws/public-testnet/outputs.tf",
        ".github/workflows/junca-validator-foundation-release.yml",
        "scripts/junca_public_testnet_foundation.sh",
        "jaios/social_ecosystem_chain/rolling_compatibility.py",
        "tests/test_junca_social_ecosystem_chain_aws_foundation.py",
        "tests/test_junca_validator_rolling_compatibility.py",
    ):
        if not (root / relative).is_file():
            raise SystemExit(f"missing patched file: {relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

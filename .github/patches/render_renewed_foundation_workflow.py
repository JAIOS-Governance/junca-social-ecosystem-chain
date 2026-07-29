#!/usr/bin/env python3
"""Render the governed Foundation workflow with expired-epoch renewal inputs."""

from __future__ import annotations

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, observed {count}")
    return text.replace(old, new)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: render_renewed_foundation_workflow.py PATH")
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
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
        "renewal inputs",
    )
    text = replace_once(
        text,
        '''      ROLLING_RESUME_RUN_ID: ${{ inputs.resume_run_id }}
      FOUNDATION_ROLLING_RELEASE: "true"
''',
        '''      ROLLING_RESUME_RUN_ID: ${{ inputs.resume_run_id }}
      RENEW_EXPIRED_EPOCH: ${{ inputs.renew_expired_epoch }}
      RENEWAL_PRESERVE_PREFIX_COUNT: ${{ inputs.renewal_preserve_prefix_count }}
      FOUNDATION_ROLLING_RELEASE: "true"
''',
        "renewal environment",
    )
    text = replace_once(
        text,
        r'''      - name: Generate one-time shared automatic finality epoch
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
        r'''      - name: Generate or renew the shared automatic finality epoch
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
        "renewable epoch step",
    )
    path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
set -euo pipefail

# This entrypoint is intentionally a permanent fail-closed tombstone.
#
# Durable validator-state migration is a one-time Security Bootstrap
# operation.  It must never be reactivated from a repository workflow or by
# passing arbitrary shell content to an AWS-managed SSM document.  The
# reviewed historical evidence remains bound by its recorded digest; the
# executable controller that produced it is retired in Git history.
printf '%s\n' \
  'ERROR: validator-state migration controller is retired.' \
  'Use an approved, time-bounded non-OIDC Security Bootstrap procedure.' \
  'No AWS API call was attempted.' >&2
exit 64

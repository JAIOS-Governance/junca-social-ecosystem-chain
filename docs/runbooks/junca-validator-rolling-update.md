# JUNCA Public Testnet Validator Rolling Update

This runbook is limited to the three Public Testnet validators. It does not
authorize Terraform apply, deployment, Mainnet changes, asset movement, or
bridge activation.

1. Record the target runtime version, immutable artifact SHA-256, rollback
   version and rollback artifact SHA-256. Require a passed rollback rehearsal.
2. Read back all three validators. Automatic finality must be disabled on all
   nodes, fallback must be inactive, and at least two healthy validators must
   agree on the finalized head.
3. Update only the validator returned as `next_validator` by
   `evaluate_rolling_compatibility`. Re-read version, health and finalized head
   after every node. Never update out of order.
4. After all three report the exact target version and are healthy, require
   `READY_FOR_SLOT_EPOCH`. Set the same future canonical slot epoch on all three.
5. Read back the epoch from all three. Only
   `READY_FOR_FINALITY_ENABLE` permits enabling automatic finality.
6. Enable automatic finality consistently on all three and require `ACCEPTED`.

Any mixed finality state, quorum below two, finalized-head disagreement,
unexpected version, partial epoch configuration, active fallback, invalid
rollback evidence, or release-boundary drift stops the rollout. Rollback must
keep automatic finality disabled and use the recorded immutable previous
artifact; finalized state must never be rewound.

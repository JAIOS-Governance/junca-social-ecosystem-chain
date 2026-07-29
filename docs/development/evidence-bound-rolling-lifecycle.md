# Evidence-bound rolling lifecycle

This change carries each validator's observed runtime, AMI, instance, retained state volume, rollback snapshot and finality baseline through the complete Public Testnet serial replacement lifecycle.

The rollout remains fail-closed and one-validator-at-a-time. It does not authorize Mainnet activation, transaction submission, asset movement or bridge activation.

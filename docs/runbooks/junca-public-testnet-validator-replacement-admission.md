# Public Testnet Validator Replacement Admission

Status: **IMPLEMENTED LOCALLY — AWS ACTIVATION NOT YET PROVEN**

This implementation is part of Public Testnet development. It is not the
post-activation audit and it is not evidence that a validator was replaced.

## Development sequence

The immutable sequence is:

1. complete the recovery implementation;
2. activate Public Testnet and read back the live result;
3. perform the formal post-activation audit.

Pre-deployment tests, negative authorization checks, rollback design,
provenance checks, protected review, deployment admission, and live readback
remain development gates. They must not be mislabeled as the formal audit.

## Implemented boundary

`scripts/junca_validator_replacement_admission.py` validates:

- one exact Security Bootstrap manifest for
  `JuncaPTReplaceValidator`;
- the fixed Automation numeric version and content SHA-256;
- the exact Automation execution role, DynamoDB serialization lock, and
  evidence bucket;
- three ordered validator launch contracts with fixed subnet, Availability
  Zone, private IP, instance profile, security group, retained volume, KMS
  key, RPC/Explorer target groups, user-data digest, and launch-template
  digest;
- one exact-three live EC2 fleet readback;
- absence of a public IP and exact false constitutional safety tags;
- one bounded seven-parameter replacement request;
- a future 30-second-aligned activation epoch no more than one hour away; and
- a candidate AMI different from the selected validator's current AMI.

Only after all checks pass does it create the deterministic
`StartAutomationExecution` request for the fixed numeric document version.
The caller cannot provide an Automation role, subnet, private IP, security
group, profile, volume, target group, user data, KMS key, shell command, or
arbitrary document name.

The serialization lock key is global, rather than validator-specific. This is
intentional: no two validators may be replaced concurrently.

## Remaining activation work

The following are still required before Public Testnet can be declared live:

1. Security Bootstrap must create and read back the exact three immutable
   launch templates, the fixed Automation, its execution role, the global
   lock table, and the evidence destination.
2. The accepted manifest must bind their exact live IDs, numeric document
   version, and content digests.
3. An independently reviewed immutable AMI and release manifest must be
   accepted.
4. The fixed Automation must replace validators serially, preserving each
   retained state volume and rollback floor.
5. Live readback must prove height advancement above baseline `1`, peers
   exactly `2/2`, a fresh exact `3/3` certificate, Explorer/RPC parity,
   Runtime Acceptance, resident-control-plane heartbeat, and soak.

Repository tests or an `ACCEPTED_FOR_FIXED_AUTOMATION_START` decision do not
prove AWS deployment or Public Testnet recovery.

## Safety boundary

- Mainnet Changed: **false**
- Assets Moved: **false**
- Bridge Activated: **false**
- Mainnet Activation Authorized: **false**

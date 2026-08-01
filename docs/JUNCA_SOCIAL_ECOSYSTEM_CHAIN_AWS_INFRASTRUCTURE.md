# JUNCA Social Ecosystem Chain AWS Infrastructure

This Terraform package is a plan-mode, fail-closed AWS implementation for
`Public Testnet / Protocol Validation Environment` under `JAIOS Institutional Governance`.

The intended external boundary is XServer as registrar for
`jaios-governance.org`, with the registrar's NS records delegated to a
canonically verified Route53 public hosted zone. Terraform does not create or
guess the registrar account, AWS account, region, hosted zone, VPC, subnets,
images, genesis, binary, or signer resources.

Architecture:

- three private validators in three independently verified Availability Zones;
- loopback/private validator JSON-RPC and internal NLB for P2P;
- public ALB on HTTPS 443 only;
- two read-only RPC replicas with unsafe method denial;
- ACM DNS validation and Route53 aliases;
- regional WAF rate limit;
- finalized-index explorer and external health routes at the public boundary;
- CloudWatch log retention, disk, quorum, and RPC head-lag alarms;
- encrypted volumes, AWS Backup plan, snapshot and rollback boundary;
- KMS or CloudHSM-backed external signer resource references only.

Global Accelerator is intentionally omitted from the initial regional public
testnet boundary. It adds no validator security and must not be introduced
until a multi-region acceptance and cost decision is approved.

## Stop conditions

Keep `deployment_enabled=false` until all of the following are independently
read back: AWS account and region, billing/organization authorization, VPC and
three-AZ topology, Route53 zone and external registrar NS delegation, KMS/HSM
resources and permissions, immutable AMI/container/binary/genesis digests,
DNS/TLS, validator quorum, unsafe-RPC rejection, runtime acceptance, and
rollback acceptance.

No resource is created while the switch is false. Mainnet, assets, and bridge
activation remain false.

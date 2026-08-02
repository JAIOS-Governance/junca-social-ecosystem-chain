# JUNCA Chain CloudFormation Self Reconcile

Run ID: 30752975231
Commit: 3d945efb834676c86007964775114543362ef3be
Identity RC: 0
Describe RC: 0
Update RC: 255
Inline policy read RC: 0
Attached policy read RC: 0
Stack status: UPDATE_ROLLBACK_COMPLETE

## Inline policies
- JuncaChainProductionRecovery
- JuncaPointMemberOtpRelayDeployment
- PublishExactTechnicalReferenceArtifact

## Attached policies

## Stack failure events

## Log
```text
{
    "UserId": "AROAYVMY5RBKAUCOXGDPN:chain-cfn-reconcile-30752975231",
    "Account": "595710543956",
    "Arn": "arn:aws:sts::595710543956:assumed-role/JuncaChainDocsProductionDeployment/chain-cfn-reconcile-30752975231"
}

aws: [ERROR]: Waiter StackUpdateComplete failed: Waiter encountered a terminal failure state: For expression "Stacks[].StackStatus" we matched expected path: "UPDATE_ROLLBACK_COMPLETE" at least once
```

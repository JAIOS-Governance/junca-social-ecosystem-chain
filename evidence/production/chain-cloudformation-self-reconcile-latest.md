# JUNCA Chain CloudFormation Self Reconcile

Run ID: 30752665566
Commit: 7555a0cbd3b9768354a67d9c38c0a1857219baa8
Identity RC: 0
Describe RC: 0
Update RC: 255
Inline policy read RC: 0
Attached policy read RC: 0
Stack status: CREATE_COMPLETE

## Inline policies
- JuncaChainProductionRecovery
- JuncaPointMemberOtpRelayDeployment
- PublishExactTechnicalReferenceArtifact

## Attached policies

## Log
```text
{
    "UserId": "AROAYVMY5RBKAUCOXGDPN:chain-cfn-reconcile-30752665566",
    "Account": "595710543956",
    "Arn": "arn:aws:sts::595710543956:assumed-role/JuncaChainDocsProductionDeployment/chain-cfn-reconcile-30752665566"
}

aws: [ERROR]: Waiter StackUpdateComplete failed: Waiter encountered a terminal failure state: For expression "Stacks[].StackStatus" we matched expected path: "UPDATE_ROLLBACK_COMPLETE" at least once
```

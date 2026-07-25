# JUNCA Chain CloudFormation Self Reconcile

Run ID: 30169342696
Commit: ca9b04bdb6078765e3639b9080d1778496e6a874
Identity RC: 0
Describe RC: 254
Update RC: 99
Inline policy read RC: 254
Attached policy read RC: 254

## Inline policies

## Attached policies

## Log
```text
{
    "UserId": "AROAYVMY5RBKAUCOXGDPN:chain-cfn-reconcile-30169342696",
    "Account": "595710543956",
    "Arn": "arn:aws:sts::595710543956:assumed-role/JuncaChainDocsProductionDeployment/chain-cfn-reconcile-30169342696"
}

aws: [ERROR]: An error occurred (AccessDenied) when calling the DescribeStacks operation: User: arn:aws:sts::595710543956:assumed-role/JuncaChainDocsProductionDeployment/chain-cfn-reconcile-30169342696 is not authorized to perform: cloudformation:DescribeStacks on resource: arn:aws:cloudformation:us-east-1:595710543956:stack/junca-chain-docs-publication/0b05dfd0-876f-11f1-963c-0e97a2fa656f because no identity-based policy allows the cloudformation:DescribeStacks action

aws: [ERROR]: An error occurred (AccessDenied) when calling the ListRolePolicies operation: User: arn:aws:sts::595710543956:assumed-role/JuncaChainDocsProductionDeployment/chain-cfn-reconcile-30169342696 is not authorized to perform: iam:ListRolePolicies on resource: role JuncaChainDocsProductionDeployment because no identity-based policy allows the iam:ListRolePolicies action

aws: [ERROR]: An error occurred (AccessDenied) when calling the ListAttachedRolePolicies operation: User: arn:aws:sts::595710543956:assumed-role/JuncaChainDocsProductionDeployment/chain-cfn-reconcile-30169342696 is not authorized to perform: iam:ListAttachedRolePolicies on resource: role JuncaChainDocsProductionDeployment because no identity-based policy allows the iam:ListAttachedRolePolicies action
```

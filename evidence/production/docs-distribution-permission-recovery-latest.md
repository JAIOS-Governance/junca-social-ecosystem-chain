# Docs Distribution Permission Recovery

Run ID: 30756216191
Commit: 4ee162fc2e9caebfc02c9676fd8c3a94556e2a7c
Target role: arn:aws:iam::595710543956:role/JuncaChainDocsProductionDeployment
Policy: DocsLiveProxyDistributionUpdate
Action: cloudfront:UpdateDistribution
Resource: arn:aws:cloudfront::595710543956:distribution/E22CXYZGWNT0AJ
Verification: PASS
Stack:  ->  (rc=0)

## Execution log
~~~text
Trying bootstrap identity: arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment
true

aws: [ERROR]: An error occurred (AccessDenied) when calling the DescribeStacks operation: User: arn:aws:sts::595710543956:assumed-role/JuncaChainPublicTestnetDeployment/docs-distribution-permission-30756216191 is not authorized to perform: cloudformation:DescribeStacks on resource: arn:aws:cloudformation:us-east-1:595710543956:stack/junca-chain-docs-publication/0b05dfd0-876f-11f1-963c-0e97a2fa656f because no identity-based policy allows the cloudformation:DescribeStacks action
Selected bootstrap identity: arn:aws:iam::595710543956:role/JuncaChainPublicTestnetDeployment
PutRolePolicy return code: 0
GetRolePolicy return code: 0
Exact policy verification return code: 0
~~~

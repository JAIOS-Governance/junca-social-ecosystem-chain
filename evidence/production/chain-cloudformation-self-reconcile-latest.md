# JUNCA Chain CloudFormation Self Reconcile

Run ID: 30753610349
Commit: 7a782ead608d917995ed7fb9ccf7c5763d9648a3
Identity RC: 0
Describe RC: 0
OAC readback RC: 0
Distribution ID: E22CXYZGWNT0AJ
Origin Access Control ID: E1FWMEHWY4J38G
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
- [2026-08-02T15:07:07.913000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_COMPLETE · no reason
- [2026-08-02T15:07:07.128000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS · no reason
- [2026-08-02T15:07:04.187000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_IN_PROGRESS · The following resource(s) failed to update: [DocsDistribution]. 
- [2026-08-02T15:07:03.710000+00:00] DocsDistribution · UPDATE_FAILED · Unable to retrieve FunctionARN attribute for AWS::CloudFront::Function, with error message Access denied for operation 'AWS::CloudFront::Function: User: arn:aws:sts::595710543956:assumed-role/JuncaChainDocsProductionDeployment/chain-cfn-reconcile-30753610349 is not authorized to perform: cloudfront:GetFunction on resource: arn:aws:cloudfront::595710543956:function/junca-chain-docs-routes-595710543956 because no identity-based policy allows the cloudfront:GetFunction action (Service: CloudFront, Status Code: 403, Request ID: c844733d-693e-4e9c-8473-5e857c899da6) (SDK Attempt Count: 1)'.
- [2026-08-02T15:02:18.415000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_COMPLETE · no reason
- [2026-08-02T15:02:17.635000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS · no reason
- [2026-08-02T15:02:14.362000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_IN_PROGRESS · The following resource(s) failed to update: [DocsDistribution]. 
- [2026-08-02T15:02:13.860000+00:00] DocsDistribution · UPDATE_FAILED · Unable to retrieve Id attribute for AWS::CloudFront::OriginAccessControl, with error message Access denied for operation 'AWS::CloudFront::OriginAccessControl'.
- [2026-08-02T14:55:48.267000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_COMPLETE · no reason
- [2026-08-02T14:55:47.477000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS · no reason
- [2026-08-02T14:55:44.114000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_IN_PROGRESS · The following resource(s) failed to update: [DocsSecurityHeaders, DocsBucket]. 
- [2026-08-02T14:55:43.568000+00:00] DocsBucket · UPDATE_FAILED · Resource update cancelled
- [2026-08-02T14:55:43.397000+00:00] DocsSecurityHeaders · UPDATE_FAILED · Resource handler returned message: "Access denied for operation 'AWS::CloudFront::ResponseHeadersPolicy'." (RequestToken: f1a7edf8-460e-bbae-c764-f0c7605acf48, HandlerErrorCode: AccessDenied)
- [2026-08-02T14:50:15.387000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_COMPLETE · no reason
- [2026-08-02T14:50:14.584000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS · no reason
- [2026-08-02T14:50:11.137000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_IN_PROGRESS · The following resource(s) failed to update: [DocsSecurityHeaders, DocsBucket]. 
- [2026-08-02T14:50:10.664000+00:00] DocsBucket · UPDATE_FAILED · Resource update cancelled
- [2026-08-02T14:50:10.350000+00:00] DocsSecurityHeaders · UPDATE_FAILED · Resource handler returned message: "Access denied for operation 'AWS::CloudFront::ResponseHeadersPolicy'." (RequestToken: 528f0dcf-bf5f-1474-6c10-d6ac57d3028d, HandlerErrorCode: AccessDenied)
- [2026-08-02T14:41:54.229000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_COMPLETE · no reason
- [2026-08-02T14:41:53.480000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS · no reason
- [2026-08-02T14:41:49.841000+00:00] junca-chain-docs-publication · UPDATE_ROLLBACK_IN_PROGRESS · The following resource(s) failed to update: [DocsSecurityHeaders, DocsBucket]. 
- [2026-08-02T14:41:49.533000+00:00] DocsBucket · UPDATE_FAILED · Resource update cancelled
- [2026-08-02T14:41:48.989000+00:00] DocsSecurityHeaders · UPDATE_FAILED · Resource handler returned message: "Access denied for operation 'AWS::CloudFront::ResponseHeadersPolicy'." (RequestToken: b18b5e6e-2a58-5b6b-573c-89561063b7d2, HandlerErrorCode: AccessDenied)

## Log
```text
{
    "UserId": "AROAYVMY5RBKAUCOXGDPN:chain-cfn-reconcile-30753610349",
    "Account": "595710543956",
    "Arn": "arn:aws:sts::595710543956:assumed-role/JuncaChainDocsProductionDeployment/chain-cfn-reconcile-30753610349"
}

aws: [ERROR]: Waiter StackUpdateComplete failed: Waiter encountered a terminal failure state: For expression "Stacks[].StackStatus" we matched expected path: "UPDATE_ROLLBACK_COMPLETE" at least once
```

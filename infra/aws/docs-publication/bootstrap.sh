#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-readback}"
DOMAIN_NAME="docs.jaios-governance.org"
ZONE_NAME="jaios-governance.org"
REPOSITORY="JAIOS-Governance/junca-social-ecosystem-chain"
ENVIRONMENT_NAME="junca-chain-docs-production"
STACK_NAME="junca-chain-docs-publication"
REGION="us-east-1"
TEMPLATE_FILE="${TEMPLATE_FILE:-infra/aws/docs-publication/main.yaml}"
EVIDENCE_DIR="${EVIDENCE_DIR:-aws-publication-evidence}"

case "${MODE}" in
  readback|prepare-zone|deploy) ;;
  *)
    echo "usage: $0 [readback|prepare-zone|deploy]" >&2
    exit 2
    ;;
esac

command -v aws >/dev/null
mkdir -p "${EVIDENCE_DIR}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
identity_file="${EVIDENCE_DIR}/${timestamp}-caller-identity.json"
aliases_file="${EVIDENCE_DIR}/${timestamp}-account-aliases.json"
oidc_file="${EVIDENCE_DIR}/${timestamp}-oidc-providers.json"
zones_file="${EVIDENCE_DIR}/${timestamp}-hosted-zones.json"

aws sts get-caller-identity --output json | tee "${identity_file}"
account_id="$(aws sts get-caller-identity --query Account --output text)"
caller_arn="$(aws sts get-caller-identity --query Arn --output text)"
test -n "${account_id}" && test "${account_id}" != "None"
test -n "${caller_arn}" && test "${caller_arn}" != "None"

aws iam list-account-aliases --output json | tee "${aliases_file}"
aws iam list-open-id-connect-providers --output json | tee "${oidc_file}"
aws route53 list-hosted-zones-by-name --dns-name "${ZONE_NAME}" --output json | tee "${zones_file}"

organization_id="$(
  aws organizations describe-organization \
    --query Organization.Id --output text 2>"${EVIDENCE_DIR}/${timestamp}-organization.err" || true
)"
if [[ -z "${organization_id}" || "${organization_id}" == "None" ]]; then
  if grep -Fq "AWSOrganizationsNotInUseException" "${EVIDENCE_DIR}/${timestamp}-organization.err"; then
    organization_id="NOT_IN_USE"
  else
    cat "${EVIDENCE_DIR}/${timestamp}-organization.err" >&2
    exit 1
  fi
fi

oidc_arn=""
while IFS= read -r provider_arn; do
  [[ -n "${provider_arn}" ]] || continue
  provider_url="$(aws iam get-open-id-connect-provider \
    --open-id-connect-provider-arn "${provider_arn}" \
    --query Url --output text)"
  if [[ "${provider_url}" == "token.actions.githubusercontent.com" ]]; then
    oidc_arn="${provider_arn}"
    break
  fi
done < <(aws iam list-open-id-connect-providers \
  --query 'OpenIDConnectProviderList[].Arn' --output text | tr '\t' '\n')

hosted_zone_id="$(
  aws route53 list-hosted-zones-by-name \
    --dns-name "${ZONE_NAME}" \
    --query "HostedZones[?Name=='${ZONE_NAME}.'] | [0].Id" \
    --output text
)"

if [[ -z "${hosted_zone_id}" || "${hosted_zone_id}" == "None" ]]; then
  if [[ "${MODE}" == "prepare-zone" || "${MODE}" == "deploy" ]]; then
    caller_reference="junca-chain-docs-${timestamp}"
    hosted_zone_id="$(
      aws route53 create-hosted-zone \
        --name "${ZONE_NAME}" \
        --caller-reference "${caller_reference}" \
        --hosted-zone-config \
          "Comment=JUNCA Chain official publication zone,PrivateZone=false" \
        --query 'HostedZone.Id' --output text
    )"
  else
    echo "Route 53 hosted zone is not present. Run prepare-zone before deploy." >&2
    exit 3
  fi
fi

hosted_zone_id="${hosted_zone_id#/hostedzone/}"
records_file="${EVIDENCE_DIR}/${timestamp}-route53-records.json"
aws route53 list-resource-record-sets \
  --hosted-zone-id "${hosted_zone_id}" \
  --output json | tee "${records_file}"

ns_file="${EVIDENCE_DIR}/${timestamp}-route53-nameservers.txt"
aws route53 get-hosted-zone \
  --id "${hosted_zone_id}" \
  --query 'DelegationSet.NameServers' \
  --output text | tr '\t' '\n' | tee "${ns_file}"

{
  echo "Account ID: ${account_id}"
  echo "Caller ARN: ${caller_arn}"
  echo "Organization ID: ${organization_id}"
  echo "Hosted Zone ID: ${hosted_zone_id}"
  echo "GitHub OIDC Provider ARN: ${oidc_arn:-NOT_PRESENT}"
  echo "Nameserver evidence: ${ns_file}"
  echo "Record inventory: ${records_file}"
} | tee "${EVIDENCE_DIR}/${timestamp}-readback-summary.txt"

if [[ "${MODE}" == "readback" || "${MODE}" == "prepare-zone" ]]; then
  exit 0
fi

public_ns_file="${EVIDENCE_DIR}/${timestamp}-public-nameservers.txt"
if command -v dig >/dev/null; then
  dig +short NS "${ZONE_NAME}" |
    sed 's/\.$//' | sort -u | tee "${public_ns_file}"
elif command -v curl >/dev/null && command -v python3 >/dev/null; then
  curl --fail --silent --show-error \
    --get \
    --header 'accept: application/dns-json' \
    --data-urlencode "name=${ZONE_NAME}" \
    --data-urlencode 'type=NS' \
    https://cloudflare-dns.com/dns-query |
    python3 -c '
import json
import sys

response = json.load(sys.stdin)
answers = response.get("Answer", [])
nameservers = sorted({
    answer["data"].rstrip(".")
    for answer in answers
    if answer.get("type") == 2 and answer.get("data")
})
for nameserver in nameservers:
    print(nameserver)
' | tee "${public_ns_file}"
else
  echo "DNS_READBACK_UNAVAILABLE: install dig or provide curl and python3." >&2
  exit 5
fi

if [[ ! -s "${public_ns_file}" ]]; then
  echo "DNS_DELEGATION_PENDING: no public NS answer is available yet." >&2
  exit 4
fi

sed 's/\.$//' "${ns_file}" | sort -u >"${EVIDENCE_DIR}/${timestamp}-route53-nameservers.sorted"
if ! diff -u \
  "${EVIDENCE_DIR}/${timestamp}-route53-nameservers.sorted" \
  "${public_ns_file}"; then
  echo "DNS_DELEGATION_PENDING: public nameservers do not match Route 53." >&2
  echo "Complete registrar delegation before running deploy again." >&2
  exit 4
fi

test -f "${TEMPLATE_FILE}"

aws cloudformation validate-template \
  --region "${REGION}" \
  --template-body "file://${TEMPLATE_FILE}" >/dev/null

aws cloudformation deploy \
  --region "${REGION}" \
  --stack-name "${STACK_NAME}" \
  --template-file "${TEMPLATE_FILE}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    "DomainName=${DOMAIN_NAME}" \
    "HostedZoneId=${hosted_zone_id}" \
    "Repository=${REPOSITORY}" \
    "EnvironmentName=${ENVIRONMENT_NAME}" \
    "ExistingGitHubOidcProviderArn=${oidc_arn}"

aws cloudformation wait stack-create-complete \
  --region "${REGION}" \
  --stack-name "${STACK_NAME}" 2>/dev/null || \
aws cloudformation wait stack-update-complete \
  --region "${REGION}" \
  --stack-name "${STACK_NAME}"

outputs_file="${EVIDENCE_DIR}/${timestamp}-stack-outputs.json"
aws cloudformation describe-stacks \
  --region "${REGION}" \
  --stack-name "${STACK_NAME}" \
  --query 'Stacks[0].Outputs' \
  --output json | tee "${outputs_file}"

role_arn="$(
  aws cloudformation describe-stacks \
    --region "${REGION}" \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='DeploymentRoleArn'].OutputValue | [0]" \
    --output text
)"
test -n "${role_arn}" && test "${role_arn}" != "None"

if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  gh variable set AWS_DOCS_DEPLOYMENT_ROLE_ARN \
    --repo "${REPOSITORY}" \
    --env "${ENVIRONMENT_NAME}" \
    --body "${role_arn}"
  gh workflow run junca-chain-docs-production.yml \
    --repo "${REPOSITORY}" \
    --ref main \
    -f deploy=true
else
  echo "GitHub environment binding remains: AWS_DOCS_DEPLOYMENT_ROLE_ARN=${role_arn}"
  echo "Workflow URL: https://github.com/${REPOSITORY}/actions/workflows/junca-chain-docs-production.yml"
fi

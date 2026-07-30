#!/usr/bin/env python3
"""Fail-closed static contract for the six fixed Public Testnet SSM documents."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised in a fresh-runner subprocess
    yaml = None  # type: ignore[assignment]


class ContractError(ValueError):
    """Raised when a repository or invocation violates the fixed contract."""


SHA256_PATTERN = r"^[0-9a-f]{64}$"
VALIDATOR_ID_PATTERN = r"^validator-0[1-3]$"
BOOLEAN_PATTERN = r"^(true|false)$"
INTERVAL_PATTERN = r"^(0|30)$"
EPOCH_PATTERN = r"^(0|[1-9][0-9]{0,10})$"
MODE_PATTERN = r"^(preflight|exact)$"
HEALTH_ENDPOINT = "http://127.0.0.1:8545/health"
MAX_FINALITY_EPOCH_HORIZON_SECONDS = 60

DOCUMENT_SPECS: dict[str, dict[str, Any]] = {
    "JuncaPTBootstrapReadiness": {
        "access_class": "read-only",
        "parameters": {
            "ValidatorId": VALIDATOR_ID_PATTERN,
            "ExpectedArtifactSha256": SHA256_PATTERN,
            "ExpectedGenesisSha256": SHA256_PATTERN,
        },
        "required_fragments": (
            "#!/usr/bin/bash",
            'exec /usr/bin/bash "$0" "$@"',
            "readonly RUNTIME_ENV=/etc/junca/runtime.env",
            "readonly RUNTIME_ARCHIVE=/opt/junca/validator-runtime.tar.gz",
            "readonly GENESIS_FILE=/etc/junca/genesis.json",
            "readonly SUPPLY_CHAIN_EVIDENCE=/opt/junca/ami-supply-chain.env",
            "readonly STATE_DATABASE=/var/lib/junca/state.sqlite",
            "/usr/bin/cloud-init status --wait",
            "/usr/bin/mountpoint -q",
            "/usr/bin/sqlite3 -batch -noheader -readonly",
            "PRAGMA query_only=ON; PRAGMA quick_check;",
            "JOIN finality_certificates AS f",
            ".consensus.last_certificate == $durable.certificate",
            "certificate_digest_matches",
            ".peer_count == 2",
            'status: "READY"',
        ),
    },
    "JuncaPTFinalityInspect": {
        "access_class": "read-only",
        "parameters": {
            "ExpectedArtifactSha256": SHA256_PATTERN,
            "Enabled": BOOLEAN_PATTERN,
            "BlockIntervalSeconds": INTERVAL_PATTERN,
            "SlotEpochSeconds": EPOCH_PATTERN,
            "Mode": MODE_PATTERN,
            "AllowMissingFinalityKeys": BOOLEAN_PATTERN,
        },
        "required_fragments": (
            "#!/usr/bin/bash",
            'exec /usr/bin/bash "$0" "$@"',
            "readonly RUNTIME_ENV=/etc/junca/runtime.env",
            "readonly RUNTIME_ARCHIVE=/opt/junca/validator-runtime.tar.gz",
            'test "$mode" = preflight',
            'if [[ "$mode" == exact ]]',
            'if [[ "$mode" == preflight ]]',
            'test "$slot_epoch" -le "$((request_now_epoch + 60))"',
            "finality_keys_present=false",
            "runtime_env_sha256=",
            "certificate_digest_matches",
            ".peer_count == 2",
            'access_class: "read-only"',
        ),
    },
    "JuncaPTFinalitySet": {
        "access_class": "mutating",
        "parameters": {
            "ExpectedArtifactSha256": SHA256_PATTERN,
            "Enabled": BOOLEAN_PATTERN,
            "BlockIntervalSeconds": INTERVAL_PATTERN,
            "SlotEpochSeconds": EPOCH_PATTERN,
        },
        "required_fragments": (
            "#!/usr/bin/bash",
            'exec /usr/bin/bash "$0" "$@"',
            "readonly RUNTIME_ENV=/etc/junca/runtime.env",
            "readonly RUNTIME_ARCHIVE=/opt/junca/validator-runtime.tar.gz",
            "before_non_finality_sha256=",
            "readonly RUNTIME_BACKUP=/etc/junca/.runtime.env.rollback",
            "readonly RUNTIME_CANDIDATE=/etc/junca/.runtime.env.candidate",
            "readonly RUNTIME_RECOVERY=/etc/junca/.runtime.env.recovery",
            "readonly TRANSACTION_MARKER=/etc/junca/.runtime.env.transaction.json",
            "readonly TRANSACTION_MARKER_NEXT=/etc/junca/.runtime.env.transaction.next",
            'stat -c \'%U:%G:%a\' "$JUNCA_DIRECTORY"',
            ")\" = root:root:750",
            "readonly MUTATION_LOCK_DIRECTORY=/run/lock/junca-validator-mutation",
            'exec 9<"$MUTATION_LOCK_DIRECTORY"',
            "/usr/bin/flock --exclusive --nonblock 9",
            '"operational_decision":"BLOCKED_CONCURRENT_MUTATION"',
            "/usr/bin/cp --preserve=mode,ownership --no-dereference",
            "/usr/bin/mv -f --",
            '/usr/bin/sync -f "$JUNCA_DIRECTORY"',
            "write_transaction_marker PREPARED",
            "mutation_in_progress=true",
            "write_transaction_marker ACCEPTED",
            "recover_prepared_transaction()",
            "verify_accepted_transaction()",
            '.state == "PREPARED"',
            ".peer_count == 2",
            "certificate_digest_matches",
            "post_mutation_progress_matches()",
            'test "$slot_epoch" -le "$((request_now_epoch + 60))"',
            'test "$last_health_head_height" -gt',
            '"$pre_mutation_head_height"',
            'test "$last_health_head_timestamp" -ge "$slot_epoch"',
            'test "$last_health_certificate_hash" !=',
            '"$pre_mutation_certificate_hash"',
            "/usr/bin/systemctl restart",
            "/usr/bin/timeout --signal=TERM --kill-after=10 30",
            "for attempt in {1..60}; do",
            "/usr/bin/sleep 2",
            "failure_guard()",
            '"operational_decision":"BLOCKED_MANUAL_SECURITY_BOOTSTRAP_RECOVERY"',
            'access_class: "mutating"',
        ),
    },
    "JuncaPTHealthReadback": {
        "access_class": "read-only",
        "parameters": {},
        "required_fragments": (
            "#!/usr/bin/bash",
            'exec /usr/bin/bash "$0" "$@"',
            f"readonly HEALTH_ENDPOINT={HEALTH_ENDPOINT}",
            "/usr/bin/curl --fail --silent --show-error --noproxy '*'",
            "--proto '=http' --connect-timeout 2 --max-time 5",
            'error("health readback contract rejected")',
            "certificate_digest_matches",
            ".peer_count == 2",
            'schema_version: "junca-pt-health-readback/v1"',
            "last_certificate:",
            'bounded_json "$health"',
        ),
    },
    "JuncaPTRestartHealth": {
        "access_class": "mutating",
        "parameters": {},
        "required_fragments": (
            "#!/usr/bin/bash",
            'exec /usr/bin/bash "$0" "$@"',
            "readonly VALIDATOR_SERVICE=junca-validator.service",
            "readonly MUTATION_LOCK_DIRECTORY=/run/lock/junca-validator-mutation",
            'exec 9<"$MUTATION_LOCK_DIRECTORY"',
            "/usr/bin/flock --exclusive --nonblock 9",
            '"operational_decision":"BLOCKED_CONCURRENT_MUTATION"',
            "/usr/bin/systemctl restart",
            "/usr/bin/timeout --signal=TERM --kill-after=10 30",
            "for attempt in {1..60}; do",
            "/usr/bin/sleep 2",
            "--no-pager --lines=100 --output=json",
            "--output-fields=__REALTIME_TIMESTAMP,PRIORITY,_SYSTEMD_UNIT",
            "journal_message_included: false",
            "journal_metadata:",
            "certificate_digest_matches",
            ".peer_count == 2",
            'access_class: "mutating"',
        ),
    },
    "JuncaPTRuntimeObservation": {
        "access_class": "read-only",
        "parameters": {"ValidatorId": VALIDATOR_ID_PATTERN},
        "required_fragments": (
            "#!/usr/bin/bash",
            'exec /usr/bin/bash "$0" "$@"',
            "readonly RUNTIME_ENV=/etc/junca/runtime.env",
            "readonly RUNTIME_ARCHIVE=/opt/junca/validator-runtime.tar.gz",
            "readonly GENESIS_FILE=/etc/junca/genesis.json",
            "readonly SUPPLY_CHAIN_EVIDENCE=/opt/junca/ami-supply-chain.env",
            "readonly STATE_DATABASE=/var/lib/junca/state.sqlite",
            "/usr/bin/sqlite3 -batch -noheader -readonly",
            "PRAGMA query_only=ON; PRAGMA quick_check;",
            ".consensus.last_certificate == $durable.certificate",
            "certificate_digest_matches",
            ".peer_count == 2",
            "finality_readback:",
            "durable_certificate_hash:",
            'access_class: "read-only"',
        ),
    },
}

EXPECTED_STEP_NAMES = {
    "JuncaPTBootstrapReadiness": "inspectBootstrapReadiness",
    "JuncaPTFinalityInspect": "inspectFinality",
    "JuncaPTFinalitySet": "setFinality",
    "JuncaPTHealthReadback": "readHealth",
    "JuncaPTRestartHealth": "restartValidatorHealth",
    "JuncaPTRuntimeObservation": "observeRuntime",
}

CANONICAL_DOCUMENT_SHA256 = {
    "JuncaPTBootstrapReadiness":
        "ef87219701d9c3310f8b8745b769ba8d6466e3b299e9503189d5599e7791c866",
    "JuncaPTFinalityInspect":
        "63f6e9ff96141015ca1fa8a4d746b0d67b9a9fe151ce60024f9756f0f5772383",
    "JuncaPTFinalitySet":
        "59589512a5d4c12c80a094117286775723e2ed7261f5bf06c41719baa445e7ab",
    "JuncaPTHealthReadback":
        "f30e679eca076b1a26ee4df958f400a402fe2ad4b78e27efbb8c319bb8682b5a",
    "JuncaPTRestartHealth":
        "d3b83a24cd40b18fb3e0dbe4a00d4f84107e52dacff4e3ccadb93954a13733ca",
    "JuncaPTRuntimeObservation":
        "c754bb26f3e7e1dd63e24c595cacb088403dcf8540dbb0f7a66cfe7c84c89f7f",
}

CANONICAL_SHELL_SHA256 = {
    "JuncaPTBootstrapReadiness":
        "b92dd638cf357cb75ed5920d74226987b137bb77d7d475a9d3061cd883054e44",
    "JuncaPTFinalityInspect":
        "70efaf76ab75609c55ef6fff52e5500ddebeebf87fb6b33bf2075962713e9ad7",
    "JuncaPTFinalitySet":
        "0988401ba4d29945c1239fbd7a61e2bd70e0524b7984adf8bb4c4eb44a004ada",
    "JuncaPTHealthReadback":
        "ff1180ead7b0698b25289cc2b338bfa21d43b9130b8415930b31da55f6924574",
    "JuncaPTRestartHealth":
        "e8e45466100282ea733b3d78c27810c16e43a9faaf68c3e38953892426f527cc",
    "JuncaPTRuntimeObservation":
        "cde16dd0127c325cfb764524b66134bae61f50587b0635f896098f29a7fc4db4",
}

EXECUTABLE_ALLOWLISTS = {
    "JuncaPTBootstrapReadiness": {
        "awk",
        "bash",
        "cloud-init",
        "curl",
        "jq",
        "mountpoint",
        "sha256sum",
        "sqlite3",
        "stat",
        "systemctl",
        "timeout",
        "wc",
    },
    "JuncaPTFinalityInspect": {
        "awk",
        "bash",
        "curl",
        "date",
        "jq",
        "sha256sum",
        "systemctl",
        "timeout",
        "wc",
    },
    "JuncaPTFinalitySet": {
        "awk",
        "bash",
        "chmod",
        "cp",
        "curl",
        "date",
        "flock",
        "jq",
        "mv",
        "rm",
        "sed",
        "sha256sum",
        "sleep",
        "stat",
        "sync",
        "systemctl",
        "tail",
        "timeout",
        "wc",
    },
    "JuncaPTHealthReadback": {
        "awk",
        "bash",
        "curl",
        "jq",
        "sha256sum",
        "wc",
    },
    "JuncaPTRestartHealth": {
        "awk",
        "bash",
        "curl",
        "flock",
        "journalctl",
        "jq",
        "sleep",
        "sha256sum",
        "stat",
        "systemctl",
        "timeout",
        "wc",
    },
    "JuncaPTRuntimeObservation": {
        "awk",
        "bash",
        "curl",
        "jq",
        "mountpoint",
        "sha256sum",
        "sqlite3",
        "stat",
        "systemctl",
        "timeout",
        "wc",
    },
}

MANIFEST_KEYS = {
    "schema_version",
    "status",
    "operational_decision",
    "owner_principal",
    "account_id",
    "region",
    "document_type",
    "schema_version_ssm",
    "runtime_lock_contract",
    "documents",
    "required_runtime_binaries",
    "live_acceptance_missing",
    "not_implemented_by_this_manifest",
    "mainnet_changed",
    "assets_moved",
    "bridge_activated",
    "transaction_submission_enabled",
}

MANIFEST_DOCUMENT_KEYS = {
    "name",
    "file",
    "access_class",
    "parameters",
    "repository_sha256",
    "accepted_live_document_version",
    "accepted_live_content_sha256",
    "live_readback_present",
}

BANNED_PARAMETER_NAMES = {
    "command",
    "commands",
    "script",
    "scripts",
    "path",
    "paths",
    "url",
    "urls",
    "service",
    "services",
    "unit",
    "units",
    "instanceid",
    "instanceids",
    "target",
    "targets",
    "shell",
    "userdata",
}

BANNED_SCRIPT_PATTERNS = (
    (re.compile(r"(?i)\bpython(?:2|3)?\b"), "Python execution/source is prohibited"),
    (re.compile(r"(?m)^\s*[^#\n]*<<-?\s*['\"]?\w+"), "heredoc construction is prohibited"),
    (re.compile(r"(?i)(?:^|[\s;/])(?:/bin/)?(?:ba|z|k|c)?sh\s+-c\b"), "constructed shell execution is prohibited"),
    (re.compile(r"(?m)^\s*(?:eval|source)\b"), "dynamic execution is prohibited"),
    (
        re.compile(
            r'(?m)^\s*(?:!\s+)?exec\b'
            r'(?!\s+(?:'
            r'9<"\$MUTATION_LOCK_DIRECTORY"|'
            r'/usr/bin/bash\s+"\$0"\s+"\$@"'
            r')\s*$)'
        ),
        "dynamic execution is prohibited",
    ),
    (re.compile(r"(?i)\b(?:apt|apt-get|dnf|yum|rpm-ostree|pip|npm)\s+(?:install|update|upgrade|remove)\b"), "package mutation is prohibited"),
    (re.compile(r"(?m)(?:^|[\s|;&])(?:aws|ssh|scp|sftp|wget|nc|ncat|socat)\s"), "remote/general administration command is prohibited"),
    (re.compile(r"169\.254\.169\.254|/latest/meta-data|/latest/api/token"), "instance metadata access is prohibited"),
    (re.compile(r"(?i)\b(?:eth_sendRawTransaction|eth_sendTransaction|junca_submitVote|personal_|txpool_|miner_)\b"), "transaction or mining control is prohibited"),
    (re.compile(r"(?i)\b(?:activate|enable|open|submit|transfer)\w*[_ -]?(?:mainnet|bridge|asset|transaction)\b"), "Mainnet/bridge/asset/transaction mutation is prohibited"),
    (re.compile(r"(?m)^\s*(?:env|printenv|export|declare\s+-p)\b"), "environment dumping is prohibited"),
    (re.compile(r"(?m)^\s*set(?:\s|$)(?!-euo pipefail$)"), "only fail-fast shell settings may use set"),
    (re.compile(r"/(?:root|home)/|/proc/[0-9a-zA-Z]|/\.aws(?:/|\b)"), "credential-bearing filesystem access is prohibited"),
    (
        re.compile(
            r"/etc/(?:shadow|gshadow|passwd|group|sudoers|ssh)(?:\b|/)|"
            r"/var/(?:run/secrets|lib/sss|lib/cloud/instance)(?:\b|/)|"
            r"/sys/(?:kernel|firmware)(?:\b|/)"
        ),
        "sensitive operating-system path access is prohibited",
    ),
)

READ_ONLY_MUTATION_PATTERN = re.compile(
    r"/usr/bin/(?:"
    r"systemctl\s+(?:restart|start|stop|enable|disable|daemon-reload)|"
    r"mv\b|cp\b|rm\b|install\b|chmod\b|chown\b|truncate\b|tee\b|"
    r"sed\s+-i\b"
    r")"
)

KNOWN_EXTERNAL_COMMANDS = (
    "awk",
    "bash",
    "cloud-init",
    "chmod",
    "cp",
    "curl",
    "date",
    "flock",
    "jq",
    "journalctl",
    "mktemp",
    "mountpoint",
    "mv",
    "rm",
    "sed",
    "sha256sum",
    "sleep",
    "sqlite3",
    "stat",
    "sync",
    "systemctl",
    "tail",
    "timeout",
    "wc",
)


if yaml is not None:
    class _UniqueKeyLoader(yaml.SafeLoader):
        pass


    def _construct_unique_mapping(
        loader: Any, node: Any, deep: bool = False
    ) -> dict[Any, Any]:
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise ContractError("YAML mapping key is not scalar") from exc
            if duplicate:
                raise ContractError(f"duplicate YAML key: {key}")
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping


    _UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        _construct_unique_mapping,
    )
else:
    _UniqueKeyLoader = None


def _json_unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _load_canonical_document_without_pyyaml(
    text: str, *, label: str
) -> Mapping[str, Any]:
    """Load only a digest-pinned canonical document on dependency-minimal CI."""

    _require(label in DOCUMENT_SPECS, f"{label}: unknown canonical document")
    _require(
        hashlib.sha256(text.encode("utf-8")).hexdigest()
        == CANONICAL_DOCUMENT_SHA256[label],
        f"{label}: canonical document digest differs",
    )
    marker = "      runCommand:\n        - |-\n"
    _require(
        text.count(marker) == 1,
        f"{label}: canonical runCommand marker differs",
    )
    shell_block = text.split(marker, 1)[1]
    shell_lines: list[str] = []
    for line in shell_block.splitlines():
        _require(
            not line or line.startswith("          "),
            f"{label}: canonical shell indentation differs",
        )
        shell_lines.append("" if not line else line[10:])
    script = "\n".join(shell_lines)
    parameters = {
        name: {
            "type": "String",
            "description": "Digest-pinned canonical parameter.",
            "allowedPattern": pattern,
            "interpolationType": "ENV_VAR",
        }
        for name, pattern in DOCUMENT_SPECS[label]["parameters"].items()
    }
    return {
        "schemaVersion": "2.2",
        "description": "Repository contract only; digest-pinned canonical document.",
        "parameters": parameters,
        "mainSteps": [
            {
                "action": "aws:runShellScript",
                "name": EXPECTED_STEP_NAMES[label],
                "inputs": {"runCommand": [script]},
            }
        ],
    }


def load_document_text(text: str, *, label: str) -> Mapping[str, Any]:
    if yaml is None:
        return _load_canonical_document_without_pyyaml(text, label=label)
    try:
        document = yaml.load(text, Loader=_UniqueKeyLoader)
    except ContractError:
        raise
    except yaml.YAMLError as exc:
        raise ContractError(f"{label}: invalid YAML") from exc
    _require(isinstance(document, Mapping), f"{label}: document must be a mapping")
    return document


def extract_shell(document: Mapping[str, Any], *, label: str) -> str:
    steps = document.get("mainSteps")
    _require(
        isinstance(steps, list) and len(steps) == 1,
        f"{label}: exactly one main step is required",
    )
    step = steps[0]
    _require(isinstance(step, Mapping), f"{label}: main step must be a mapping")
    inputs = step.get("inputs")
    _require(isinstance(inputs, Mapping), f"{label}: step inputs must be a mapping")
    run_command = inputs.get("runCommand")
    _require(
        isinstance(run_command, list)
        and len(run_command) == 1
        and isinstance(run_command[0], str),
        f"{label}: runCommand must contain exactly one fixed shell body",
    )
    return run_command[0]


def _validate_parameters(
    name: str, parameters: Any, expected: Mapping[str, str]
) -> None:
    _require(isinstance(parameters, Mapping), f"{name}: parameters must be a mapping")
    _require(
        list(parameters) == list(expected),
        f"{name}: parameter keys/order differ from the fixed contract",
    )
    for parameter_name, expected_pattern in expected.items():
        normalized = re.sub(r"[^a-z0-9]", "", parameter_name.lower())
        _require(
            normalized not in BANNED_PARAMETER_NAMES,
            f"{name}: general-purpose parameter is prohibited: {parameter_name}",
        )
        value = parameters[parameter_name]
        _require(
            isinstance(value, Mapping),
            f"{name}.{parameter_name}: definition must be a mapping",
        )
        _require(
            set(value)
            == {"type", "description", "allowedPattern", "interpolationType"},
            f"{name}.{parameter_name}: definition keys must be exact",
        )
        _require(
            value.get("type") == "String",
            f"{name}.{parameter_name}: SSM type must be String",
        )
        _require(
            isinstance(value.get("description"), str)
            and bool(value["description"].strip()),
            f"{name}.{parameter_name}: description is required",
        )
        _require(
            value.get("allowedPattern") == expected_pattern,
            f"{name}.{parameter_name}: allowedPattern differs",
        )
        _require(
            value.get("interpolationType") == "ENV_VAR",
            f"{name}.{parameter_name}: interpolationType must be ENV_VAR",
        )


def _validate_shell(name: str, script: str, expected_parameters: Mapping[str, str]) -> None:
    lines = script.splitlines()
    _require(
        lines[:5]
        == [
            "#!/usr/bin/bash",
            'if [ -z "${BASH_VERSION:-}" ]; then',
            '  exec /usr/bin/bash "$0" "$@"',
            "fi",
            "set -euo pipefail",
        ],
        f"{name}: fixed Bash shebang/re-exec/fail-fast preamble differs",
    )
    try:
        parsed = subprocess.run(
            ["bash", "-n"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise ContractError(f"{name}: bash is unavailable") from exc
    _require(
        parsed.returncode == 0,
        f"{name}: bash -n failed: {parsed.stderr.strip()}",
    )

    _require("{{" not in script and "}}" not in script, f"{name}: direct SSM interpolation is prohibited")
    references = re.findall(r"\$\{SSM_([A-Za-z][A-Za-z0-9]*)\}", script)
    _require(
        Counter(references) == Counter({key: 1 for key in expected_parameters}),
        f"{name}: SSM ENV_VAR references must be exact and unique",
    )
    all_env_tokens = re.findall(r"\bSSM_([A-Za-z][A-Za-z0-9]*)\b", script)
    _require(
        Counter(all_env_tokens) == Counter(references),
        f"{name}: unbraced or duplicate SSM environment key is prohibited",
    )
    for parameter_name in expected_parameters:
        _require(
            f'="${{SSM_{parameter_name}}}"' in script,
            f"{name}: {parameter_name} must be read through a quoted ENV_VAR",
        )

    for pattern, reason in BANNED_SCRIPT_PATTERNS:
        _require(pattern.search(script) is None, f"{name}: {reason}")
    for index, line in enumerate(lines):
        if "/usr/bin/systemctl" in line:
            previous = "" if index == 0 else lines[index - 1]
            _require(
                "/usr/bin/timeout" in line
                or (
                    "/usr/bin/timeout" in previous
                    and previous.rstrip().endswith("\\")
                ),
                f"{name}: every systemctl call must have a fixed timeout",
            )
        if "/usr/bin/journalctl" in line:
            _require(
                "/usr/bin/timeout 10 /usr/bin/journalctl" in line,
                f"{name}: every journalctl call must have a fixed timeout",
            )
        if "/usr/bin/sqlite3" in line:
            _require(
                "/usr/bin/timeout 15 /usr/bin/sqlite3" in line,
                f"{name}: every sqlite3 call must have a fixed timeout",
            )
        if "/usr/bin/cloud-init" in line:
            _require(
                "/usr/bin/timeout 300 /usr/bin/cloud-init status --wait"
                in line,
                f"{name}: cloud-init readiness must have the fixed timeout",
            )
    urls = re.findall(r"https?://[^\s\"']+", script)
    _require(
        urls and set(urls) == {HEALTH_ENDPOINT},
        f"{name}: only the fixed localhost health URL is permitted",
    )
    _require(
        script.count("/usr/bin/curl ") == 1,
        f"{name}: exactly one fixed curl call site is required",
    )
    _require(
        "/usr/bin/curl --fail --silent --show-error --noproxy '*'" in script
        and "--proto '=http' --connect-timeout 2 --max-time 5" in script
        and '--max-filesize "$MAX_JSON_BYTES" "$HEALTH_ENDPOINT"' in script,
        f"{name}: fixed localhost curl transport/time/size contract differs",
    )
    executable_paths = set(
        re.findall(
            r"(?<![A-Za-z0-9_.-])"
            r"(/(?:bin|sbin|usr/bin|usr/sbin|usr/local/bin|usr/local/sbin)/"
            r"[A-Za-z0-9_.-]+)",
            script,
        )
    )
    _require(
        all(path.startswith("/usr/bin/") for path in executable_paths),
        f"{name}: executable path outside /usr/bin is prohibited",
    )
    absolute_executables = {
        path.removeprefix("/usr/bin/") for path in executable_paths
    }
    _require(
        all("/" not in command for command in absolute_executables),
        f"{name}: executable path parsing failed closed",
    )
    _require(
        absolute_executables == EXECUTABLE_ALLOWLISTS[name],
        f"{name}: absolute executable allowlist differs",
    )
    _require(
        "readonly MAX_JSON_BYTES=65536" in script
        and "bounded_json()" in script
        and "bounded_json " in script,
        f"{name}: bounded JSON output contract is required",
    )
    _require(
        ".mainnet_changed == false" in script
        and ".assets_moved == false" in script
        and ".bridge_activated == false" in script,
        f"{name}: all live constitutional flags must be checked as false",
    )
    for flag in ("mainnet_changed", "assets_moved", "bridge_activated"):
        _require(
            f".{flag} == true" not in script
            and f"{flag}: true" not in script
            and f'"{flag}":true' not in script,
            f"{name}: contradictory {flag} true flag is prohibited",
        )
    _require(
        "mainnet_changed: false" in script
        or name == "JuncaPTHealthReadback",
        f"{name}: bounded result must declare mainnet_changed false",
    )
    _require(
        "assets_moved: false" in script
        or name == "JuncaPTHealthReadback",
        f"{name}: bounded result must declare assets_moved false",
    )
    _require(
        "bridge_activated: false" in script
        or name == "JuncaPTHealthReadback",
        f"{name}: bounded result must declare bridge_activated false",
    )

    for command in KNOWN_EXTERNAL_COMMANDS:
        bare = re.compile(rf"(?<![/A-Za-z0-9_.-]){re.escape(command)}(?:\s|$)")
        for match in bare.finditer(script):
            line_start = script.rfind("\n", 0, match.start()) + 1
            prefix = script[line_start : match.start()]
            if prefix.rstrip().endswith(("readonly", "local")):
                continue
            raise ContractError(
                f"{name}: external command must use an absolute path: {command}"
            )

    if DOCUMENT_SPECS[name]["access_class"] == "read-only":
        _require(
            READ_ONLY_MUTATION_PATTERN.search(script) is None,
            f"{name}: read-only document contains a mutating command",
        )
        _require(">>" not in script, f"{name}: read-only document appends to a file")
    else:
        _require(
            "readonly MUTATION_LOCK_DIRECTORY="
            "/run/lock/junca-validator-mutation" in script
            and 'exec 9<"$MUTATION_LOCK_DIRECTORY"' in script
            and "/usr/bin/flock --exclusive --nonblock 9" in script
            and "BLOCKED_CONCURRENT_MUTATION" in script,
            f"{name}: shared nonblocking validator mutation lock is required",
        )
        _require(
            'exec 9>"$MUTATION_LOCK_DIRECTORY"' not in script,
            f"{name}: mutation lock must not follow/create a file target",
        )

    for fragment in DOCUMENT_SPECS[name]["required_fragments"]:
        _require(fragment in script, f"{name}: required fixed fragment missing: {fragment}")

    if name == "JuncaPTHealthReadback":
        _require("/usr/bin/sleep" not in script, f"{name}: caller delay must not enter the document")
        _require("/usr/bin/systemctl" not in script, f"{name}: health readback must not control a service")
    if name == "JuncaPTRestartHealth":
        _require("parameters" not in script, f"{name}: unexpected dynamic parameter surface")
    if name == "JuncaPTFinalitySet":
        mutation_targets = set(re.findall(r"/(?:etc|var|opt)/junca/[A-Za-z0-9._/-]+", script))
        _require(
            all(
                target
                in {
                    "/etc/junca/runtime.env",
                    "/etc/junca/.runtime.env.rollback",
                    "/etc/junca/.runtime.env.candidate",
                    "/etc/junca/.runtime.env.recovery",
                    "/etc/junca/.runtime.env.transaction.json",
                    "/etc/junca/.runtime.env.transaction.next",
                    "/opt/junca/validator-runtime.tar.gz",
                }
                for target in mutation_targets
            ),
            f"{name}: mutation surface contains an unexpected fixed path",
        )
    _require(
        hashlib.sha256(script.encode("utf-8")).hexdigest()
        == CANONICAL_SHELL_SHA256[name],
        f"{name}: canonical shell body digest differs",
    )


def validate_document_text(name: str, text: str) -> dict[str, Any]:
    _require(name in DOCUMENT_SPECS, f"unknown document: {name}")
    document = load_document_text(text, label=name)
    _require(
        set(document) == {"schemaVersion", "description", "parameters", "mainSteps"},
        f"{name}: top-level keys must be exact",
    )
    _require(document.get("schemaVersion") == "2.2", f"{name}: schemaVersion must be 2.2")
    description = document.get("description")
    _require(
        isinstance(description, str)
        and "Repository contract only" in description,
        f"{name}: repository-only status must be explicit",
    )
    spec = DOCUMENT_SPECS[name]
    expected_parameters = spec["parameters"]
    _validate_parameters(name, document.get("parameters"), expected_parameters)

    steps = document.get("mainSteps")
    _require(
        isinstance(steps, list) and len(steps) == 1,
        f"{name}: exactly one main step is required",
    )
    step = steps[0]
    _require(
        isinstance(step, Mapping)
        and set(step) == {"action", "name", "inputs"},
        f"{name}: main step keys must be exact",
    )
    _require(step.get("action") == "aws:runShellScript", f"{name}: action must be aws:runShellScript")
    _require(step.get("name") == EXPECTED_STEP_NAMES[name], f"{name}: step name differs")
    inputs = step.get("inputs")
    _require(
        isinstance(inputs, Mapping) and set(inputs) == {"runCommand"},
        f"{name}: plugin inputs must contain only runCommand",
    )
    script = extract_shell(document, label=name)
    _validate_shell(name, script, expected_parameters)
    _require(
        hashlib.sha256(text.encode("utf-8")).hexdigest()
        == CANONICAL_DOCUMENT_SHA256[name],
        f"{name}: canonical document digest differs",
    )
    return {
        "name": name,
        "access_class": spec["access_class"],
        "parameters": list(expected_parameters),
        "shell_lines": len(script.splitlines()),
    }


def _load_manifest(path: Path) -> Mapping[str, Any]:
    try:
        manifest = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_json_unique_object,
        )
    except ContractError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError("manifest.json: invalid JSON") from exc
    _require(isinstance(manifest, Mapping), "manifest.json: root must be an object")
    return manifest


def _validate_manifest(
    root: Path,
    manifest: Mapping[str, Any],
    document_reports: Mapping[str, Mapping[str, Any]],
    scripts: Mapping[str, str],
) -> None:
    _require(set(manifest) == MANIFEST_KEYS, "manifest.json: top-level keys must be exact")
    _require(
        manifest.get("schema_version") == "junca-fixed-ssm-document-manifest/v1",
        "manifest.json: schema_version differs",
    )
    _require(
        manifest.get("status") == "REPOSITORY_CONTRACT_ONLY_NOT_DEPLOYED",
        "manifest.json: repository-only status differs",
    )
    _require(
        manifest.get("operational_decision")
        == "BLOCKED_PENDING_ATTESTED_LAUNCH_AND_SSM_CONTRACT",
        "manifest.json: operational decision must remain blocked",
    )
    _require(
        manifest.get("owner_principal")
        == "arn:aws:iam::595710543956:role/JuncaChainSecurityBootstrap",
        "manifest.json: owner principal differs",
    )
    _require(manifest.get("account_id") == "595710543956", "manifest.json: account differs")
    _require(manifest.get("region") == "us-east-1", "manifest.json: region differs")
    _require(manifest.get("document_type") == "Command", "manifest.json: document type differs")
    _require(manifest.get("schema_version_ssm") == "2.2", "manifest.json: SSM schema differs")
    _require(
        manifest.get("runtime_lock_contract")
        == {
            "path": "/run/lock/junca-validator-mutation",
            "type": "directory",
            "owner": "root",
            "group": "root",
            "mode": "0700",
            "provisioned_by":
                "systemd-tmpfiles rule in SecurityBootstrap-owned immutable validator AMI",
            "repository_provisioning_present": True,
            "live_readback_present": False,
        },
        "manifest.json: runtime mutation lock contract differs",
    )

    documents = manifest.get("documents")
    _require(isinstance(documents, list), "manifest.json: documents must be an array")
    names = [item.get("name") if isinstance(item, Mapping) else None for item in documents]
    _require(
        names == sorted(DOCUMENT_SPECS),
        "manifest.json: exact six documents in canonical order are required",
    )
    for entry in documents:
        _require(isinstance(entry, Mapping), "manifest.json: document entry must be an object")
        _require(
            set(entry) == MANIFEST_DOCUMENT_KEYS,
            f"manifest.json: {entry.get('name')} keys must be exact",
        )
        name = entry["name"]
        report = document_reports[name]
        filename = f"{name}.yaml"
        _require(entry.get("file") == filename, f"manifest.json: {name} filename differs")
        _require(
            entry.get("access_class") == report["access_class"],
            f"manifest.json: {name} access class differs",
        )
        _require(
            entry.get("parameters") == report["parameters"],
            f"manifest.json: {name} parameters differ",
        )
        digest = hashlib.sha256((root / filename).read_bytes()).hexdigest()
        _require(
            entry.get("repository_sha256") == digest,
            f"manifest.json: {name} repository digest differs",
        )
        _require(
            entry.get("accepted_live_document_version") is None,
            f"manifest.json: {name} must not claim a live version",
        )
        _require(
            entry.get("accepted_live_content_sha256") is None,
            f"manifest.json: {name} must not claim a live digest",
        )
        _require(
            entry.get("live_readback_present") is False,
            f"manifest.json: {name} must not claim live readback",
        )

    required_binaries = sorted(
        {
            match
            for script in scripts.values()
            for match in re.findall(r"/usr/bin/[A-Za-z0-9_.-]+", script)
        }
    )
    _require(
        manifest.get("required_runtime_binaries") == required_binaries,
        "manifest.json: required runtime binary inventory differs",
    )
    missing = manifest.get("live_acceptance_missing")
    _require(
        isinstance(missing, list)
        and len(missing) >= 6
        and all(isinstance(item, str) and item for item in missing),
        "manifest.json: live acceptance blockers are incomplete",
    )
    not_implemented = manifest.get("not_implemented_by_this_manifest")
    _require(
        isinstance(not_implemented, list)
        and any("Automation document" in item for item in not_implemented)
        and any("launch-template" in item for item in not_implemented)
        and any("mutation lock directory" in item for item in not_implemented)
        and any("live AWS deployment" in item for item in not_implemented),
        "manifest.json: deferred Automation/launch/live work is incomplete",
    )
    for flag in (
        "mainnet_changed",
        "assets_moved",
        "bridge_activated",
        "transaction_submission_enabled",
    ):
        _require(manifest.get(flag) is False, f"manifest.json: {flag} must be false")


def validate_contract(root: Path) -> dict[str, Any]:
    root = root.resolve()
    _require(root.is_dir(), f"SSM document directory does not exist: {root}")
    expected_files = {f"{name}.yaml" for name in DOCUMENT_SPECS} | {"manifest.json"}
    actual_files = {path.name for path in root.iterdir() if path.is_file()}
    _require(actual_files == expected_files, "SSM document directory file inventory differs")

    reports: dict[str, dict[str, Any]] = {}
    scripts: dict[str, str] = {}
    for name in sorted(DOCUMENT_SPECS):
        path = root / f"{name}.yaml"
        text = path.read_text(encoding="utf-8")
        reports[name] = validate_document_text(name, text)
        scripts[name] = extract_shell(load_document_text(text, label=name), label=name)
    manifest = _load_manifest(root / "manifest.json")
    _validate_manifest(root, manifest, reports, scripts)
    return {
        "schema_version": "junca-fixed-ssm-document-contract-report/v1",
        "status": "REPOSITORY_CONTRACT_ONLY_NOT_DEPLOYED",
        "operational_decision": "BLOCKED_PENDING_ATTESTED_LAUNCH_AND_SSM_CONTRACT",
        "documents": [reports[name] for name in sorted(reports)],
        "document_count": len(reports),
        "mainnet_changed": False,
        "assets_moved": False,
        "bridge_activated": False,
        "transaction_submission_enabled": False,
        "accepted": True,
    }


def validate_invocation(
    document_name: str,
    parameters: Mapping[str, Any],
    *,
    now_epoch: int,
) -> dict[str, str]:
    """Validate an intended invocation before it reaches the fixed Bash body."""

    _require(document_name in DOCUMENT_SPECS, f"unknown document: {document_name}")
    _require(
        isinstance(parameters, Mapping),
        f"{document_name}: invocation parameters must be a mapping",
    )
    expected = DOCUMENT_SPECS[document_name]["parameters"]
    _require(
        set(parameters) == set(expected),
        f"{document_name}: invocation parameter keys differ",
    )
    normalized: dict[str, str] = {}
    for key, pattern in expected.items():
        value = parameters[key]
        _require(
            isinstance(value, str),
            f"{document_name}.{key}: invocation value must be a string",
        )
        _require(
            re.fullmatch(pattern, value) is not None,
            f"{document_name}.{key}: invocation value rejected",
        )
        normalized[key] = value

    if document_name in {"JuncaPTFinalityInspect", "JuncaPTFinalitySet"}:
        enabled = normalized["Enabled"]
        interval = int(normalized["BlockIntervalSeconds"])
        epoch = int(normalized["SlotEpochSeconds"])
        if enabled == "true":
            _require(interval == 30, f"{document_name}: enabled interval must be 30")
            _require(epoch > 0, f"{document_name}: enabled epoch must be positive")
            _require(epoch % 30 == 0, f"{document_name}: enabled epoch must be 30-second aligned")
            future_preflight = (
                document_name == "JuncaPTFinalitySet"
                or normalized.get("Mode") == "preflight"
            )
            if future_preflight:
                _require(
                    epoch > now_epoch,
                    f"{document_name}: enabled preflight epoch must be future",
                )
                _require(
                    epoch <= now_epoch + MAX_FINALITY_EPOCH_HORIZON_SECONDS,
                    f"{document_name}: enabled preflight epoch exceeds "
                    "60-second horizon",
                )
        else:
            _require(interval == 0, f"{document_name}: disabled interval must be zero")
            _require(epoch == 0, f"{document_name}: disabled epoch must be zero")

    if document_name == "JuncaPTFinalityInspect":
        mode = normalized["Mode"]
        allow_missing = normalized["AllowMissingFinalityKeys"]
        if mode == "exact":
            _require(allow_missing == "false", f"{document_name}: exact mode cannot allow missing keys")
        if allow_missing == "true":
            _require(mode == "preflight", f"{document_name}: missing keys require preflight")
            _require(normalized["Enabled"] == "false", f"{document_name}: missing keys require disabled state")
            _require(
                normalized["BlockIntervalSeconds"] == "0"
                and normalized["SlotEpochSeconds"] == "0",
                f"{document_name}: missing keys require false/0/0",
            )
    return normalized


def _default_root() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "infrastructure"
        / "aws"
        / "ssm-documents"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=_default_root())
    parser.add_argument("--document-name", choices=sorted(DOCUMENT_SPECS))
    parser.add_argument("--parameters-file", type=Path)
    parser.add_argument("--now-epoch", type=int)
    args = parser.parse_args(argv)
    try:
        invocation_mode = any(
            value is not None
            for value in (
                args.document_name,
                args.parameters_file,
                args.now_epoch,
            )
        )
        if invocation_mode:
            _require(
                args.document_name is not None
                and args.parameters_file is not None
                and args.now_epoch is not None,
                "invocation validation requires document, parameters, and time",
            )
            parameters = json.loads(
                args.parameters_file.read_text(encoding="utf-8"),
                object_pairs_hook=_json_unique_object,
            )
            report = {
                "schema_version":
                    "junca-fixed-ssm-invocation-decision/v1",
                "document_name": args.document_name,
                "parameters": validate_invocation(
                    args.document_name,
                    parameters,
                    now_epoch=args.now_epoch,
                ),
                "accepted": True,
                "mainnet_changed": False,
                "assets_moved": False,
                "bridge_activated": False,
                "transaction_submission_enabled": False,
            }
        else:
            report = validate_contract(args.root)
    except (
        ContractError,
        json.JSONDecodeError,
        OSError,
        UnicodeError,
    ) as exc:
        print(f"fixed SSM document contract rejected: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

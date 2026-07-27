#!/usr/bin/env bash
set -euo pipefail
umask 027

volume_id="${JUNCA_STATE_VOLUME_ID:-}"
rollback_token="${JUNCA_MIGRATION_TOKEN:-}"
phase="${JUNCA_MIGRATION_PHASE:-migrate}"
expected_signer_arn="${JUNCA_EXPECTED_SIGNER_ARN:-}"
backfill_tool="${JUNCA_FINALITY_BACKFILL_TOOL:-}"
backfill_request="${JUNCA_FINALITY_BACKFILL_REQUEST:-}"
backfill_request_sha256="${JUNCA_FINALITY_BACKFILL_REQUEST_SHA256:-}"
[[ "$volume_id" =~ ^vol-[0-9a-f]{8,17}$ ]]
[[ "$rollback_token" =~ ^[0-9]+-[0-9]+$ ]]
case "$phase" in
  prepare|migrate|verify) ;;
  *) echo "JUNCA_MIGRATION_PHASE must be prepare, migrate, or verify" >&2; exit 2 ;;
esac
[[ "$expected_signer_arn" =~ ^arn:aws:kms:us-east-1:595710543956:key/.+ ]]
test -f "$backfill_tool"
test ! -L "$backfill_tool"
test -f "$backfill_request"
test ! -L "$backfill_request"
[[ "$backfill_request_sha256" =~ ^[0-9a-f]{64}$ ]]
actual_backfill_request_sha256="$(
  python3 - "$backfill_request" <<'PY'
import hashlib
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    value = json.load(source)
canonical = json.dumps(
    value,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
).encode("utf-8")
print(hashlib.sha256(canonical).hexdigest())
PY
)"
test "$actual_backfill_request_sha256" = "$backfill_request_sha256"
runtime_signer_arn="$(
  sed -n 's/^SIGNER_RESOURCE_ARN=//p' /etc/junca/runtime.env
)"
test "$runtime_signer_arn" = "$expected_signer_arn"

state_path=/var/lib/junca
temporary_mount=/mnt/junca-validator-state-migration
rollback_path="/var/lib/junca-root-rollback-${rollback_token}"
expected_serial="${volume_id//-/}"
device="/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_${expected_serial}"
before_health="/tmp/junca-health-before-${rollback_token}.json"
after_health="/tmp/junca-health-after-${rollback_token}.json"
source_manifest="/tmp/junca-state-source-${rollback_token}.metadata.json"
target_manifest="/tmp/junca-state-target-${rollback_token}.metadata.json"
backfill_result="/tmp/junca-finality-backfill-${rollback_token}.json"
switched=false
root_path_moved=false
service_stopped=false

certificate_hash() {
  python3 - "$1" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    value = json.load(source)
certificate = value.get("consensus", {}).get("last_certificate_hash")
if not isinstance(certificate, str) or re.fullmatch(r"0x[0-9a-f]{64}", certificate) is None:
    raise SystemExit("last_certificate_hash is absent or invalid")
print(certificate)
PY
}

head_field() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    value = json.load(source)
field = value.get(sys.argv[2])
if sys.argv[2] == "head_height":
    if not isinstance(field, int) or isinstance(field, bool) or field < 0:
        raise SystemExit("head_height is absent or invalid")
elif not isinstance(field, str) or not field.startswith("0x"):
    raise SystemExit(f"{sys.argv[2]} is absent or invalid")
print(field)
PY
}

verify_sqlite() {
  python3 - "$1" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
try:
    result = connection.execute("PRAGMA integrity_check").fetchone()
finally:
    connection.close()
if result != ("ok",):
    raise SystemExit(f"sqlite3 PRAGMA integrity_check failed: {result!r}")
PY
}

verify_backfill_binding() {
  python3 - "$1" "$backfill_request" <<'PY'
import json
import sqlite3
import sys

database, request_path = sys.argv[1:]
with open(request_path, encoding="utf-8") as source:
    request = json.load(source)
connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
connection.row_factory = sqlite3.Row
try:
    row = connection.execute(
        """
        SELECT height,block_hash,finalized,certificate_hash
        FROM blocks ORDER BY height DESC LIMIT 1
        """
    ).fetchone()
finally:
    connection.close()
if (
    row is None
    or row["height"] != request.get("head_height")
    or row["block_hash"] != request.get("head_hash")
    or row["finalized"] != 1
    or row["certificate_hash"] != request.get("certificate_hash")
):
    raise SystemExit("durable head does not bind finality backfill request")
PY
}

verify_legacy_sqlite_equivalence() {
  python3 - "$1" "$2" <<'PY'
import sqlite3
import sys

source_path, target_path = sys.argv[1:]
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
target = sqlite3.connect(f"file:{target_path}?mode=ro", uri=True)
try:
    source_tables = {
        row[0]
        for row in source.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """
        )
    }
    target_tables = {
        row[0]
        for row in target.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """
        )
    }
    if source_tables != {"metadata", "blocks"}:
        raise SystemExit("legacy source state schema is unexpected")
    if target_tables != {
        "metadata",
        "blocks",
        "finality_certificates",
    }:
        raise SystemExit("backfilled target state schema is unexpected")
    source_objects = list(
        source.execute(
            """
            SELECT type,name,tbl_name,sql FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type,name
            """
        )
    )
    target_objects = list(
        target.execute(
            """
            SELECT type,name,tbl_name,sql FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
              AND name != 'finality_certificates'
            ORDER BY type,name
            """
        )
    )
    if source_objects != target_objects:
        raise SystemExit("target SQLite objects differ from legacy source")
    finality_objects = list(
        target.execute(
            """
            SELECT type,name,tbl_name FROM sqlite_master
            WHERE name='finality_certificates'
            """
        )
    )
    if finality_objects != [
        ("table", "finality_certificates", "finality_certificates")
    ]:
        raise SystemExit("finality certificate schema scope is invalid")
    for table, order in (
        ("metadata", "key"),
        ("blocks", "height"),
    ):
        source_columns = list(source.execute(f"PRAGMA table_info({table})"))
        target_columns = list(target.execute(f"PRAGMA table_info({table})"))
        if source_columns != target_columns:
            raise SystemExit(f"{table} schema changed during backfill")
        source_rows = list(source.execute(f"SELECT * FROM {table} ORDER BY {order}"))
        target_rows = list(target.execute(f"SELECT * FROM {table} ORDER BY {order}"))
        if source_rows != target_rows:
            raise SystemExit(f"{table} rows changed during backfill")
finally:
    source.close()
    target.close()
PY
}

write_metadata_manifest() {
  python3 - "$1" "$2" "${3:-include-state}" <<'PY'
import base64
import hashlib
import json
import os
import stat
import sys

root = os.path.abspath(sys.argv[1])
output = sys.argv[2]
exclude_state = sys.argv[3] == "exclude-state"
paths = [root]
for directory, names, filenames in os.walk(
    root, topdown=True, followlinks=False
):
    names.sort()
    filenames.sort()
    paths.extend(os.path.join(directory, name) for name in names)
    paths.extend(os.path.join(directory, name) for name in filenames)
paths = sorted(set(paths), key=lambda path: os.path.relpath(path, root))
if exclude_state:
    paths = [
        path
        for path in paths
        if os.path.relpath(path, root)
        not in {"state.sqlite", "state.sqlite-shm", "state.sqlite-wal"}
    ]

hardlinks = {}
for path in paths:
    value = os.lstat(path)
    if stat.S_ISREG(value.st_mode) and value.st_nlink > 1:
        hardlinks.setdefault((value.st_dev, value.st_ino), []).append(
            os.path.relpath(path, root)
        )

entries = []
for path in paths:
    value = os.lstat(path)
    relative = "." if path == root else os.path.relpath(path, root)
    entry = {
        "path": relative,
        "type": stat.S_IFMT(value.st_mode),
        "mode": stat.S_IMODE(value.st_mode),
        "uid": value.st_uid,
        "gid": value.st_gid,
        "mtime_ns": value.st_mtime_ns,
        "nlink": value.st_nlink,
        "xattrs": {},
    }
    if exclude_state and relative == ".":
        # SQLite WAL/SHM creation and cleanup changes only the containing
        # directory timestamps/link bookkeeping. Compare its ownership,
        # permissions and xattrs while the database is checked semantically.
        entry.pop("mtime_ns")
        entry.pop("nlink")
    for name in sorted(os.listxattr(path, follow_symlinks=False)):
        entry["xattrs"][name] = base64.b64encode(
            os.getxattr(path, name, follow_symlinks=False)
        ).decode("ascii")
    if stat.S_ISREG(value.st_mode):
        digest = hashlib.sha256()
        with open(path, "rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        entry["size"] = value.st_size
        entry["sha256"] = digest.hexdigest()
        if value.st_nlink > 1:
            entry["hardlink_group"] = sorted(
                hardlinks[(value.st_dev, value.st_ino)]
            )
    elif stat.S_ISLNK(value.st_mode):
        entry["target"] = os.readlink(path)
    entries.append(entry)

with open(output, "w", encoding="utf-8") as destination:
    json.dump(entries, destination, sort_keys=True, separators=(",", ":"))
    destination.write("\n")
PY
}

wait_for_health() {
  output="$1"
  for attempt in $(seq 1 90); do
    if curl -fsS http://127.0.0.1:8545/health >"$output"; then
      certificate_hash "$output" >/dev/null
      return 0
    fi
    test "$attempt" -lt 90
    sleep 2
  done
}

wait_for_basic_health() {
  output="$1"
  for attempt in $(seq 1 90); do
    if curl -fsS http://127.0.0.1:8545/health >"$output" &&
      python3 - "$output" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    value = json.load(source)
consensus = value.get("consensus", {})
if (
    value.get("status") != "healthy"
    or value.get("network") != "Public Testnet / No Monetary Value"
    or value.get("chain_id") != 20260723
    or value.get("genesis_hash")
    != "0xdc8200c498d28d23ec834fde6559d5b14f0b05a4ed5178c4b90642310b8660a6"
    or not isinstance(value.get("head_height"), int)
    or isinstance(value.get("head_height"), bool)
    or value["head_height"] < 0
    or re.fullmatch(r"0x[0-9a-f]{64}", value.get("head_hash", "")) is None
    or value.get("private_key_material_accepted") is not False
    or value.get("mainnet_changed") is not False
    or value.get("assets_moved") is not False
    or value.get("bridge_activated") is not False
    or consensus.get("chain_id") != 20260723
    or consensus.get("pending_height") is not None
    or consensus.get("required_vote_count") != 3
    or consensus.get("quorum_rule") != "strictly-greater-than-two-thirds"
    or consensus.get("private_key_material_accepted") is not False
    or consensus.get("mainnet_changed") is not False
    or consensus.get("assets_moved") is not False
    or consensus.get("bridge_activated") is not False
):
    raise SystemExit("basic Public Testnet health validation failed")
PY
    then
      return 0
    fi
    test "$attempt" -lt 90
    sleep 2
  done
}

if [[ "$phase" == prepare ]]; then
  test -d "$state_path"
  test ! -L "$state_path"
  test -f "$state_path/state.sqlite"
  test ! -L "$state_path/state.sqlite"
  wait_for_basic_health "$before_health"
  before_certificate="$(jq -er '.certificate_hash' "$backfill_request")"
  verify_sqlite "$state_path/state.sqlite"
  verify_backfill_binding "$state_path/state.sqlite"
  systemctl stop junca-validator
  systemctl is-active --quiet junca-validator && exit 1
  sync
  verify_sqlite "$state_path/state.sqlite"
  printf '{"state":"SNAPSHOT_READY","volume_id":"%s","certificate_hash":"%s"}\n' \
    "$volume_id" "$before_certificate"
  exit 0
fi

rollback() {
  local rollback_status="$1"
  local rollback_line="${2:-unknown}"
  local rollback_command="${3:-unknown}"
  trap - ERR EXIT INT TERM
  set +e
  printf \
    'JUNCA_MIGRATION_FAILURE phase=%q line=%q status=%q command=%q\n' \
    "$phase" "$rollback_line" "$rollback_status" "$rollback_command" >&2
  if [[ "$root_path_moved" == true ]]; then
    systemctl stop junca-validator
    mountpoint -q "$state_path" && umount "$state_path"
    rmdir "$state_path" 2>/dev/null || true
    if [[ -d "$rollback_path" ]]; then
      mv "$rollback_path" "$state_path"
    fi
    rm -f /etc/systemd/system/junca-validator-state.service
    rm -f \
      /etc/systemd/system/junca-validator.service.d/validator-state.conf
    rmdir /etc/systemd/system/junca-validator.service.d 2>/dev/null || true
    systemctl daemon-reload
    service_stopped=true
  fi
  mountpoint -q "$temporary_mount" && umount "$temporary_mount"
  if [[ "$service_stopped" == true ]]; then
    systemctl start junca-validator
  fi
  exit "$rollback_status"
}
trap 'rollback "$?" "$LINENO" "$BASH_COMMAND"' ERR EXIT
trap 'rollback 130' INT
trap 'rollback 143' TERM

for attempt in $(seq 1 120); do
  [[ -b "$device" ]] && break
  test "$attempt" -lt 120
  sleep 5
done
[[ -b "$device" ]]
resolved_device="$(readlink -f "$device")"
[[ -b "$resolved_device" ]]
actual_serial="$(lsblk -ndo SERIAL "$device" | tr -d '-')"
test "$actual_serial" = "$expected_serial"

if [[ "$phase" == verify ]]; then
  mountpoint -q "$state_path"
  test "$(findmnt -n -o SOURCE --target "$state_path")" = "$resolved_device"
  test -f "$state_path/state.sqlite"
  test ! -L "$state_path/state.sqlite"
  verify_sqlite "$state_path/state.sqlite"
  systemctl stop junca-validator
  service_stopped=true
  systemctl is-active --quiet junca-validator && exit 1
  python3 "$backfill_tool" \
    --database "$state_path/state.sqlite" \
    --request "$backfill_request" \
    --result "$backfill_result"
  jq -e \
    --arg request "$backfill_request_sha256" '
    (.state == "BACKFILLED" or .state == "ALREADY_BACKFILLED") and
    .request_sha256 == $request and
    .write_scope == "finality_certificate_schema_and_head_body_only" and
    .mainnet_changed == false and
    .assets_moved == false and
    .bridge_activated == false
  ' "$backfill_result" >/dev/null
  systemctl start junca-validator
  service_stopped=false
  wait_for_basic_health "$after_health"
  printf '{"state":"VERIFIED_PASS","volume_id":"%s","device":"%s","state_sha256":"%s","certificate_hash":"%s","head_height":%s,"head_hash":"%s"}\n' \
    "$volume_id" "$resolved_device" \
    "$(sha256sum "$state_path/state.sqlite" | cut -d' ' -f1)" \
    "$(jq -er '.certificate_hash' "$backfill_result")" \
    "$(head_field "$after_health" head_height)" \
    "$(head_field "$after_health" head_hash)"
  trap - ERR EXIT INT TERM
  exit 0
fi

if mountpoint -q "$state_path"; then
  test "$(findmnt -n -o SOURCE --target "$state_path")" = "$resolved_device"
  test -f "$state_path/state.sqlite"
  test ! -L "$state_path/state.sqlite"
  verify_sqlite "$state_path/state.sqlite"
  systemctl stop junca-validator
  service_stopped=true
  systemctl is-active --quiet junca-validator && exit 1
  python3 "$backfill_tool" \
    --database "$state_path/state.sqlite" \
    --request "$backfill_request" \
    --result "$backfill_result"
  jq -e \
    --arg request "$backfill_request_sha256" '
    (.state == "BACKFILLED" or .state == "ALREADY_BACKFILLED") and
    .request_sha256 == $request and
    .write_scope == "finality_certificate_schema_and_head_body_only"
  ' "$backfill_result" >/dev/null
  systemctl start junca-validator
  service_stopped=false
  wait_for_basic_health "$after_health"
  if [[ -s "$before_health" ]]; then
    before_height="$(head_field "$before_health" head_height)"
    after_height="$(head_field "$after_health" head_height)"
    test "$after_height" -ge "$before_height"
    if [[ "$after_height" == "$before_height" ]]; then
      test "$(head_field "$after_health" head_hash)" = \
        "$(head_field "$before_health" head_hash)"
    fi
  fi
  printf '{"state":"MOUNT_ACTIVATED_PENDING_FINALITY","volume_id":"%s","device":"%s","state_sha256":"%s","head_height":%s,"head_hash":"%s"}\n' \
    "$volume_id" "$resolved_device" \
    "$(sha256sum "$state_path/state.sqlite" | cut -d' ' -f1)" \
    "$(head_field "$after_health" head_height)" \
    "$(head_field "$after_health" head_hash)"
  trap - ERR EXIT INT TERM
  exit 0
fi

test -d "$state_path"
test ! -L "$state_path"
test -f "$state_path/state.sqlite"
test ! -L "$state_path/state.sqlite"
test ! -e "$rollback_path"
test -s "$before_health"
before_certificate="$(jq -er '.certificate_hash' "$backfill_request")"
service_stopped=true
systemctl is-active --quiet junca-validator && exit 1
sync
verify_sqlite "$state_path/state.sqlite"
verify_backfill_binding "$state_path/state.sqlite"

filesystem="$(blkid -o value -s TYPE "$device" 2>/dev/null || true)"
test "$(lsblk -nrpo NAME "$device" | wc -l)" = 1
test -z "$(findmnt -rn -S "$resolved_device" -o TARGET)"
if [[ -z "$filesystem" ]]; then
  test -z "$(
    wipefs -n -o TYPE "$device" 2>/dev/null |
      tail -n +2 |
      tr -d '[:space:]'
  )"
  # Only an empty/unformatted exact device may reach mkfs.
  mkfs.ext4 -m 0 -L JUNCA_VALIDATOR_STATE "$device"
else
  test "$filesystem" = ext4
  filesystem_label="$(blkid -o value -s LABEL "$device" 2>/dev/null || true)"
  if [[ -z "$filesystem_label" ]]; then
    # An earlier fail-closed attempt may have created the exact dedicated
    # ext4 filesystem before assigning its identity label. Repair only that
    # empty-label condition on the Terraform-bound, unmounted volume; never
    # relabel a differently identified filesystem.
    e2label "$device" JUNCA_VALIDATOR_STATE
    sync
    filesystem_label="$(blkid -o value -s LABEL "$device")"
  fi
  test "$filesystem_label" = JUNCA_VALIDATOR_STATE
fi
install -d -m 0750 "$temporary_mount"
mount -o noatime,nosuid,nodev "$device" "$temporary_mount"
test "$(findmnt -n -o SOURCE --target "$temporary_mount")" = "$resolved_device"
if [[ -d "$temporary_mount/lost+found" ]]; then
  test ! -L "$temporary_mount/lost+found"
  test -z "$(
    find "$temporary_mount/lost+found" -mindepth 1 -print -quit
  )"
  rmdir "$temporary_mount/lost+found"
fi

# Amazon Linux 2023 provides coreutils and Python in the immutable AMI.  cp -a
# preserves ownership, modes, symlinks, ACL/xattr metadata, and timestamps
# without downloading migration-time packages.
if [[ -f "$temporary_mount/state.sqlite" ]]; then
  test ! -L "$temporary_mount/state.sqlite"
  verify_sqlite "$temporary_mount/state.sqlite"
else
  test -z "$(
    find "$temporary_mount" -mindepth 1 -maxdepth 1 -print -quit
  )"
  cp -a --preserve=all "$state_path/." "$temporary_mount/"
  sync
fi
test -f "$temporary_mount/state.sqlite"
test ! -L "$temporary_mount/state.sqlite"
verify_sqlite "$temporary_mount/state.sqlite"
write_metadata_manifest "$state_path" "$source_manifest"
write_metadata_manifest "$temporary_mount" "$target_manifest"
source_state_sha256="$(sha256sum "$state_path/state.sqlite" | cut -d' ' -f1)"
target_state_sha256="$(sha256sum "$temporary_mount/state.sqlite" | cut -d' ' -f1)"
if cmp -s "$source_manifest" "$target_manifest"; then
  test "$source_state_sha256" = "$target_state_sha256"
fi
python3 "$backfill_tool" \
  --database "$temporary_mount/state.sqlite" \
  --request "$backfill_request" \
  --result "$backfill_result"
jq -e \
  --arg request "$backfill_request_sha256" '
  (.state == "BACKFILLED" or .state == "ALREADY_BACKFILLED") and
  .request_sha256 == $request and
  .write_scope == "finality_certificate_schema_and_head_body_only" and
  .mainnet_changed == false and
  .assets_moved == false and
  .bridge_activated == false
' "$backfill_result" >/dev/null
verify_sqlite "$temporary_mount/state.sqlite"
verify_legacy_sqlite_equivalence \
  "$state_path/state.sqlite" "$temporary_mount/state.sqlite"
write_metadata_manifest "$state_path" "$source_manifest" exclude-state
write_metadata_manifest "$temporary_mount" "$target_manifest" exclude-state
cmp "$source_manifest" "$target_manifest"
copy_manifest_sha256="$(sha256sum "$target_manifest" | cut -d' ' -f1)"
target_state_sha256="$(sha256sum "$temporary_mount/state.sqlite" | cut -d' ' -f1)"

umount "$temporary_mount"
mv "$state_path" "$rollback_path"
root_path_moved=true
install -d -m 0750 "$state_path"
mount -o noatime,nosuid,nodev "$device" "$state_path"
switched=true
test "$(findmnt -n -o SOURCE --target "$state_path")" = "$resolved_device"

cat >/usr/local/sbin/junca-mount-validator-state <<EOF
#!/usr/bin/env bash
set -euo pipefail
device='$device'
resolved_device='$resolved_device'
[[ -b "\$device" ]]
test "\$(readlink -f "\$device")" = "\$resolved_device"
if ! mountpoint -q /var/lib/junca; then
  mount -o noatime,nosuid,nodev "\$device" /var/lib/junca
fi
test "\$(findmnt -n -o SOURCE --target /var/lib/junca)" = "\$resolved_device"
test -f /var/lib/junca/state.sqlite
test ! -L /var/lib/junca/state.sqlite
EOF
chmod 0750 /usr/local/sbin/junca-mount-validator-state

cat >/etc/systemd/system/junca-validator-state.service <<'EOF'
[Unit]
Description=JUNCA Validator Durable State Mount
Before=junca-validator.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/junca-mount-validator-state
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
install -d -m 0755 /etc/systemd/system/junca-validator.service.d
cat >/etc/systemd/system/junca-validator.service.d/validator-state.conf <<'EOF'
[Unit]
Requires=junca-validator-state.service
After=junca-validator-state.service
RequiresMountsFor=/var/lib/junca
ConditionPathIsMountPoint=/var/lib/junca
ConditionPathExists=/var/lib/junca/state.sqlite

[Service]
ExecStartPre=/usr/bin/test -f /var/lib/junca/state.sqlite
ExecStartPre=/usr/bin/test ! -L /var/lib/junca/state.sqlite
EOF
systemctl daemon-reload
systemctl enable junca-validator-state.service
systemctl start junca-validator
service_stopped=false
wait_for_basic_health "$after_health"
before_height="$(head_field "$before_health" head_height)"
after_height="$(head_field "$after_health" head_height)"
test "$after_height" -ge "$before_height"
if [[ "$after_height" == "$before_height" ]]; then
  test "$(head_field "$after_health" head_hash)" = \
    "$(head_field "$before_health" head_hash)"
fi
verify_sqlite "$state_path/state.sqlite"

printf '{"state":"MOUNT_ACTIVATED_PENDING_FINALITY","volume_id":"%s","device":"%s","state_sha256":"%s","copy_manifest_sha256":"%s","before_certificate_hash":"%s","before_height":%s,"before_head_hash":"%s","after_height":%s,"after_head_hash":"%s","rollback_path":"%s"}\n' \
  "$volume_id" "$resolved_device" "$source_state_sha256" \
  "$copy_manifest_sha256" "$before_certificate" "$before_height" \
  "$(head_field "$before_health" head_hash)" "$after_height" \
  "$(head_field "$after_health" head_hash)" "$rollback_path"
trap - ERR EXIT INT TERM

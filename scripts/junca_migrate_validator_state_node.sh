#!/usr/bin/env bash
set -euo pipefail
umask 027

volume_id="${JUNCA_STATE_VOLUME_ID:-}"
rollback_token="${JUNCA_MIGRATION_TOKEN:-}"
phase="${JUNCA_MIGRATION_PHASE:-migrate}"
expected_signer_arn="${JUNCA_EXPECTED_SIGNER_ARN:-}"
[[ "$volume_id" =~ ^vol-[0-9a-f]{8,17}$ ]]
[[ "$rollback_token" =~ ^[0-9]+-[0-9]+$ ]]
case "$phase" in
  prepare|migrate|verify) ;;
  *) echo "JUNCA_MIGRATION_PHASE must be prepare, migrate, or verify" >&2; exit 2 ;;
esac
[[ "$expected_signer_arn" =~ ^arn:aws:kms:us-east-1:595710543956:key/.+ ]]
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

write_metadata_manifest() {
  python3 - "$1" "$2" <<'PY'
import base64
import hashlib
import json
import os
import stat
import sys

root = os.path.abspath(sys.argv[1])
output = sys.argv[2]
paths = [root]
for directory, names, filenames in os.walk(
    root, topdown=True, followlinks=False
):
    names.sort()
    filenames.sort()
    paths.extend(os.path.join(directory, name) for name in names)
    paths.extend(os.path.join(directory, name) for name in filenames)
paths = sorted(set(paths), key=lambda path: os.path.relpath(path, root))

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

if [[ "$phase" == prepare ]]; then
  test -d "$state_path"
  test ! -L "$state_path"
  test -f "$state_path/state.sqlite"
  test ! -L "$state_path/state.sqlite"
  wait_for_health "$before_health"
  before_certificate="$(certificate_hash "$before_health")"
  verify_sqlite "$state_path/state.sqlite"
  systemctl stop junca-validator
  systemctl is-active --quiet junca-validator && exit 1
  sync
  verify_sqlite "$state_path/state.sqlite"
  printf '{"state":"SNAPSHOT_READY","volume_id":"%s","certificate_hash":"%s"}\n' \
    "$volume_id" "$before_certificate"
  exit 0
fi

rollback() {
  status=$?
  trap - ERR EXIT
  set +e
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
  exit "$status"
}
trap rollback ERR EXIT INT TERM

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
  systemctl is-active --quiet junca-validator
  wait_for_health "$after_health"
  printf '{"state":"VERIFIED_PASS","volume_id":"%s","device":"%s","state_sha256":"%s","certificate_hash":"%s","head_height":%s,"head_hash":"%s"}\n' \
    "$volume_id" "$resolved_device" \
    "$(sha256sum "$state_path/state.sqlite" | cut -d' ' -f1)" \
    "$(certificate_hash "$after_health")" \
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
  if ! systemctl is-active --quiet junca-validator; then
    service_stopped=true
    systemctl start junca-validator
    service_stopped=false
  fi
  wait_for_health "$after_health"
  if [[ -s "$before_health" ]]; then
    before_height="$(head_field "$before_health" head_height)"
    after_height="$(head_field "$after_health" head_height)"
    test "$after_height" -ge "$before_height"
    if [[ "$after_height" == "$before_height" ]]; then
      test "$(head_field "$after_health" head_hash)" = \
        "$(head_field "$before_health" head_hash)"
      test "$(certificate_hash "$after_health")" = \
        "$(certificate_hash "$before_health")"
    fi
  fi
  printf '{"state":"ALREADY_MIGRATED","volume_id":"%s","device":"%s","state_sha256":"%s","certificate_hash":"%s","head_height":%s,"head_hash":"%s"}\n' \
    "$volume_id" "$resolved_device" \
    "$(sha256sum "$state_path/state.sqlite" | cut -d' ' -f1)" \
    "$(certificate_hash "$after_health")" \
    "$(head_field "$after_health" head_height)" \
    "$(head_field "$after_health" head_hash)"
  trap - ERR EXIT
  exit 0
fi

test -d "$state_path"
test ! -L "$state_path"
test -f "$state_path/state.sqlite"
test ! -L "$state_path/state.sqlite"
test ! -e "$rollback_path"
test -s "$before_health"
before_certificate="$(certificate_hash "$before_health")"
service_stopped=true
systemctl is-active --quiet junca-validator && exit 1
sync
verify_sqlite "$state_path/state.sqlite"

filesystem="$(blkid -o value -s TYPE "$device" 2>/dev/null || true)"
if [[ -n "$filesystem" ]]; then
  echo "validator state device is not empty/unformatted; refusing mkfs" >&2
  exit 1
fi
test "$(lsblk -nrpo NAME "$device" | wc -l)" = 1
test -z "$(findmnt -rn -S "$resolved_device" -o TARGET)"
test -z "$(
  wipefs -n -o TYPE "$device" 2>/dev/null |
    tail -n +2 |
    tr -d '[:space:]'
)"
mkfs.ext4 -m 0 -L JUNCA_VALIDATOR_STATE "$device"
install -d -m 0750 "$temporary_mount"
mount -o noatime,nosuid,nodev "$device" "$temporary_mount"
test "$(findmnt -n -o SOURCE --target "$temporary_mount")" = "$resolved_device"
test -z "$(find "$temporary_mount" -mindepth 1 -maxdepth 1 -print -quit)"

# Amazon Linux 2023 provides coreutils and Python in the immutable AMI.  cp -a
# preserves ownership, modes, symlinks, ACL/xattr metadata, and timestamps
# without downloading migration-time packages.
cp -a --preserve=all "$state_path/." "$temporary_mount/"
sync
test -f "$temporary_mount/state.sqlite"
test ! -L "$temporary_mount/state.sqlite"
verify_sqlite "$temporary_mount/state.sqlite"
write_metadata_manifest "$state_path" "$source_manifest"
write_metadata_manifest "$temporary_mount" "$target_manifest"
cmp "$source_manifest" "$target_manifest"
copy_manifest_sha256="$(sha256sum "$source_manifest" | cut -d' ' -f1)"
source_state_sha256="$(sha256sum "$state_path/state.sqlite" | cut -d' ' -f1)"
target_state_sha256="$(sha256sum "$temporary_mount/state.sqlite" | cut -d' ' -f1)"
test "$source_state_sha256" = "$target_state_sha256"

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
wait_for_health "$after_health"
after_certificate="$(certificate_hash "$after_health")"
before_height="$(head_field "$before_health" head_height)"
after_height="$(head_field "$after_health" head_height)"
test "$after_height" -ge "$before_height"
if [[ "$after_height" == "$before_height" ]]; then
  test "$(head_field "$after_health" head_hash)" = \
    "$(head_field "$before_health" head_hash)"
  test "$after_certificate" = "$before_certificate"
fi
verify_sqlite "$state_path/state.sqlite"

printf '{"state":"VERIFIED_PASS","volume_id":"%s","device":"%s","state_sha256":"%s","copy_manifest_sha256":"%s","certificate_hash":"%s","before_height":%s,"before_head_hash":"%s","after_height":%s,"after_head_hash":"%s","rollback_path":"%s"}\n' \
  "$volume_id" "$resolved_device" "$source_state_sha256" \
  "$copy_manifest_sha256" "$after_certificate" "$before_height" \
  "$(head_field "$before_health" head_hash)" "$after_height" \
  "$(head_field "$after_health" head_hash)" "$rollback_path"
trap - ERR EXIT

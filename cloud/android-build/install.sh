#!/bin/bash
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT=/opt/android-build
STORE=/srv/android-build
secrets=''
projects=''
accepted=false
while (($#)); do
 case "$1" in
 --secrets) secrets="$2"; shift 2;;
 --projects) projects="$2"; shift 2;;
 --accept-sdk-licenses) accepted=true; shift;;
 *) echo "Unknown option: $1" >&2; exit 1;;
 esac
done
[[ $EUID == 0 ]] || { echo 'Run as root on Ubuntu ARM64'; exit 1; }
[[ "$(uname -m)" == aarch64 ]] || { echo 'This build profile requires Linux ARM64'; exit 1; }
[[ -f "$secrets" && "$accepted" == true ]] || { echo 'Supply --secrets FILE and --accept-sdk-licenses (review Google SDK licenses first)'; exit 1; }
python3 - "$secrets" <<'PY_CHECK'
import json,sys
value=json.load(open(sys.argv[1])).get('upstream')
assert isinstance(value,str) and len(value)>=32,'Use generated private upstream secret (at least 32 characters)'
PY_CHECK
if systemctl is-active --quiet android-build; then
 echo 'Stop the existing android-build service before installing or upgrading'; exit 1
fi
command -v docker >/dev/null
export MCPHUB_NETWORK="${MCPHUB_NETWORK:-mcphub_default}"
gateway="$(python3 - "$SRC/.." "$MCPHUB_NETWORK" <<'PY'
import sys
sys.path.insert(0,sys.argv[1]);from network_info import bridge
print(bridge(sys.argv[2])[2])
PY
)"
install -d -m 755 "$ROOT" "$STORE"
if ! mountpoint -q "$STORE"; then
 [[ ! -e /var/lib/android-build-store.img ]] || { echo 'Existing unmounted store image: inspect before retry'; exit 1; }
 [[ -z "$(ls -A "$STORE")" ]] || { echo 'Store mountpoint is nonempty'; exit 1; }
 truncate -s 40G /var/lib/android-build-store.img
 chmod 600 /var/lib/android-build-store.img
 mkfs.ext4 -q -m 0 -L android-build /var/lib/android-build-store.img
 line='/var/lib/android-build-store.img /srv/android-build ext4 loop,nodev,nosuid 0 0'
 grep -Fqx "$line" /etc/fstab || printf '%s\n' "$line" >> /etc/fstab
 mount "$STORE"
fi
# Refuse to reuse an unrelated larger filesystem that would defeat the quota.
python3 - "$STORE" <<'PY'
import shutil,sys
size=shutil.disk_usage(sys.argv[1]).total
assert 35*2**30<size<=40*2**30,'Expected dedicated 40 GiB store filesystem on the existing boot volume'
PY
install -d -o 10001 -g 10001 "$STORE"/{jobs,cache,sdk,uploads}
install -d -m 700 "$ROOT/control"
apt-get update -qq
apt-get install -y -qq python3-venv
python3 -m venv "$ROOT/venv"
"$ROOT/venv/bin/pip" install fastmcp==3.4.5
install -m 644 "$SRC"/{server.py,run_job.py,Dockerfile,install_sdk.py,configure_network.py} "$ROOT/"
install -m 644 "$SRC/../network_info.py" "$ROOT/"
install -m 755 "$SRC/network.sh" "$ROOT/"
if [[ -e "$ROOT/secrets.json" ]]; then cmp -s "$secrets" "$ROOT/secrets.json" || { echo 'Existing secrets differ; refuse implicit key rotation'; exit 1; }; fi
install -m 600 "$secrets" "$ROOT/secrets.json"
if [[ -n "$projects" ]]; then
 [[ ! -e "$ROOT/control/projects.json" ]] || { echo 'Existing projects: register additions through MCP'; exit 1; }
 install -m 600 "$projects" "$ROOT/control/projects.json"
fi
printf 'MCPHUB_NETWORK=%q\nANDROID_BUILD_HOST=%q\nANDROID_BUILD_PORT=18200\n' "$MCPHUB_NETWORK" "$gateway" > "$ROOT/network.env"
chmod 600 "$ROOT/network.env"
printf '*\n!Dockerfile\n' > "$ROOT/.dockerignore"
docker build -t local/android-builder:1 "$ROOT"
docker image inspect local/android-builder:1 --format '{{.Id}}' > "$ROOT/image-id"
"$ROOT/venv/bin/python" "$ROOT/install_sdk.py"
install -m 644 "$SRC/android-build.service" /etc/systemd/system/android-build.service
systemctl daemon-reload
systemctl enable android-build
systemctl restart android-build

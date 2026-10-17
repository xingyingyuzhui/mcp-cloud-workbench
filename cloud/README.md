# Cloud deployment

This is a reusable extraction of an OCI A1 deployment, not a fresh deployment tested on your host. Read [the operating notes](../docs/cloud.md) first. Commands below run on the cloud Ubuntu ARM64 host from any checkout path. They mutate the host and require root, Docker Engine with the iptables firewall backend, systemd, and outbound HTTPS. Docker installation and OCI provisioning are deliberately outside these scripts. Do not expose ports 3000, 18200 or 28189–28192 publicly.

## MCPHub

Create private config on the Mac using the root setup instructions, transfer only the required runtime files through SSH, and prepare a private directory on the cloud host:

```bash
sudo install -d -m 700 /opt/mcphub/data
sudo install -m 644 cloud/mcphub/compose.yaml /opt/mcphub/compose.yaml
sudo install -m 600 runtime/mcphub.env /opt/mcphub/.env
sudo docker compose --project-directory /opt/mcphub create
sudo python3 cloud/mcphub/merge_settings.py \
  --settings /opt/mcphub/data/mcp_settings.json \
  --changes runtime/hub-changes.json --container mcphub
sudo docker compose --project-directory /opt/mcphub up -d
```

`create` prepares a stopped container for the safety check; it must not be running during the merge. For an existing Hub, stop it first; this merge preserves existing services/groups/keys and rejects conflicting named entries. Backups contain secrets, so keep the directory private. The script requires Docker access and refuses on failed inspection.

The pinned upstream image is MCPHub 1.1.5 at the verified ARM64-compatible manifest digest. The compose network defaults to **mcphub_default, 172.18.0.0/16, gateway 172.18.0.1**. Generated Hub URLs, cloud listener addresses, Mac reverse tunnel addresses and Docker network must agree. If that subnet conflicts with another Docker/VPC network, change all runtime network settings together before deployment. Existing networks must have the same IPAM settings; never recreate an active network blindly.

## Android compilation and cleanup

Google SDK licenses must be reviewed and accepted by the operator. The explicit flag records that decision; the installer writes the standard accepted license hashes.

```bash
# Load the generated network values in this shell, then pass them through sudo.
set -a
source runtime/cloud.env
set +a
sudo env MCPHUB_NETWORK="$MCPHUB_NETWORK" bash cloud/android-build/install.sh \
  --secrets runtime/android-build/secrets.json \
  --projects cloud/android-build/projects.example.json \
  --accept-sdk-licenses
sudo systemctl status android-build
sudo journalctl -u android-build -n 100
```

Omit `--projects` for an empty project registry. Do not pass it again over an existing registry; use `register_project`. The Modbus repository is an optional public example, not a default source. Pin a commit when requesting a reproducible build. No cloud deployment is performed by repository tests.

## Mac reverse tunnel

Create the dedicated key manually on the Mac as described in [the Mac guide](../mac/README.md). Transfer only `~/.ssh/mcphub_bridge_ed25519.pub` to the cloud checkout as `runtime/tunnel_ed25519.pub` (create its private `runtime/` directory first). The commands below read that copied public-key file; the Mac scripts do not generate keys automatically. Apply the restricted account and Docker-only firewall:

```bash
sudo python3 cloud/setup_tunnel.py --public-key runtime/tunnel_ed25519.pub \
  --network mcphub_default --user mcphub-bridge --ports 28189,28190,28192
sudo python3 cloud/setup_firewall.py --network mcphub_default --ports 28189,28190,28192
```

Select only ports you actually enable. The SSH installer resolves the network's actual RFC1918 gateway, appends the managed key without removing unrelated keys, refuses unmanaged SSH snippets, and rolls back file changes if `sshd -t` or reload fails. The dedicated user has no shell/session/TTY/agent forwarding. Do not reuse a normal login account.

The firewall resolves the current Docker bridge interface from `docker network inspect`; no machine-specific bridge ID is stored. After recreating a network, restart both `mcp-cloud-firewall` and `android-build`, update runtime addresses if the gateway changed, and reconnect Mac tunnels.

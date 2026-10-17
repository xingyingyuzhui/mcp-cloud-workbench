# Cloud operation and boundaries

The reference host is Ubuntu 24.04 on OCI Ampere A1 ARM64, 4 OCPUs / 24 GB RAM with a 200 GB boot disk. The software does not require an OCI credential or change OCI resources. This repository contains no production credentials, generated APKs, private MCPHub settings or OCI keys.

## Build profile

- JDK 17; project Gradle Wrapper; SDK platform `android-37.2`; build-tools 36.0.0 and 37.0.0.
- Four ARM64 native tools (`aapt2`, `aidl`, `zipalign`, `split-select`) come from [Commit451/android-arm-build-tools](https://github.com/Commit451/android-arm-build-tools), checked against that release's SHA256SUMS. These are community binaries, not official Google Linux ARM64 releases. The checksums verify download consistency, not independent provenance.
- Official SDK archives and local package metadata come from Google's repository manifest. `sdk-manifest.json` records downloaded URLs/checksums.
- Public HTTPS GitHub Gradle projects, or direct `.tar.gz` source uploads through MCP; no repository credential injection, NDK profile, arbitrary shell MCP tool, release signing or emulator on the cloud host.
- 15 MCP tools: environment_info, register_project, list_projects, submit_build, list_builds, get_build_status, read_build_logs, get_artifacts, read_artifact, cancel_build, storage_status, preview_cleanup, cleanup_expired, cleanup_build, set_retention.
- Build modes: build (`assembleDebug`), test (`testDebugUnitTest`), lint (`lintDebug`), full (all three). Additional project-specific modules are not automatically inferred. Debug builds may use Gradle's standard debug signing; there is no release key workflow.

Each build executes source-controlled Gradle code. Direct source uploads are capped at 100 MiB compressed, 2 GiB expanded and 20,000 files; archive paths and entry types are checked, and symlinks are rejected. Upload chunks are sequential and incomplete uploads expire after two hours. Only give the build token to agents allowed to run code. Containers reduce exposure but are not a sandbox against kernel exploits or a substitute for a separate host for hostile tenants. The root control process manages Docker; its token is an administrative capability for this build service. Hub tokens should be scoped to `android-build`, and upstream tokens must remain private.

## Storage and cleanup

`/opt/android-build` stores root-only credentials/control metadata and the Python service. `/srv/android-build` is a dedicated 40 GiB sparse ext4 loop filesystem backed by `/var/lib/android-build-store.img`, which resides on the existing boot volume. It is a logical filesystem ceiling, not a separate physical disk or 40 GiB reserved allocation. The service also refuses/aborts builds below 20 GiB host free or 2 GiB store free. Keep other host workloads bounded. The installer refuses an existing unmounted image or nonempty mountpoint rather than formatting unknown data. It does not delete old host files or expand disks.

One job runs at a time with 2 CPUs, 8 GiB RAM, PID limit 512, read-only container root, unprivileged UID 10001, dropped capabilities and no Docker socket. Queue is capped at 10, metadata history at 1000, logs at 20 MiB per job, extracted artifacts at 1 GiB / 400 files per job, default timeout 30 minutes. SDK is mounted read-only. Cache is per repository/subdirectory, so branches share that repository's cache; repositories are not mutually trusted within the same token scope.

Automatic housekeeping runs every 15 minutes. Success/cancellation/timeout/storage-stop removes workspace after artifact collection. Failed/interrupted workspaces expire after 24 hours. APKs/reports/logs expire after 7 days. Idle caches expire after 14 days or are evicted oldest-first above 20 GiB. Active builds are protected, and `read_artifact` grants a 10-minute output lease. Manual cleanup tools use the same lock; retained metadata marks deleted outputs. Retention knobs have bounds and cannot disable filesystem/free-space safety gates. SDK versions are fixed; SDK/image upgrade and pruning remain an operator maintenance task, not automatic deletion of installed SDKs or shared Docker images.

`fstrim` after deletion can release sparse backing-file blocks. No universal `docker system prune` is run. Control backups, Docker images and host journal live outside the 40 GiB filesystem; configure host journal/Docker rotation and monitor root storage too. MCPHub's container logs rotate at 3 × 10 MB.

## Network and recovery

Hub listens only on cloud loopback 3000. The build MCP listens on the Hub Docker private gateway 18200 with bearer authentication. Container builds use dedicated IPv4 `android-build-net` (172.30.0.0/24). Host iptables rejects their access to RFC1918, link-local metadata and host INPUT; public Internet remains enabled for GitHub/Maven/Gradle downloads. Do not attach builders to other networks or enable IPv6 on their network. Docker must use the iptables backend; this script does not support the experimental nftables backend.

`network_info.py` validates actual Docker IPAM and computes interface name dynamically. The Mac tunnel SSH account permits only the specified private gateway ports. Firewall rules admit those ports only from the Hub Docker bridge/subnet. No public management endpoint, TLS/domain provisioning or broad host firewall reset is provided.

Systemd restarts the build service and reapplies its network rules after Docker restart. On startup it removes only containers bearing its managed label and marks interrupted jobs. Jobs queued before restart remain queued. A changed Docker gateway also requires regenerating the listener environment/Hub URLs and reconnecting SSH tunnels; an interface-only recreation needs service restarts.

The eight isolated safety tests cover active-job cleanup exclusion, cancellation before worker claim, download protection, expiry, bounded history, disk admission, path/repository validation and cache exclusion during builds. They do not exercise Docker, SDK downloads, systemd, SSH, a fresh cloud installation or a real build. The original deployment successfully built the Modbus Android debug APK; this portable extraction must be smoke-tested on a disposable host before replacing an existing deployment.

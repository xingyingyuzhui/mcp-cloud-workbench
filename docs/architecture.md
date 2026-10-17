# 架构与信任边界

## 分工

MCPHub 是 agent 的入口，负责连接上游 MCP 与分配访问范围。耗时编译由独立 Android Build MCP 和任务执行器完成；Mac 应用继续运行在 Mac 上。

| 组件 | 位置 | 职责 |
|---|---|---|
| MCPHub | 云端 Docker | 统一发现与路由 MCP 工具，限制客户端可访问的服务 |
| Android Build MCP | 云端 | 项目校验、任务排队、状态与日志查询、产物下载、存储清理 |
| 构建容器 | 云端 | 运行指定 Gradle 任务，限制 CPU、内存和执行时间 |
| Mac HTTP 代理 | Mac 回环地址 | 将现有 stdio MCP 或本地 HTTP MCP 转为带认证的上游 |
| 反向 SSH | Mac 主动连接云端 | 把代理端口映射到云端 Docker 网桥地址 |
| Mac 应用 | Mac | Blender、ComfyUI 后端和指定 Android 模拟器 |

无域名部署通过 SSH 本地转发访问 MCPHub。反向隧道不要求 Mac 开启公网入站端口。

## Mac 接入

Blender 的 stdio 服务经 FastMCP 代理为 HTTP。ComfyUI 的原 HTTP 服务保留原有回环地址和 Host 校验，通过额外认证代理接入，避免放宽原服务的保护。Android 模拟器复用已有的认证 HTTP 网关。

隧道服务端使用单独账户与 SSH 密钥。只允许指定地址、端口的远程转发，禁止交互 shell、PTY、代理转发和无关端口转发。防火墙仅允许 MCPHub 所在 Docker 网桥访问这些转发端口；公网入口保持关闭。

每个上游使用自己的认证凭据，每个 agent 使用对应范围的 MCPHub 密钥。组合访问组可以同时提供三个 Mac 服务。独立密钥限制入口权限，但不提供应用状态隔离：多个 agent 操作的 Blender 场景、ComfyUI 和模拟器仍可能互相影响，涉及状态修改时应顺序执行或另做调度。

Mac 睡眠、关机或断网时，本地工具不可用；云端构建仍可独立运行。本地 MCP 的启动与空闲关闭由各自生命周期管理器负责，隧道重连不应持续唤醒应用。

## Android 构建

agent 提交仓库与版本及构建参数后，服务返回任务 ID。客户端用后续 MCP 调用读取状态、日志和产物，避免把整个编译周期绑定到一次请求。

每个任务使用自己的工作目录和容器。源码、构建中间文件、依赖缓存、输出和控制记录分别管理。运行容器不应获得 Docker 管理接口、云账户 API 私钥或 Mac 上游凭据。

基线限制为单任务 2 CPU、8 GiB 内存、30 分钟超时，并以单任务并发起步。空间不足时拒绝接单，并终止已达到空间保护条件的构建；异常退出留下的工作区由清理流程回收。

产物下载有锁保护。云端产物路径不是 Mac 路径，安装到模拟器前必须完成传输与校验。正式发布签名不在本项目范围内。

## ARM64 适配

参考部署使用 OCI A1 ARM64。JDK、Gradle 与 Kotlin 可以在该环境运行，但 Android SDK 中部分 Linux 原生工具需适配。参考构建使用 Linux ARM64 工具替代并为 AAPT2 指定路径。

当前验证只覆盖指定 Kotlin/Java Android 项目。它不能证明任意 AGP、Flutter、React Native、NDK 或厂商二进制插件都能运行。尤其 NDK 的 Linux 主机工具链存在架构限制；需要原生依赖的项目应先逐项验证，必要时使用独立 x86_64 构建节点。

参考：[Android 命令行构建](https://developer.android.com/build/building-cmdline)、[NDK 主机工具链](https://developer.android.com/ndk/guides/other_build_systems)、[ARM64 build-tools](https://github.com/Commit451/android-arm-build-tools)。

## 存储边界

构建数据放在现有系统盘上的 40 GiB 稀疏 ext4 loop 文件系统中，使任务数据有文件系统容量上限。它不是独立物理磁盘，也不会预先占满 40 GiB。容器运行镜像与少量控制元数据在其之外，需要另外管理；40 GiB 不代表整台主机的全部服务用量上限。

系统盘可用空间低于 20 GiB、构建数据盘可用空间低于 2 GiB 时，触发空间保护。缓存清理只在构建空闲时进行，运行任务与下载锁保护的产物不应被回收。

详细保留策略见 [运维说明](operations.md)。

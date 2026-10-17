# Mac 本地 MCP 接入

先准备已经能单独工作的本地 MCP。本项目只提供认证代理、隧道与启动配置，不包含 Blender 插件、ComfyUI 模型或 Android 模拟器管理器的实现。

| 服务 | 本地前提 | 代理与转发 |
|---|---|---|
| Blender | 可运行的 stdio MCP 命令，通常是已有的应用生命周期 wrapper | 本项目增加 `127.0.0.1:18190/mcp` 认证代理 → 云端 `28190` |
| ComfyUI | 已有 `127.0.0.1:18189/mcp` | 本项目增加 `127.0.0.1:18191/mcp` 认证代理 → 云端 `28189` |
| Android | 已有 `127.0.0.1:19101/mcp`，使用 bearer key 认证 | 直接复用已有 HTTP MCP → 云端 `28192` |

启用 Android 与云端编译服务后，配置生成器会额外配置 `mac-apk-delivery`：Mac 自动通过 MCPHub 分块拉取云编译 APK、校验 SHA256，写入权限受限的临时文件，再调用现有 Android MCP 的本机路径安装工具。Agent 只需调用 `mac-apk-delivery-install_build_apk(build_id)`，APK 二进制不会进入对话上下文。交付使用独立的反向转发端口 `28193` → Mac loopback `19102`。`render_launchagents.py` 会生成 `local.mcp-cloud-workbench.android-artifact-delivery` LaunchAgent，启动 `mac/android_artifact_delivery.py`；下载串行执行，最多接受 512 MiB APK，并在服务启动时清除缓存中超过 24 小时的遗留 APK。

若 Android MCP 只有 stdio，可自行用固定版本 [Supergateway](https://github.com/supercorp-ai/supergateway) 转成 HTTP，绑定 `127.0.0.1`、启用 API key，再填入配置。本项目不安装或启动模拟器，也不会把真机管理能力替换成未经约束的 ADB 服务。原来限定 AVD、按需启动与闲置回收的 wrapper 要继续保留。

## 生成私有配置

在仓库根目录：

```sh
cp config/workbench.example.json config/local.json
# 编辑 config/local.json，填写主机、路径；按需将 mac 下各服务 enabled 改为 true。
python3 scripts/init_config.py
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

配置生成只写 `runtime/`，不会登录服务器、启动应用或安装服务。模板默认关闭 Mac 服务。Android 启用时会读取 `token_file` 中的现有密钥；不要把密钥值写进公开模板。重复生成保留已生成的密钥，但会按配置更新连接和组成员；缩减组前需要核对现有客户端权限。

首次建立 SSH 时，通过云控制台等可信渠道核对主机指纹，并将主机记录放入配置指定的 `known_hosts_file`。隧道始终使用 `StrictHostKeyChecking=yes`；本项目不会自动信任 `ssh-keyscan` 返回的结果。

为反向连接创建专用 SSH key，例如：

```sh
ssh-keygen -t ed25519 -f ~/.ssh/mcphub_bridge_ed25519 -N ''
```

私钥只留在 Mac；把 `.pub` 交给[云端的专用隧道账户配置](../cloud/README.md)。连接管理面板用管理员 SSH key，反向转发用受限账户 key，两者分开。

## 前台启动与验证

仅启动已经启用的代理（各自占一个终端）：

```sh
.venv/bin/python mac/blender_http.py
.venv/bin/python mac/comfyui_http.py
.venv/bin/python mac/tunnel.py reverse
```

访问云端 MCPHub 管理面板时：

```sh
.venv/bin/python mac/tunnel.py forward
```

打开 `http://127.0.0.1:13000`。客户端配置位于私有的 `runtime/mcp-client.json`。云端还需合并 `runtime/hub-changes.json`，不能只开隧道就认为接入完成。

先运行只读的工具发现/状态查询。确认未认证访问返回 401、单服务密钥无法访问其他服务。不要用真实渲染、出图或模拟器安装操作当作默认健康检查；它们可能唤醒应用并占用资源。

ComfyUI 的额外代理会用正确的本地 URL 请求原服务，保留其 Host 验证。不要为让 Docker 网桥地址直连原 ComfyUI MCP 而关闭该验证。

## 可选：登录后自动启动与重连

先生成 plist，检查其路径与端口是否符合预期：

```sh
.venv/bin/python mac/render_launchagents.py
# 若也想自动保持管理面板隧道，加 --with-forward。
plutil -lint runtime/launchagents/*.plist
```

生成器仅写文件，不修改 LaunchAgents、不加载服务。确认没有另一套同端口服务运行后，再安装：

```sh
mkdir -p ~/Library/LaunchAgents
cp runtime/launchagents/*.plist ~/Library/LaunchAgents/
# 对每个生成的文件执行一次，例如：
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/local.mcp-cloud-workbench.mac-tunnel.plist
```

停止示例：

```sh
launchctl bootout "gui/$(id -u)/local.mcp-cloud-workbench.mac-tunnel"
```

日志位于 `runtime/mac-bridge/logs/`。移动仓库或 venv 后要重新生成 plist。禁用服务时应先 bootout 旧的已加载任务；重新生成只会删除输出目录中过期的本项目 plist，不会停止已加载任务。SSH 使用存活探测和 `ExitOnForwardFailure`；launchd 在进程退出后重启。Mac 休眠、断网或应用未就绪时，云端对应 MCP 会暂时不可用。

本地应用状态会在 agent 之间共享。MCPHub 的服务范围密钥控制“可调用哪个服务”，不会给每个 agent 复制独立 Blender 场景或独立模拟器。

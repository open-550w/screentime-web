# Android：手机 AW + frpc 转发配置教程

目标：保留 ActivityWatch，通过 frpc 将手机上的 AW HTTP 服务转发至自己的服务器，再由 Web 工作台主动读取。普通用户不需要服务器时，请选局域网方案。

这是 **frp >= 0.52 的 TOML 模板**。旧版 Android 客户端可能只接受 INI；有独立的 `frpc.legacy.ini` 参考，不能把 TOML 简单改扩展名当成 INI。

## 先明确端口与凭据

| 字段 | 含义 | 示例 |
|---|---|---|
| 手机 AW 本机端口 | 手机上已有 AW HTTP API | 5600，实际以手机版本为准 |
| serverAddr | frps 所在服务器 IP / 域名 | YOUR_SERVER_IP_OR_DOMAIN |
| serverPort | frpc 连接 frps 的控制端口 | 7000 |
| remotePort | frps 侧为 AW 分配的转发端口 | 7075 |
| frp 共享密钥 | frpc 与 frps 认证 | 两端 auth.token 一致 |
| AW API Token | 工作台访问手机 AW API | 填在工作台数据源中 |
| Web Token | 登录本工作台 / 调用其 API | 不填到 frpc 配置里 |

`localIP = "127.0.0.1"` 在 **手机 frpc** 中指手机自己；不是服务器或电脑。

## 1. 手机配置文件——重点

复制仓库的 `examples/frpc.toml` 到你能找到的文件夹，例如手机 Downloads 下自己创建的目录。用纯文本编辑器编辑；请确认文件没有被保存为 `.toml.txt`。

```toml
serverAddr = "YOUR_SERVER_IP_OR_DOMAIN"
serverPort = 7000
loginFailExit = false

auth.method = "token"
auth.token = "REPLACE_WITH_FRP_SHARED_SECRET"
transport.tls.enable = true

[[proxies]]
name = "aw-my-android"
type = "tcp"
localIP = "127.0.0.1"
localPort = 5600
remotePort = 7075
```

至少修改 serverAddr、auth.token。若 AW 端口不是 5600，也要修改 localPort。多手机需要不同代理 name 和 remotePort，且服务器 allowPorts 必须放行对应端口。

### Android frpc 客户端怎样使用这个文件

各第三方客户端的按钮名称不同，本项目不假装所有版本都有同一界面。对应以下两类之一操作：

- **文件导入 / 选择配置路径**：用 Android 文件选择器选中刚编辑的配置，授予读取权限。若客户端会复制到私有目录，之后需重新导入修改后的文件。
- **内置配置编辑器**：将完整文本粘贴进去，保存为一个独立配置项，再选中该配置项启动。

启动后查看日志：确认已连接 frps，且 `aw-my-android` 代理成功。仅显示客户端进程启动并不代表代理可用。修改配置文件后要停止 / 重新启动或按该客户端支持的 reload 方式生效。

`serverAddr` 不包含 `http://` 或 `https://`，也不附带端口。Token 不写在 URL 中。文件含凭据，不上传到公开仓库或截图分享。

手机须允许 AW 和 frpc 必要的后台活动；否则可能是 frp 连着但 AW 不响应，也可能 AW 正常而隧道断开。

## 2. 服务器 frps

以 `examples/frps.toml` 为起点，密钥与手机一致。模板只开放 7000 控制端口，代理端口绑定服务器 loopback：

```toml
bindPort = 7000
proxyBindAddr = "127.0.0.1"
auth.method = "token"
auth.token = "REPLACE_WITH_FRP_SHARED_SECRET"
transport.tls.force = true
allowPorts = [{ single = 7075 }]
```

`frps -c /你的路径/frps.toml`。服务器安全组 / 防火墙需允许手机连接 7000/TCP。

先在服务器本机测试 `http://127.0.0.1:7075/api/0/info`，若 AW 有认证，带 `Authorization: Bearer <AW_TOKEN>`。

## 3. 让工作台通过 HTTPS 访问

推荐用域名和 HTTPS 反向代理。`examples/Caddyfile` 示例：

```caddy
aw.example.com {
    reverse_proxy 127.0.0.1:7075
}
```

域名需指向服务器，Caddy 的正常证书签发需要对应公网连通条件。工作台填写 `https://aw.example.com` 与 AW Token。

frpc → frps 的 TLS **不涵盖**工作台 → frps 的 HTTP 访问。若选择兼容旧方式 `http://服务器IP:7075`，还需把 proxyBindAddr 改为服务器可访问接口并配置防火墙，且该 HTTP 段没有加密；它不是本教程默认配置。

## 4. 工作台接入与验收

“同步与接入”新增 Android 数据源，连接方式 frpc，填 HTTPS 地址和 AW API Token。“保存并测试连接”后，应出现正确 hostname 和 `aw-watcher-android...` 前台应用桶；有多个桶时选择要用的桶 ID，不要选解锁、媒体或网页桶。

点“立即同步”，确认最近成功时间与设备最新记录时间。然后选择公共调度或独立调度。frpc 解决连接，不控制 AW 何时采集系统事件。

常见排查：

- frpc 认证失败：核对 frp 密钥、版本、serverAddr / serverPort。
- 代理启动失败：检查 remotePort 冲突及 allowPorts。
- 代理成功但 API 无响应：手机 localhost 的 AW 服务、localPort、后台限制。
- HTTP 401/403：检查 AW Token，不能用 frp Token 替代。
- 手机端可用，工作台连不上：看 HTTPS / 防火墙 / 代理监听地址。

字段依据：[frp 官方客户端示例](https://github.com/fatedier/frp/blob/dev/conf/frpc_full_example.toml)、[服务器示例](https://github.com/fatedier/frp/blob/dev/conf/frps_full_example.toml)。模板已按上游字段校核；不同 Android frpc 客户端导入及后台可靠性需在所用版本验证。

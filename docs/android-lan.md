# Android：不需要公网服务器的局域网接入

适用：手机与运行 Screen Time Web 的电脑网络可互通。访客 Wi-Fi / AP 隔离可能阻止互访。

## 1. 手机先准备好 AW

安装 ActivityWatch，授予“使用情况访问权限”，使用几个 App 后回到 AW，确认有使用记录。Android App 的版本和桌面版本不能混为一谈。

找到手机本机 AW 地址（常见为 `http://127.0.0.1:5600`，测试 / research 构建可能使用其他端口），在手机浏览器打开。若启用 AW 接口认证，记录该 AW 的 API Token。

注意三种凭据互不替代：AW Token 访问手机数据，Screen Time Web Token 登录本工作台，frp Token 只验证转发客户端。

## 2. 判断能否直连

手机 Wi-Fi 设置中查看当前 IP，例如 `192.168.1.20`。电脑访问 `http://192.168.1.20:5600`。

- 能访问：工作台“同步与接入”新增 AW 数据源，连接方式选“局域网”，填该地址和 AW Token。
- 不能访问：先确认同一网络、没有 AP 隔离、AW 服务正在运行、端口正确。
- 手机 localhost 可访问，但电脑访问超时 / 拒绝：**不要认为改一个 Web 设置就能解决**。AW 可能仅监听 `127.0.0.1`。

上游 aw-server-rust 默认是 loopback 监听：
https://github.com/ActivityWatch/aw-server-rust/blob/master/aw-server/src/config.rs

若你的 Android AW 版本提供网络监听设置，可按其说明启用局域网监听和接口认证。不要照抄桌面配置路径，Android 的 app 私有文件通常不能用普通文件管理器编辑。

## 3. stock AW 只能 localhost 时：LAN relay（仍无需公网）

此方案复用手机 frpc，让手机主动连电脑的 frps。电脑再从自己的 loopback 端口读取。无需 root / ADB，不要求安装我们自写的 APK。

```
手机 AW 127.0.0.1:5600 ← 手机 frpc → 电脑 frps:7000 → 电脑 127.0.0.1:5601 → Web
```

1. 电脑从官方 frp Releases 下载对应系统的 frps：https://github.com/fatedier/frp/releases 。
2. 复制 `examples/frps.lan.toml` 到电脑的私有配置目录，修改共享密钥。
3. 电脑运行 `frps -c /你的路径/frps.lan.toml`，允许防火墙接受本局域网的 7000/TCP。
4. 手机复制 `examples/frpc.lan.toml`，把 `serverAddr` 改为电脑的 LAN IP；共享密钥与 frps 一致。不要填手机自己的 IP 或 127.0.0.1。
5. 手机客户端导入并启动这份 frpc 配置。具体导入方式见 frpc 教程的“手机配置文件”。
6. 工作台 AW 地址填写 `http://127.0.0.1:5601`，连接方式仍选“局域网”，填的是 **AW Token**。
7. “保存并测试连接”，确认返回正确 hostname 和前台应用桶；再点“立即同步”。

同一 Wi-Fi 下，电脑地址变化后需修改手机 `serverAddr`；建议路由器固定 DHCP 地址。frps 和 frpc 是独立外部程序，本项目不会暗中安装或启动它们。

## 4. 断线与补同步

不在同一网络时同步可能失败，已归档数据保留。网络恢复后再次执行。AW 必须先在手机保存了记录，电脑同步才能补回；不能补回手机从未采集的历史。

设置界面显示最近成功、下一次计划和失败状态。先用“立即同步”验证，再启用自动策略。

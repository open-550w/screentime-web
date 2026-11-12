# Screen Time Web

把 Mac、iPhone / iPad、Android 的使用记录放到一个本地 Web 工作台。
**MIT 开源；不需要公共服务器；数据与凭据保存在自己的设备。**

这是时间统计工具：App 状态区间不代表持续操作或注意力时间。当前不扣除空闲。

## 功能

- 分类 / App 饼图、完整用时排行、日 / 周 / 月趋势。
- 每日首末活动、会话明细；设备时间轴让所有设备共用一条时间刻度。
- 应用重命名、分类配置；生活日默认凌晨 4 点分界，可调整。
- 设备筛选记入 localStorage，页面与筛选同步到 URL，支持刷新和前进后退。
- **同步与接入**：多个 Android ActivityWatch 数据源，局域网或 frpc；连接测试与桶发现。
- **可配置调度**：自动开关、间隔、每天固定时刻、两者组合、时区、启动执行；公共策略或数据源独立策略。
- **JSON 导出 API**：精确时间范围、一个 / 多个 / 所有设备、raw / enriched、完整导出或固定快照分页。
- 全局 Token 保护，跨站 API 使用 Bearer Token；无 CDN、遥测或第三方图表请求。

## 快速开始

需要 Python **3.11+**；macOS / Linux 无 Python 第三方依赖。Windows 需要有 IANA 时区数据，可先运行 `py -m pip install tzdata`。

```sh
# 下载源码 ZIP 并解压，进入项目目录
python3 server.py
```

打开 **http://127.0.0.1:7076/**。首次启动自动创建访问 Token，复制到登录框：

- macOS：`~/Library/Application Support/ScreenTimeWeb/access-token`
- Linux / Windows：`~/.local/share/screentime-web/access-token`
- 可通过 `--state PATH` 自定义私有数据目录。

新用户不需要 Apple 归档，空安装也能进入接入页面。先添加一个 Android 数据源即可使用。
服务默认监听 `0.0.0.0:7076`，允许其他设备通过电脑 IP 访问。仅本机使用可传 `--host 127.0.0.1`。

```sh
python3 server.py --host 127.0.0.1 --port 7076
# Mac 登录启动（Python 路径和源码目录会记录到 launchd；移动目录后重新安装）
python3 install.py
# 需要 Mac / iPhone 采集时，安装可选 Apple 归档程序
python3 install.py --with-apple
```

Apple 归档需要 macOS 14+ 和 Xcode Command Line Tools，详见 [Apple 接入](docs/apple.md)。

## 两种 Android 连接方式

| 方式 | 需要公网服务器？ | 教程 |
|---|---|---|
| 局域网接入 | 不需要 | [局域网教程](docs/android-lan.md) |
| 手机 frpc 转发 | 需要用户自己的 frps 服务 | [手机配置文件逐项教程](docs/android-frpc.md) |

**先确认 AW 的监听地址。** Android AW 可能只监听手机 localhost；同一个 Wi-Fi 不代表电脑能直接读取。教程提供无公网的 LAN relay 兜底方案，复用 frpc，不依赖 root 或 ADB。

保留 ActivityWatch 作为采集器。这一版只调度电脑读取，不会远程更改手机 AW 的采集频率。

## 调度配置

在“同步与接入”修改公共策略。每个数据源可继承公共策略或设置完整独立策略，独立策略不受公共变更影响。
自动关闭仅停止定时任务，仍可手动执行。组合策略合并同一时刻的触发；错过时间只补执行一次，不逐次补跑。
服务停止 / 电脑睡眠时不会同步；恢复后补执行到期任务。固定时刻会受执行耗时和系统休眠影响，不是硬实时保证。

Apple 是一个归档数据源，涵盖本机与 iCloud 同步设备。**不能通过它控制 iCloud 同步频率，或为每台 iCloud 设备分别调度系统同步。**

详见 [调度与迁移](docs/scheduling.md)。

## API 与数据

[完整 API 文档](docs/api.md) · [示例请求](examples/export.py)

```sh
# 在当前 shell 设置 SCREEN_TIME_TOKEN，不要写进脚本或提交到 Git。
curl -H "Authorization: Bearer $SCREEN_TIME_TOKEN" --get \
  --data-urlencode 'start=2026-01-01T04:00:00+08:00' \
  --data-urlencode 'end=2026-01-02T04:00:00+08:00' \
  --data-urlencode 'format=enriched' --data-urlencode 'limit=all' \
  http://127.0.0.1:7076/api/export
```

原始 Apple 归档只读。Android 写入独立的 `android.sqlite`，新增同步保留 AW 原始事件 JSON（含上游提供的 classname）。旧归档未保存的字段不会凭空恢复。
名字和分类保存在独立 `preferences.sqlite`；新数据不覆盖用户编辑。

Token、端点配置和数据库都在私有 `--state` 目录，**不随源码发布**。运行日志不打印请求 Token、完整 URL 查询或事件内容。
HTTP 不提供传输加密；公网使用应配置 HTTPS。frp 控制链路的 TLS 不等于公开 AW API 已是 HTTPS，教程有对应说明。

## 数据口径

- 时区为 Asia/Shanghai；精确 API 查询为 `[start,end)`，选取所有相交会话。凌晨分日不影响精确查询。
- App 累计为所选设备会话相加；设备内去重为各设备区间并集相加，不扣跨设备重叠，可超过 24 小时。
- 分类占比按 App 累计计算；平均每天含所选范围的无记录日。
- 没有记录不能证明没使用，可能是同步延迟或采集未执行。
- 不推断同名 Mac 属于同一物理设备，也不自动删除超长会话。

## 开发与验证

```sh
python3 -m unittest discover -s tests -v
node --check static/app.js
```

源码结构：`server.py` HTTP / 查询、`config_store.py` 私有配置、`sync_manager.py` 调度、`android_sync.py` AW 适配、`export_api.py` 导出、`static/` 前端。

打包时使用 `git archive`，不直接打包工作目录。`scripts/check_release.py --private-state PATH` 可检查发布文件是否误带当前凭据。

## 已知边界与后续 TODO

- Android 仍需授权 AW 并允许必要后台执行。不同 AW 版本的接口认证、存储访问与监听配置存在差异。
- 本项目未附带、未修改 Android AW APK；frpc 模板已按上游字段校核，但每个 Android frpc 客户端的导入界面不同。
- 不做实时屏幕录像、网页正文、聊天内容或身份 / 欺诈判断。
- 可能 TODO：ADB 直接读取、自写精简 APK；**不属于当前实现范围**。
- 后续：系统活动排除、区间对比、异常提示、MCP / AI 简报、配置备份。

## 致谢与许可

MIT，见 [LICENSE](LICENSE)。可选 Apple 归档器来自 [tobias-x/screentime-archive](https://github.com/tobias-x/screentime-archive)，固定版本与原始 MIT 许可保存在 `vendor/apple-archiver/`。
Android 数据来自独立的 [ActivityWatch](https://github.com/ActivityWatch/aw-android)；转发可用独立的 [frp](https://github.com/fatedier/frp)。见 [NOTICE](NOTICE)。

# Mac / iPhone / iPad 的 Apple 归档

Android-only 用户可以跳过本页。

1. 在 macOS 14+ 安装 Xcode Command Line Tools（已有 swiftc 时不必再装）。
2. 运行 `python3 install.py --with-apple`。不存在归档程序时构建 MIT 上游代码；已安装的签名二进制不会被替换。
3. 系统设置 → 隐私与安全性 → 完全磁盘访问权限，添加：
   `~/Library/Application Support/ScreenTimeArchive/bin/screentime-archiver`
4. Mac 与 iPhone / iPad 开启屏幕使用时间的 App 与网站活动、跨设备共享，并使用同一个 Apple 账户。
5. 工作台“同步与接入”应已有 Apple 源，点“立即同步”，查看源卡片是否成功以及设备最新记录。

设置页面可关闭，菜单栏 ScreenTimeBar 可退出。Web 不依赖菜单栏 UI；依赖归档任务生成的数据。

归档仍通过自身 launchd 作业运行，以使用归档二进制获得的完全磁盘访问权限。不要把权限授给整个 Python / Web 服务来规避这一点。

Apple 底层文件不属于稳定公开接口；本项目固定携带上游版本，未承诺所有未来 macOS 兼容。归档器在独立进程中运行，失败不会清空数据库，也不妨碍 Android 数据源。

原始 archive.sqlite 只读使用；默认路径：`~/Library/Application Support/ScreenTimeArchive/archive.sqlite`。iCloud 延迟可能数小时，不通过高频归档强制加速。

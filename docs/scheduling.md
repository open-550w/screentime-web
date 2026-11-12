# 调度、状态与旧版迁移

## 策略

公共配置是默认策略，不是强制总开关。继承源使用公共配置；独立源使用自己的完整配置。因此公共自动关闭时，独立开启的源仍会运行。

- enabled：是否自动执行；不阻止手动执行。
- interval_minutes：1–10080 分钟，按上次任务结束后计时。
- times：每天最多 24 个固定时刻，HH:MM。
- mode：interval、daily、combined；组合时按最早触发，避免同一源并发。
- timezone：IANA 时区，默认 Asia/Shanghai。
- run_on_start：服务启动 / 策略重设时是否立即执行一次。

调度器每五秒检查，按选定时区生成固定时刻；系统睡眠、服务退出或已有长任务会延迟。错过多次只补执行一次。执行失败按策略等待下次，界面保留最近成功和本次错误。

配置与状态写入私有 sync-config.json / sync-status.json。更新策略后数秒内生效；没有运行的服务不能自己按时执行。夏令时跳变的本地时刻按 Python zoneinfo 的时间映射处理，不保证重复执行当地重复小时。

## 分清三个时间

1. 手机 AW 的采集：由 Android / AW 自己负责，本项目不控制。
2. 本项目读取 AW：可配置公共 / 独立策略。
3. iCloud 把 iPhone 记录送到 Mac：由 Apple 决定；本项目只能调度读取已经落到 Mac 的数据。

Apple 按归档程序整批读取，覆盖本机和同步设备，不能假装给每台 iCloud 设备独立控制同步周期。Android 一个 AW 数据源对应一个明确的 Android foreground bucket，可以分别配置。

## 旧版自动迁移

存在 android-source.json 时，首次启动生成新版 sync-config.json，保留地址与 AW Token，并从已有 Android 归档取得名称 / hostname。默认 aw-watcher-android 桶的设备 identity 算法不变，避免把现有手机导成新设备；其他桶的 identity 额外包含桶 ID，避免不同桶事件 ID 相互覆盖。旧文件仍留在私有目录，不删除。

旧 Android 五分钟策略迁为独立策略。旧 Apple 每日 12:30 迁为独立策略；首次自动迁移的启动执行保持开启。

运行 install.py 时：

- 停止并备份旧 local.screentime-web.android-sync LaunchAgent，避免两套定时器叠加。
- 已有 Apple archiver 的签名二进制不重建，保留完全磁盘访问权限。
- 将 Apple LaunchAgent 改为手动触发，统一由 Web 调度器调用；原 plist 备份到 installation-backups。
- Apple LaunchAgent 标签仍保留，因此原菜单栏程序的手动归档按钮仍可使用。

只停止 Web 服务也会停止自动归档调度。若卸载本项目又想恢复原独立 Apple 定时任务，需要恢复备份 plist 后重新 bootstrap，不要仅删除源码目录。

## 源数据保留

AW 首次同步读取可用的完整 foreground bucket；后续回读最近事件之前的 48 小时，更新延长过的会话，按事件 ID 幂等。手动完整回读可用 API full=true。

源端删记录不删除本地归档。同步失败保留上次成功数据。一个数据源的状态不能代替其他数据源状态；请看各卡片而非只看全局“最近归档”。

首次升级到发布版可能需要重新登录网页（会话 Cookie 按服务端口区分）；全局访问 Token 不变。

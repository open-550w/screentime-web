# JSON API（schema_version 1）

所有 API 需要 `Authorization: Bearer <工作台全局Token>`。同源网页登录也可使用 HttpOnly Cookie；跨站读写请用 Bearer，CORS 不开放跨站 Cookie 凭据。

## 按时间 / 设备导出

`GET /api/export`

| 参数 | 说明 |
|---|---|
| start、end | ISO 日期时间；推荐显式 `+08:00` 或 `Z`。左闭右开，查询所有相交会话，范围最多 366 天 |
| devices | 可选，逗号分隔设备 ID。不传代表全部设备；名称不作为唯一标识 |
| format | `raw` 或 `enriched`，默认 enriched |
| limit | 默认 1000；1–5000 为分页；`all` 一次取全部，数据量大时请分页 |
| cursor | 下一页游标；传入后沿用首次快照及筛选，不重新查询。仍可指定 limit |

URL 中 `+` 需编码为 `%2B`。使用 curl `--data-urlencode` 或 URLSearchParams，不能直接把 `+08:00` 拼到 URL 后面。

```sh
curl --get 'http://127.0.0.1:7076/api/export' \
  -H "Authorization: Bearer $SCREEN_TIME_TOKEN" \
  --data-urlencode 'start=2026-01-01T04:00:00+08:00' \
  --data-urlencode 'end=2026-01-02T04:00:00+08:00' \
  --data-urlencode 'format=raw' --data-urlencode 'limit=all'
```

响应包含 `schema_version`、`created_at`（Unix 秒）、`snapshot_id`、`range`、`timezone`、`devices`（含各设备 latest_record）、`records`、`total_count`、`returned_count`、`next_cursor`、`complete`。

分页例：首次 `limit=1000`；后续 `GET /api/export?cursor=<next_cursor>&limit=1000`，直到 `next_cursor` 为 null。快照固定保留 30 分钟，存放在私有数据目录，过期需重新导出；不会因为后台同步插入新会话而改变后续页面。`limit=all` 不静默截断。

### raw：归档原始会话

每条含 `device_id`、`bundle_id`、`start_ts`、`end_ts`、`source`。时间为未经筛选裁切的原始 Unix 秒。查询范围相交即可返回，因此 start_ts 可能早于 start。

`source_events` 在保留过 AW 原始 JSON 时包含 bucket_id 与完整 AW event；`source_payload_available` 表示是否有该 payload。它不代表 Android OS 原始 queryEvents 流。旧版导入没有保存过的 classname 不会凭空补出；Apple 不导出 OS 底层数据库。

### enriched：加工会话

在 raw 基础上增加应用名称、分类、设备名称、平台、`original_start` / `original_end`、裁切后的 `start` / `end`、`duration_seconds`、UTC ISO 时间。

名称 / 分类快照取导出时的配置。跨筛选边界被裁切，**不自动合并跨设备区间，不排除空闲，也不套用生活日分界**。

## 其他读取接口

- `GET /api/meta`：设备、App、分类、最近归档和同步摘要。
- `GET /api/stats?start=...&end=...&devices=...&group=day|week|month`：汇总统计。
- `GET /api/timeline?start=...&end=...&devices=...`：会话时间线，最多三天。
- `GET /api/device-timeline?start=...&end=...`：设备时间轴，最多 366 天。
- `GET /api/sync-config`：公共策略、数据源、有效策略、执行状态；返回 has_token，绝不返回 Token。

## 同步与配置

`POST /api/sync`：`{}` 同步所有已配置源；`{"sources":["source-id"],"full":true}` 对指定源完整回读。自动关闭不影响手动执行。202 只表示任务已受理，需查询 sync-config 中的 running / last_success / error 判断结果。

`POST /api/sync-config`：

- `{"action":"shared","policy":{...}}` 保存公共策略。
- `{"action":"source","source":{...}}` 新增 / 修改源；不提供 id 时生成。Token 留空保留原值，clear_token=true 才清空。

策略字段：enabled、mode（interval/daily/combined）、interval_minutes、times（HH:MM 数组）、timezone（IANA）、run_on_start。

源字段：id、name、type（activitywatch/apple）、schedule_mode（inherit/independent）、schedule。AW 另含 transport（lan/frpc）、url、token、bucket、hostname（可选预期值）。

`POST /api/source-test`：`{"id":"source-id"}` 测试已保存的 AW 源，返回可用 Android 前台桶；不会打印上游凭据或原始异常 URL。

## 状态码

401 未认证；403 Host 或跨站 Cookie 写入被拒绝；400 参数 / 游标 / 范围无效；502 AW 测试失败；503 本地数据库暂不可读。

凭据轮换：停止服务，移走私有 access-token，再启动生成新的 Token，旧会话和导出游标签名随之失效。不要公开 Token 或包含 Token 的初始登录链接。

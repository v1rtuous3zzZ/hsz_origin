# hsz_origin AI 项目说明

修改接口、认证、数据库、ETL 或部署方式时，必须同步更新本文档。

## 范围与边界

- 后端：`hsz-origin-system-api/`；前端：`hsz-origin-system-web/`；中心库：`hsz_origin`。
- 门架源库仅可访问 `10.13.*`，只能执行 `SELECT/SHOW/DESCRIBE/EXPLAIN`；所有业务、日志与任务写入只允许进入中心库。
- `t_legacy_gantry_info` 的 32 条门架是正式采集参考基线；实际计划必须同时按该基线、可达 `10.13.*` 服务器、启用物理门架及有效映射过滤。不可达方向必须明确标记，不补零。

## 认证与接口

`GET /health` 与 `POST /api/v1/auth/login` 匿名；其他 `/api/v1/*` 需要 Bearer JWT。

| 分组 | 接口 |
| --- | --- |
| 系统 | `GET /api/v1/system/database`、`GET /api/v1/system/gantry-summary` |
| 报表 | `/api/v1/reports/*`、`/api/v1/dashboard/*` |
| ETL 日志 | `GET /api/v1/etl/sync-logs`、`GET /api/v1/etl/missing-windows` |
| ETL 任务 | `POST /api/v1/etl/jobs/backfill`、`POST /api/v1/etl/jobs/check`、`POST /api/v1/etl/sync-logs/{sync_id}/repair`、`GET /api/v1/etl/jobs/{job_id}` |

POST 接口只向中心库任务队列写入记录并返回 HTTP 202。禁止在 HTTP 请求、FastAPI startup 或 BackgroundTasks 中读取门架。

## 数据库职责

| 分组 | 表 |
| --- | --- |
| 用户 | `t_user`、`t_user_session`、`t_login_audit` |
| 源与规则 | `t_source_server`、`t_source_db_config`、`t_physical_gantry`、`t_physical_logical_gantry_rel`、`t_stat_rule` |
| ODS/命中 | `t_ods_event_template`、`t_ods_event_YYYYMM`、`t_event_object_match_template`、`t_event_object_match_YYYYMM` |
| 事实 | `t_fact_flow_*`、`t_fact_local_entry_flow_*`、`t_fact_vehicle_type_*`、`t_fact_source_station_*` |
| ETL | `t_etl_sync_log`、`t_etl_manual_job` |

`trade_id` 即门架原始 `TradeId`，全渠道唯一。各 ODS 月表必须有该字段的唯一约束。迁移脚本是 `hsz-origin-system-api/migrations/20260723_simplify_etl.sql`，不得只手工改库。

## 同步规则

- 核心函数是 `sync_window(server_code,start,end,operation,force=False)`；operation 仅有 `LIVE/BACKFILL/REPAIR/CHECK`。
- 所有 CLI/API/timer 的同步、检查和补数入口只向中心任务表入队；唯一常驻 `worker` 串行读取门架并处理服务器和窗口。不使用分布式锁、命名锁、父子批次、checkpoint、递归拆窗或成功区间拼接。
- 每次实际窗口循环 INSERT 一条新 `t_etl_sync_log`；旧日志永不复用。BACKFILL 命中既有 COMPLETE 时也新增 SKIPPED 日志。
- 当前自然月只读实时表；过去自然月只读对应历史月表；统一使用 `Asia/Shanghai`。不自动双表扫描，不用十分钟交易片段推断完整性。
- 源 SQL 必须保留原始 `TransTime >= start AND TransTime < end AND GantryId IN (...)`。读取前以 SHOW/EXPLAIN 判断真实执行计划，不硬编码索引名或固定索引顺序。
- 源端流式 `fetchmany`，按 TradeId 去重，读完立即关闭连接。仅瞬时网络错误在初次失败后最多重试两次，间隔 2 秒、5 秒；表、字段、配置和索引问题不重试。
- CHECK 投影只选择 TradeId，GantryId 与 TransTime 仅用于 WHERE，不读取业务字段。完整性唯一算法是源端 TradeId 集合减中心 trade_id 集合；中心额外数据不算缺失，源端零行是 COMPLETE。
- 非 CHECK 在关闭门架连接后标准化并写 ODS 与规则命中。中心重试只复用内存快照，禁止重新访问门架。
- 事实重建统一由 task runner 执行：LIVE 同一两小时窗口全部目标服务器 COMPLETE 后重建一次；REPAIR 一个任务全部 COMPLETE 后重建一次；BACKFILL 仅在最新日志证明整自然月、全部启用可采集服务器窗口均 COMPLETE 后重建该月一次；CHECK 不重建事实。
- `missing-windows` 以服务器、开始和结束时间分组，只取最新有效日志；新 COMPLETE 会覆盖旧 MISSING 的页面状态，但不会修改旧日志。

默认配置：

```env
HSZ_ETL_SOURCE_BATCH_SIZE=2000
HSZ_ETL_MAX_WORKERS=1
HSZ_ETL_SOURCE_RETRIES=2
HSZ_ETL_HISTORY_WINDOW_MINUTES=120
HSZ_ETL_SLEEP_SECONDS=5
HSZ_ETL_CENTER_RETRIES=2
```

## 运行与部署

```powershell
python -m app.etl.cli live-once
python -m app.etl.cli live
python -m app.etl.cli backfill --start 2026-01-01T00:00:00 --end 2026-02-01T00:00:00
python -m app.etl.cli nightly-check --days 1 2
python -m app.etl.cli repair --sync-id <sync_id>
python -m app.etl.cli worker
```

生产运行 FastAPI、两小时实时入队 timer、唯一的 ETL worker 和每天 04:30 的夜检入队 timer。实时与夜检 timer 不直接连接门架；只有 `python -m app.etl.cli worker` 消费全部 LIVE/BACKFILL/REPAIR/CHECK。三年历史初始化应逐月提交；可通过不启用 nightly-check timer 暂时关闭夜检。

## 前端设计

前端唯一视觉规范是 `hsz-origin-system-web/DESIGN.md`。同步日志页展示唯一窗口日志与最新缺失窗口，沿用 Element Plus 和既有 IBM Carbon 令牌。

## 验证

```powershell
cd hsz-origin-system-api
.venv\Scripts\ruff.exe check .
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m app.etl.cli --help
cd ..\hsz-origin-system-web
npm run build
```

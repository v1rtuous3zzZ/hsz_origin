# hsz_origin AI 项目说明

修改接口、认证、数据库、ETL 或部署方式时，必须同步更新本文档。

## 范围与边界

- 后端：`hsz-origin-system-api/`；前端：`hsz-origin-system-web/`；中心库：`hsz_origin`。
- 源库仅可访问 `10.13.*`，仅允许只读查询；生产写入仅限中心库 `10.13.0.223/hsz_origin`。
- `t_physical_gantry.collection_enabled=1` 的 32 条门架是本项目正式采集范围；当前可达服务器覆盖其中 26 条，另 6 条属于不可达网段。

## 认证与接口

`GET /health` 与 `POST /api/v1/auth/login` 匿名；其他 `/api/v1/*` 接口需要 Bearer JWT。

| 分组 | 接口 |
| --- | --- |
| 系统 | `GET /api/v1/system/database`、`GET /api/v1/system/gantry-summary` |
| 报表选项 | `GET /api/v1/reports/options`、`GET /api/v1/reports/directions?flow=entry|exit` |
| 报表 | `GET /api/v1/reports/entry-flow`、`exit-flow`、`local-entry-station-flow`、`vehicle-types`、`media-vehicle-types`、`entry-stations`、`entry-provinces` |
| 数据大屏 | `GET /api/v1/dashboard/latest-range`、`route-stack`、`direction-flow`、`local-station-flow`、`section-rank`、`vehicle-type-ratio`、`province-summary` |
| ETL | `GET /api/v1/etl/batches`、`POST /api/v1/etl/manual-sync`、`GET /api/v1/etl/manual-sync-jobs/{job_id}` |

`POST /api/v1/etl/manual-sync` 只写入中心库任务队列并返回 HTTP 202，禁止在 HTTP 请求、FastAPI startup 或 BackgroundTasks 中执行同步。

## 数据库职责

| 分组 | 表 |
| --- | --- |
| 用户 | `t_user`、`t_user_session`、`t_login_audit` |
| 源配置 | `t_source_server`、`t_source_db_config`、`t_physical_gantry` |
| 门架规则 | `t_logical_gantry`、`t_physical_gantry`、`t_physical_logical_gantry_rel`、`t_stat_object`、`t_stat_rule` |
| 字典 | `t_toll_station`、`t_vehicle_type_dict`、`t_local_entry_station` |
| ODS/命中 | `t_ods_event_template`、`t_ods_event_YYYYMM`、`t_event_object_match_template`、`t_event_object_match_YYYYMM` |
| 事实 | `t_fact_flow_*`、`t_fact_local_entry_flow_*`、`t_fact_vehicle_type_*`、`t_fact_source_station_*` |
| ETL | `t_etl_batch`、`t_etl_batch_source`、`t_etl_manual_job`、`t_etl_checkpoint`、`t_etl_quality`、`t_data_freshness` |
| 配置 | `t_system_config` |

`t_etl_manual_job` 仅存在于中心库，由 API 首次入队或 worker 启动时以 `CREATE TABLE IF NOT EXISTS` 创建；所有字段、索引和表均带中文 `COMMENT`。

## 同步规则

- 正式入口为 `app.etl.cli`，支持 `live-once`、常驻 `live`、循环 `backfill`、后台任务 `worker` 和仅中心库执行的 `rebuild-facts`。
- 实时窗口固定对齐两小时并减去安全延迟；已有成功窗口时不访问门架。
- 实时同步固定按两小时记录窗口，默认最多并行读取 4 台不同 IP 的物理服务器。历史手动补数采用独立低压力配置：默认 120 分钟窗口、单 worker、源游标每批 2000 行、窗口间休眠 10 秒；CLI 与 HTTP 请求的显式参数可覆盖默认值，HTTP 任务会持久化并由 worker 使用实际参数。
- 同一时间窗口重复执行时复用原 `t_etl_batch`，逐源结果按 `batch_id + source_server_id` 覆盖更新；失败源补齐后原批次从 `PARTIAL/FAILED` 更新为 `SUCCESS`，不新增第二条同窗口日志。
- 同步分为门架采集与中心处理两个阶段。源连接读取完成立即关闭；中心处理失败复用内存快照，不重新查询门架。
- 实时、历史、手动 worker 与凌晨核对共享 `GET_LOCK('hsz:etl:source-read')`，只串行化门架读取阶段；获得锁后会从中心库二次检查成功覆盖，仅读取等待期间仍未完成的服务器，全部完成则不创建或重置批次。
- 不同物理服务器按 `HSZ_ETL_MAX_WORKERS` 可控并行，同一 IP 始终串行。
- 源查询必须保留 `GantryId IN (...)` 与原始 `TransTime >= ... AND TransTime < ...`，禁止包装索引列或无界扫描。
- 过去月份 `HISTORY` 只读对应历史月表。当前月最近窗口 `AUTO` 只读实时表；因为源库没有可靠水位字段，低流量或零交易不再被当作数据不完整，也不会在每次实时同步中扫描两张表。明确指定 `MIXED` 时仍按 TradeId 去重，实时表优先、历史表仅补缺失交易。该策略的局限是当前月实时表迟到/淘汰数据由凌晨核对发现，不在每次实时任务中双表确认。
- 历史表读取前用只读 `SHOW INDEX` 检查索引前缀 `(GantryId, TransTime)`，结果按服务器和表缓存；缺索引时拒绝历史大范围同步。实时表缺索引默认高等级告警，可用 `HSZ_ETL_SOURCE_INDEX_LIVE_POLICY=FAIL` 改为拒绝。系统绝不在门架源库创建或修改索引。
- 源读取默认最多尝试 3 次，仅对网络超时、连接中断等临时错误重试，间隔 2 秒、5 秒；字段/表/配置/索引错误立即终止。历史查询超时可二分窗口，最低 30 分钟；实时两小时窗口不拆分。
- 源连接的 host、port、database 始终取 `SourceServer`；账号密码优先取 `credential_key` 对应的环境变量。环境凭据缺失时仅允许回退到唯一一条公共 `t_source_db_config` 凭据，禁止用最早记录隐式匹配服务器。
- 每个源服务器的 ODS、命中、源批次和断点使用独立中心库事务并立即提交；事实重建与主批次汇总各自使用独立事务。中心重试复用已采集快照并跳过已经成功提交的源，不重新读取门架或重复大批量写入。
- 历史补数全部窗口成功后按月重建事实，不在每个窗口重复重建。
- 中心库明细默认每 10000 行批量写入；生产 MySQL 应为 ETL 工作集配置足够的 InnoDB Buffer Pool 和 Redo Log，不能沿用 128 MiB Buffer Pool 的开发默认值。
- HTTP 手动同步由 `python -m app.etl.cli worker` 消费。worker 每个窗口更新任务心跳；超过 `HSZ_ETL_MANUAL_JOB_STALE_MINUTES` 未更新的 RUNNING 任务可重新入队。
- 凌晨核对先在中心库筛选 FAILED/PARTIAL/MISSING、中心计数为零及最近一天可能迟到的候选窗口，只访问候选服务器/表/范围；过去月份只读历史月表。dry-run 不连接门架，直接列出计划访问项，并继续受最大修复窗口数限制。

三年历史初始化建议从最早月份开始分段执行，默认即为低压力参数：

```powershell
python -m app.etl.cli backfill --start 2023-01-01T00:00:00 --end 2026-01-01T00:00:00
```

## 部署

生产至少运行：

1. FastAPI Web 服务；
2. `python -m app.etl.cli live` 实时同步进程，或等价的两小时 systemd timer；
3. `python -m app.etl.cli worker` 手动任务消费进程；
4. 每天 04:30 的凌晨核对任务。

`requirements.txt` 必须包含 `tzdata`，保证 Windows、CI 和精简容器能加载 `Asia/Shanghai`。时区不得在模块导入阶段初始化。

## 前端设计

前端唯一视觉规范是 `hsz-origin-system-web/DESIGN.md`。规范以 IBM Carbon 为基础，适用于内网报表后台。

## 验证

```powershell
cd hsz-origin-system-api
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\ruff.exe check .
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m app.etl.cli --help
```

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
- 历史补数默认两小时一个窗口，跨月切分、断点续跑、窗口间休眠；过去月份直接读取历史月表。
- 同步分为门架采集与中心处理两个阶段。源连接读取完成立即关闭；中心处理失败复用内存快照，不重新查询门架。
- 实时、历史、手动 worker 与凌晨核对共享 `GET_LOCK('hsz:etl:source-read')`，只串行化门架读取阶段。
- 不同物理服务器按 `HSZ_ETL_MAX_WORKERS` 可控并行，同一 IP 始终串行。
- 源查询必须保留 `GantryId IN (...)` 与原始 `TransTime >= ... AND TransTime < ...`，禁止包装索引列或无界扫描。
- 实时表优先，历史表仅补不存在的 `TradeId`；中心 ODS 与命中表依靠唯一键幂等。
- 历史补数全部窗口成功后按月重建事实，不在每个窗口重复重建。
- HTTP 手动同步由 `python -m app.etl.cli worker` 消费。worker 每个窗口更新任务心跳；超过 `HSZ_ETL_MANUAL_JOB_STALE_MINUTES` 未更新的 RUNNING 任务可重新入队。

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

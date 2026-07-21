# hsz_origin AI 项目说明

修改接口、认证、数据库、ETL 或部署方式时，必须同步更新本文档。

## 范围与边界

- 后端：`hsz-origin-system-api/`；前端：`hsz-origin-system-web/`；中心库：`hsz_origin`。
- 源库仅可访问 `10.13.*`，仅允许只读查询；生产写入仅限中心库 `10.13.0.223/hsz_origin`。
- `t_physical_gantry.collection_enabled=1` 的 32 条门架是本项目正式采集范围；当前 `10.13.*` 可达服务器覆盖其中 26 条，另 6 条属于不可达网段。入口 8 个外部来向可用；出口仅 G50 两个方向可用，其他出口必须标记 `UNAVAILABLE`。G50 的上海方向入口/出口分别使用苏沪边界门架 `2A2C01`/`2B2C01`，浙江方向入口/出口分别使用苏浙边界门架 `2B2C09`/`2A2C09`。

## 认证与接口

`GET /health` 与 `POST /api/v1/auth/login` 匿名；其他 `/api/v1/*` 接口需要 Bearer JWT。JWT 无服务端会话限制，支持同账号多端登录。

| 分组 | 接口 |
| --- | --- |
| 系统 | `GET /api/v1/system/database`、`GET /api/v1/system/gantry-summary` |
| 报表选项 | `GET /api/v1/reports/options`、`GET /api/v1/reports/directions?flow=entry|exit` |
| 报表 | `GET /api/v1/reports/entry-flow`、`exit-flow`、`local-entry-station-flow`、`vehicle-types`、`media-vehicle-types`、`entry-stations`、`entry-provinces` |
| 数据大屏 | `GET /api/v1/dashboard/latest-range`、`route-stack`、`direction-flow`、`local-station-flow`、`section-rank`、`vehicle-type-ratio`、`province-summary` |
| ETL | `GET /api/v1/etl/batches?start=&end=`、`POST /api/v1/etl/manual-sync` |

## 数据库职责

| 分组 | 表 |
| --- | --- |
| 用户 | `t_user`、`t_user_session`、`t_login_audit` |
| 源配置 | `t_source_server`、`t_source_db_config`、`t_physical_gantry` |
| 门架规则 | `t_logical_gantry`、`t_physical_gantry`、`t_physical_logical_gantry_rel`、`t_stat_object`、`t_stat_rule` |
| 字典 | `t_toll_station`、`t_vehicle_type_dict`、`t_local_entry_station` |
| ODS/命中 | `t_ods_event_template`、`t_ods_event_YYYYMM`、`t_event_object_match_template`、`t_event_object_match_YYYYMM` |
| 事实 | `t_fact_flow_*`、`t_fact_local_entry_flow_*`、`t_fact_vehicle_type_*`、`t_fact_source_station_*` |
| ETL | `t_etl_batch`、`t_etl_batch_source`、`t_etl_checkpoint`、`t_etl_quality`、`t_data_freshness` |
| 配置 | `t_system_config` |

表、字段、索引或存储过程变更必须有中文 `COMMENT`，并更新本节。

## 同步规则

- 正式入口为 `app.etl.cli`，支持 `live-once`、常驻 `live`、循环 `backfill` 和仅中心库执行的 `rebuild-facts`。`scripts/run_live_sync.py` 保留给原 systemd timer，`scripts/run_sync.py` 为统一包装。
- 实时窗口固定对齐两小时，并减去安全延迟；例如 10:15 同步 08:00–10:00。循环任务每次先查中心批次，已有成功窗口时不访问门架。
- 历史补数默认两小时一个窗口，跨月自动切分，成功窗口自动跳过，窗口之间休眠。过去月份直接读取历史月表；当前月份先读实时表，仅为覆盖不完整的物理门架补读月表。
- 同步分为“门架采集”和“中心处理”两个阶段。源连接只负责有界范围明细读取，读取完成立即关闭；标准化、按 `TradeId` 去重、ODS/命中分批写入和事实重建均在中心库执行。
- 源读取失败只重试对应源；中心库处理失败复用已经采集的内存快照，不得重新查询门架。
- 实时同步与历史补数通过中心库 `GET_LOCK('hsz:etl:source-read')` 只串行化门架采集阶段，防止两个进程同时压源库；中心处理阶段立即释放该锁。不同 IP 可按 `HSZ_ETL_MAX_WORKERS` 并行，同一 IP 必须串行。
- 断点续跑按源服务器判断。一个窗口部分成功后，后续循环只读取尚未成功的源服务器，不重复读取已成功源。
- 源查询必须保留 `GantryId IN (...)` 与原始 `TransTime >= ... AND TransTime < ...`，利用现有 `(GantryId, TransTime, ...)` 范围索引；禁止包装索引列或无界扫描。
- ODS 事件键为 `SHA-256(source_server_id|source_trade_id)`；实时表优先，历史表仅补不存在的 `TradeId`。中心 ODS 和命中表依靠唯一键保证重复窗口幂等。
- 历史补数不在每个窗口重建事实；全部窗口成功后按月统一重建。事实重建失败只重试中心库阶段。
- 批次写 `t_etl_batch`，逐源写 `t_etl_batch_source`。`source_row_count` 表示实时表与月表按 `TradeId` 去重后的源事件数。

## CentOS 8

推荐二选一：

1. systemd timer 每两小时第 15 分钟执行 `python scripts/run_live_sync.py`；
2. systemd service 常驻执行 `python -m app.etl.cli live`。

历史补数使用独立命令 `python -m app.etl.cli backfill --start ... --end ...`。即使与实时任务同时启动，门架采集锁也会避免并发读取源库；实时任务可在历史窗口之间取得锁。

另有每天 04:30 的核对任务，比较最近 7 个完整自然日源端与中心 ODS 唯一事件数，只补不一致的源服务器窗口；单晚最多 24 个。

## 前端设计

前端唯一视觉规范是 `hsz-origin-system-web/DESIGN.md`。规范以 IBM Carbon 为基础，适用于内网报表后台；不得另建冲突的颜色、字体、圆角、阴影或间距体系。

## 验证

```powershell
cd hsz-origin-system-api
.venv\Scripts\ruff.exe check .
.venv\Scripts\python.exe -m pytest
```

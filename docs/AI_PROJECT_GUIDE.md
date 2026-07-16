# hsz_origin AI 项目说明

修改接口、认证、数据库、ETL 或部署方式时，必须同步更新本文档。

## 范围与边界

- 后端：`hsz-origin-system-api/`；前端：`hsz-origin-system-web/`；中心库：`hsz_origin`。
- 源库仅可访问 `10.13.*`，仅允许只读查询；生产写入仅限中心库 `10.13.0.223/hsz_origin`。
- `t_legacy_gantry_info` 的 32 条门架是实际采集基线。入口 8 个方向可用；出口仅 G50 两个方向可用，其他出口必须标记 `UNAVAILABLE`。

## 认证与接口

`GET /health` 与 `POST /api/v1/auth/login` 匿名；其他 `/api/v1/*` 接口需要 Bearer JWT。JWT 无服务端会话限制，支持同账号多端登录。

| 分组 | 接口 |
| --- | --- |
| 系统 | `GET /api/v1/system/database`、`GET /api/v1/system/gantry-summary` |
| 报表选项 | `GET /api/v1/reports/options`、`GET /api/v1/reports/directions?flow=entry|exit` |
| 报表 | `GET /api/v1/reports/entry-flow`、`exit-flow`、`vehicle-types`、`entry-stations` |
| ETL | `GET /api/v1/etl/batches`、`POST /api/v1/etl/manual-sync` |

报表共用参数：`start`、`end`、`granularity=hour|day|week|month|year`、可重复 `direction_ids`、`page`、`page_size`。车型名称由前端枚举；入口站名称缺失返回“未知”。

## 数据库职责

| 分组 | 表 |
| --- | --- |
| 用户 | `t_user`、`t_user_session`、`t_login_audit` |
| 源配置 | `t_source_server`、`t_source_db_config`、`t_legacy_gantry_info` |
| 门架规则 | `t_logical_gantry`、`t_physical_gantry`、`t_physical_logical_gantry_rel`、`t_stat_object`、`t_stat_rule` |
| 字典 | `t_toll_station`、`t_vehicle_type_dict`、`t_base_facility_catalog`、`t_base_gantry_catalog`、`t_network_entry_station_rel` |
| ODS/命中 | `t_ods_event_template`、`t_ods_event_YYYYMM`、`t_event_object_match_template`、`t_event_object_match_YYYYMM` |
| 事实 | `t_fact_flow_*`、`t_fact_vehicle_type_*`、`t_fact_source_station_*` |
| ETL | `t_etl_batch`、`t_etl_batch_source`、`t_etl_checkpoint`、`t_etl_quality`、`t_data_freshness` |
| 配置 | `t_system_config` |

表、字段、索引或存储过程变更必须有中文 `COMMENT`，并更新本节。

## 同步规则

- 手动同步按连续两小时窗口，跨月切分。
- 每个窗口每源先读实时表 `dfs_gantry_transaction`，再读月表 `dfs_gantry_transactionYYYYMM`。
- 同源按 `TradeId` 去重；中心事件键为 `SHA-256(source_server_id|source_trade_id)`，物理表名不参与幂等。
- 禁止用固定 7 天阈值决定只读哪张表，归档可在运行中切换。
- 批次写 `t_etl_batch`，逐源明细写 `t_etl_batch_source`，全成功后推进 `t_etl_checkpoint`。

## CentOS 8

Web 与 ETL 分离。推荐 systemd timer 每两小时第 15 分钟启动独立 ETL 脚本；timer 是操作系统调度，不是项目内定时器。调度脚本应按断点、延迟时间和 MySQL `GET_LOCK` 运行，不能调用 HTTP 手动同步接口。

## 验证

```powershell
cd hsz-origin-system-api
.venv\Scripts\ruff.exe check .
.venv\Scripts\python.exe -m pytest
```

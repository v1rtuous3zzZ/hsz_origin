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
| ETL | `GET /api/v1/etl/batches?start=&end=`（按区间查看批次与同步覆盖缺口）、`POST /api/v1/etl/manual-sync` |

报表共用参数：`start`、`end`、`granularity=hour|day|week|month|year`、`page`、`page_size`。方向报表使用可重复 `direction_ids`；本路段数据统计使用可重复 `station_ids`。车型名称由 `t_vehicle_type_dict` 返回；入口站名称缺失返回“未知”。介质车型统计按 ODS 的 `media_type` 分类：`1` 为 OBU、`2` 为 CPC，其他或空值归为“无介质”。入口省份统计的 `province_code` 同样取自 `t_toll_station`；站点或省份编码无法匹配时返回 `UNKNOWN`。

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

- 手动同步按连续两小时窗口，跨月切分。
- 同一同步窗口最多并行读取 4 个门架源库。源连接只负责读取原始明细，读取完成后立即关闭；标准化、规则匹配、ODS/命中写入和事实重建均在中心库执行。同步不使用跨任务 MySQL 命名锁，ODS 与命中表依靠唯一事件键幂等；大范围历史补数默认不重建事实，避免与实时事实重建互相覆盖。
- 单个两小时窗口读取或重建失败时，立即完整重试一次；第二次失败则保留失败批次记录并继续下一个窗口。定时同步同样遵循该规则，下一次调度仍可正常执行。
- 历史补数按多个两小时窗口执行时应延后事实重建；全部窗口写入成功后，再按月份统一重建事实表。实时窗口的小时、日事实从当月命中明细重建，月事实从中心库日事实汇总，禁止每两小时重复扫描整月命中明细。
- 每个窗口每源先读实时表 `dfs_gantry_transaction` 的 `collection_enabled=1` 门架数据，并按每一条物理门架分别检查两小时的 12 个十分钟片段。某门架实时数据不完整或为空时，仅为该门架查询对应历史月表 `dfs_gantry_transactionYYYYMM`，再按 `TradeId` 去重合并；不得因同一服务器的其他门架数据连续而跳过该门架的历史查询。该规则避免正常门架双查，也覆盖实时表部分回补、两表同时存在或实时表已清理的窗口。
- 同源按 `TradeId` 去重；中心事件键为 `SHA-256(source_server_id|source_trade_id)`，物理表名不参与幂等。
- 入口流量在 8 个外部来向外，额外提供“本路段收费站来源”（方向 ID `199`）。它由 `t_local_entry_station` 配置的 6 个收费站识别，并按 `event_key` 去重；每次事实重算都同步重建该来源的小时、日、月事实。
- 批次写 `t_etl_batch`，逐源明细写 `t_etl_batch_source`，全成功后推进 `t_etl_checkpoint`。

## CentOS 8

Web 与 ETL 分离。生产 systemd timer 每两小时第 15 分钟启动独立 ETL 脚本；按 `Asia/Shanghai` 计算刚完整结束的两小时窗口（例如 10:15 同步 08:00–10:00），跨月拆分。另有每天 04:30（`Asia/Shanghai`）的核对任务，比较最近 7 个完整自然日的源端两小时计数与中心入库计数，只补不一致的源服务器窗口；单晚最多 24 个，避免占满门架源库。timer 是操作系统调度，不是项目内定时器；调度脚本不能调用 HTTP 手动同步接口。

## 前端设计

前端的唯一视觉规范是 `hsz-origin-system-web/DESIGN.md`。该规范以 IBM Carbon 为基础，已经针对本项目的内网报表后台场景定制；所有 UI 改动必须先阅读并遵循。不得照搬 IBM 官网营销页结构，也不得另建冲突的颜色、字体、圆角、阴影或间距体系。

核心原则：IBM Blue、方角、无阴影、细边框、紧凑表格、固定企业后台布局、内网离线资源和桌面端适配。

前端固定路由为 `/login`、`/dashboard`、`/reports/entry-flow`、`/reports/exit-flow`、`/reports/local-entry-station-flow`、`/reports/vehicle-types`、`/reports/media-vehicle-types`、`/reports/entry-stations`、`/reports/entry-provinces` 和 `/sync-logs`。登录后默认进入 `/reports/entry-flow`，数据大屏仅通过独立菜单进入；大屏通过 `latest-range` 使用事实表最新有数据的自然日。数据大屏复用旧系统深色大屏素材与 ECharts 样式；预测模块暂不接入，断面流量排名不改同步脚本和数据库结构，按 `t_ods_event_YYYYMM.current_physical_gantry_code` 聚合已同步成功事件并关联 `t_physical_gantry.collection_enabled=1` 的本项目采集门架。本路段数据统计按收费站展示行、按时间展示列，并包含合计。同步日志页按选中区间显示批次执行状态；手动同步会等待所选窗口全部执行结束，页面不展示实时进度也不自动刷新，维护者可稍后手动查询日志。“缺失”只表示两小时窗口未被成功批次完整覆盖，不等同于源库没有交易数据。认证 Token 仅存于浏览器 `sessionStorage`；报表选项在会话中缓存。Excel 导出接口和密码修改接口尚未提供，前端不得虚构对应能力。

生产前端构建由 `hsz-origin-system-web/.env.production` 固定 `VITE_API_BASE_URL=/api/v1`，必须通过 Nginx `/api/` 反向代理访问 API；不得把本机开发地址编译进生产包。

## 验证

```powershell
cd hsz-origin-system-api
.venv\Scripts\ruff.exe check .
.venv\Scripts\python.exe -m pytest
```

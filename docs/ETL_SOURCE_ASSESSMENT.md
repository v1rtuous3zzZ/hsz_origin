# ETL 门架源评估

评估时间：2026-07-23。所有门架查询均为只读；本文不记录账号、密码或连接串。

## 数据库与表

- 中心库：MySQL 8.0.46。
- 8 台可达门架服务器：MySQL 8.0.32。
- 实时表：`dfs_gantry_transaction`。
- 历史月表：`dfs_gantry_transactionYYYYMM`，例如 `dfs_gantry_transaction202606`。
- 必需字段实测为 `TradeId`、`GantryId`、`TransTime`；同步业务字段还包括 `VehiclePlate`、`VehicleType`、`MediaType`、上一门架候选、入口站/时间和交易结果字段。
- `TradeId` 是源表主键；实时表和 202606 历史表均存在以 `GantryId, TransTime` 开头的多个复合索引，但索引名和优化器选择并不固定。

SHOW TABLE STATUS 的近似行数：

| 服务器 | 实时表 | 202606 历史表 |
| --- | ---: | ---: |
| 10.13.10.4 | 432,643 | 1,658,865 |
| 10.13.15.4 | 366,424 | 1,518,585 |
| 10.13.20.4 | 434,696 | 1,823,814 |
| 10.13.25.4 | 1,288,458 | 5,971,910 |
| 10.13.30.4 | 504,688 | 2,115,549 |
| 10.13.35.4 | 611,129 | 2,182,033 |
| 10.13.40.4 | 220,345 | 1,081,217 |
| 10.13.5.4 | 253,016 | 2,763,112 |

8 台服务器的两类表均有以下与时间有关的索引结构（历史表索引名前缀带月份）：

- `_01 (GantryId, TransTime, DealStatus)`；
- `_02 (GantryId, TransTime, MUploadFlag, UploadFlag, DealStatus)`；
- `_11 (ChargeUnitId, TransTime, DealStatus)`；
- `_12 (ChargeUnitId, TransTime, MUploadFlag, UploadFlag, DealStatus)`。

## EXPLAIN

对 8 台服务器分别执行以下有界 SQL 的 EXPLAIN：

```sql
SELECT TradeId, GantryId, TransTime
FROM <单个实时表或历史月表>
WHERE TransTime >= :start
  AND TransTime < :end
  AND GantryId IN (...);
```

实时表均为 `type=range`，实际 key 为各表 `_01`，估算 rows 为 5,764–41,362；
202606 历史表均为 `type=range`，实际 key 由优化器选择 `_01` 或 `_02`，估算 rows 为
8,554–46,512。全部为 `Extra=Using where; Using index`。因此代码依据 EXPLAIN 的
`key/type` 判断，不限定某个索引名，也不要求只接受一个固定索引定义。

## 两小时样本

## TradeId 字段实测

2026-07-23 重新执行只读有界探测。实时表窗口为 `2026-07-22 00:00:00`
至 `2026-07-22 02:00:00`，覆盖 8 台 `10.13.*` 服务器、每台最多 3 个实际
`GantryId`。历史月表样本为 `dfs_gantry_transaction202606` 与
`dfs_gantry_transaction202601`，窗口均为当月 15 日 00:00 至 02:00，覆盖
`legacy_10_13_10_4` 与 `legacy_10_13_15_4`。

- 实时表和历史月表 `TradeId` 字段类型一致：`varchar(38)`、`Null=NO`、`Key=PRI`。
- 有数据样本实际长度固定为 35；未发现 NULL、空字符串或非 ASCII 字符。
- `COUNT(DISTINCT TradeId)` 与 `COUNT(DISTINCT BINARY TradeId)` 一致，未发现大小写折叠导致的重复。
- 202607 历史月表在所选窗口无数据，但字段定义仍与实时表一致。
- 中心库最终字段定义采用 `trade_id VARCHAR(38) CHARACTER SET ascii COLLATE ascii_bin NOT NULL`，保留源字段上限，不用 SHA256 派生键。

服务器 `legacy_10_13_10_4`，窗口 `2026-06-15 08:00:00` 至 `10:00:00`，源表
`dfs_gantry_transaction202606`：8,016 行，8,016 个唯一 TradeId，重复 0；使用流式
游标、每批 2,000 行读取完整业务字段，耗时约 2,733 ms。该结果支持使用两小时内存
快照和中心分批 IN 校验。

## 最终读取规则与参数

- 当前自然月只读实时表；过去自然月只读对应历史月表。
- 查询始终包含半开时间范围和服务器实际 GantryId 列表。
- CHECK 投影只选择 TradeId；GantryId 与 TransTime 仅用于有界 WHERE 条件。同步选择标准化需要的业务字段。
- 默认窗口 120 分钟、源批量 2,000、单 worker、窗口休眠 5 秒、瞬时源错误最多两次重试。BACKFILL 仅接受 Asia/Shanghai 偶数整点边界；任务领取优先级为 LIVE、REPAIR、CHECK、BACKFILL，systemd 以本机 `flock` 防止第二个 worker 并发读取门架。

## 尚存风险

- 评估只覆盖当前实时表和 202606 历史表；三年初始化前应按月份抽查更早历史表的字段与 EXPLAIN。任何历史月表无可用索引时必须停止该月同步并由数据库管理员处理。
- 当前月固定读取实时表，不回退历史表；若源系统在月内提前淘汰实时数据，该窗口会按源表当时可见 TradeId 判定，程序不会猜测理论应有数据。
- 当前可达范围仅为 `10.13.*` 配置服务器；不可达网段不记为采集失败。

## 旧 ETL 依赖审计

重构前后端 `/etl/batches` 直接读取 `t_etl_batch/t_etl_batch_source`，旧
`formal_sync/orchestrator/reconcile/source_coverage` 还引用批次、源批次和 checkpoint；
前端同步日志页也调用旧批次、手工同步和失败源重试接口。此次已同步替换 API、页面、
CLI、systemd 脚本和测试，因此迁移可删除 `t_etl_batch`、`t_etl_batch_source`、
`t_etl_checkpoint`、`t_etl_quality`、`t_data_freshness`，不保留旧运行兼容层。

## 真实单窗口验证

中心写入使用允许联调的 `192.168.1.109/hsz_origin`，门架源始终只读。验证服务器为
`legacy_10_13_10_4`，历史窗口为 2026-06-15 08:00–10:00，EXPLAIN key 为
`dfs_gantry_transaction202606_02`。

| 步骤 | 源唯一数 | 中心匹配 | 缺失 | 源查询 | 写入 | 校验 | 总耗时 | 结果 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 首次 CHECK | 8,016 | 0 | 8,016 | 1,517 ms | 0 | 53 ms | 1,586 ms | MISSING |
| REPAIR | 8,016 | 8,016 | 0 | 2,487 ms | 1,653 ms | 161 ms | 4,407 ms | COMPLETE |
| 再次 CHECK | 8,016 | 8,016 | 0 | 1,418 ms | 0 | 97 ms | 1,528 ms | COMPLETE |
| 重复 REPAIR | 8,016 | 8,016 | 0 | 2,410 ms | 873 ms | 163 ms | 3,544 ms | COMPLETE |

重复 REPAIR 后中心范围仍为 8,016 行、8,016 个唯一 TradeId，未产生重复数据。
另通过 CLI 提交 `BACKFILL-cde531f3a91a4b36`，确认命令只生成 PENDING 任务；随后唯一
worker 消费 1 个窗口，任务进度为 total=1、processed=1、complete=1、failed=0，生成
新的 BACKFILL 日志 `bfce1a58-8883-4c52-aa2f-f06e5caf7bd1`。该次源查询 2,539 ms、
幂等写入 925 ms、校验 96 ms，仍为 8,016/8,016、缺失 0。
当前月另检查 2026-07-22 08:00–10:00，自动选择实时表，源唯一 TradeId 为 7,513，
源查询 1,539 ms；联调中心该窗口尚未写入，因此按定义为 MISSING。D-1/D-2 范围与
24 个两小时窗口由单元测试验证，未对全部服务器执行夜间压力测试。

### TradeId 结构重构后验证

2026-07-23 在同一中心联调库对 ODS/命中模板和 202606、202607 月表完成列级迁移：
保留已有业务数据，补齐并回填 `trade_id` 后删除旧双标识列与旧索引。随后对
`legacy_10_13_10_4`、`dfs_gantry_transaction202606`、2026-06-15 08:00–10:00
重复执行 `CHECK -> REPAIR -> CHECK -> REPAIR`：

| 步骤 | 状态 | 完整性 | 源唯一数 | 中心匹配 | 缺失 | 新增 | 更新 | 源查询 | 写入 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CHECK | SUCCESS | COMPLETE | 8,016 | 8,016 | 0 | 0 | 0 | 914 ms | 0 ms |
| REPAIR | SUCCESS | COMPLETE | 8,016 | 8,016 | 0 | 0 | 8,016 | 2,427 ms | 733 ms |
| CHECK | SUCCESS | COMPLETE | 8,016 | 8,016 | 0 | 0 | 0 | 869 ms | 0 ms |
| REPAIR | SUCCESS | COMPLETE | 8,016 | 8,016 | 0 | 0 | 8,016 | 2,414 ms | 781 ms |

验证结论：

- `t_ods_event_202606` 在该窗口为 8,016 行，`COUNT(DISTINCT trade_id)=8,016`。
- `t_event_object_match_202606` 按 `(trade_id, object_no)` 分组无重复键。
- `t_ods_event_202606` 与 `t_event_object_match_202606` 仅保留 `trade_id` 交易标识列，不再存在旧双标识列。
- 调用 `sp_create_event_month_tables('202608')` 后，新 ODS 月表为 `trade_id varchar(38) ascii_bin NOT NULL` 且以该列为主键；新命中月表为 `trade_id varchar(38) ascii_bin NOT NULL` 且有 `uk_event_object_match (trade_id, object_no)`，两表均不保留重复的单列唯一/普通索引。

## 生产发布验证

2026-07-23 将提交 `c766177` 部署到 `10.13.0.223`。生产旧数据量大且仍依赖
`event_key + source_trade_id`，按维护者指示不保留数据备份，采用仓库迁移 SQL 的
`DROP_AND_RECREATE` 路径：删除旧 ODS、命中和 ETL 运行表，15 张事实表保留结构并
逐表清空；服务器、门架映射、规则、字典、用户和权限数据保留。迁移后确认 ODS 模板
只以 `trade_id` 为主键，旧交易标识列不存在。

正式验证窗口为 Asia/Shanghai `2026-07-22 08:00–10:00`，`source-mode=auto`，
覆盖全部 8 台启用且有有效门架映射的 `10.13.*` 服务器。首次和重复 LIVE 任务均为
8/8 `SUCCESS + COMPLETE`，各服务器源唯一数分别为 7,513、6,413、7,746、22,149、
7,988、9,417、4,009、11,923，合计 77,158；中心匹配数逐台相等，缺失均为 0。
重复同步后：

- ODS 仍为 77,158 行、77,158 个唯一 `trade_id`；
- 12,707 条命中记录无 `(trade_id, object_no)` 重复；
- 第二次同步新增均为 0，全部 77,158 条走幂等更新，并生成 8 个新 sync_id；
- 小时、日、月以及本路段入口、车型、来源收费站事实均已生成；
- 生产 `reports/options` 和窗口 `reports/entry-flow` 均返回 HTTP 200；
- API、唯一 worker、实时 timer active/enabled；D-1/D-2 夜检 unit 保留且 timer disabled/inactive，等待中心库连续积累两个完整自然日后启用；旧 reconcile unit 删除；
- worker 由 `flock` 包装一个 Python 子进程；第二个 worker 在 0 秒内退出，状态码为 1。

### 2026-07-23 最终清理

- 删除生产中心库遗留的 `t_etl_batch_bak_20260723_superseded`、`t_etl_batch_source_bak_20260723_superseded`；旧 ETL 表及备份表均不存在，配置、映射、规则、字典、用户权限和 15 张事实表继续保留。
- 删除旧 `hsz-origin-reconcile.service`、`hsz-origin-reconcile.timer` 及对应脚本、日志；nightly-check unit 保留并改为 Asia/Shanghai 03:00，但 timer 保持 disabled/inactive。
- 手工启动与 timer 同命令的 `hsz-origin-etl.service`，成功入队 `2026-07-23 14:00–16:00` LIVE；唯一 worker 完成 8/8 服务器，合计 102,320 个源 TradeId，全部 `SUCCESS + COMPLETE`、missing=0。
- 最终队列为 3 个 LIVE SUCCESS；同步日志为 24 个 `SUCCESS + COMPLETE`，PENDING/RUNNING/FAILED/MISSING 均为 0。ODS 重复 TradeId 为 0，命中 `(trade_id, object_no)` 重复为 0。
- 第二 worker 使用相同 flock 锁立即退出，状态码 1；实际 Python worker 为 1 个。API 健康检查返回 `{"status":"ok"}`。
- 三年历史 BACKFILL 未提交；中心库连续积累两个完整自然日后执行 `systemctl enable --now hsz-origin-nightly-check.timer`。

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

服务器 `legacy_10_13_10_4`，窗口 `2026-06-15 08:00:00` 至 `10:00:00`，源表
`dfs_gantry_transaction202606`：8,016 行，8,016 个唯一 TradeId，重复 0；使用流式
游标、每批 2,000 行读取完整业务字段，耗时约 2,733 ms。该结果支持使用两小时内存
快照和中心分批 IN 校验。

## 最终读取规则与参数

- 当前自然月只读实时表；过去自然月只读对应历史月表。
- 查询始终包含半开时间范围和服务器实际 GantryId 列表。
- CHECK 投影只选择 TradeId；GantryId 与 TransTime 仅用于有界 WHERE 条件。同步选择标准化需要的业务字段。
- 默认窗口 120 分钟、源批量 2,000、单 worker、窗口休眠 5 秒、瞬时源错误最多两次重试。

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

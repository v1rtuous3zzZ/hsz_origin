# ETL 运行说明

所有命令和 HTTP 入口先写中心任务队列，唯一常驻 worker 串行处理“一个服务器 + 一个时间窗口”。门架连接仅执行带
`GantryId IN (...)` 和 `[start,end)` 时间条件的只读查询，读取结束立即关闭。

## 数据库迁移

在中心库备份确认后执行 `migrations/20260723_simplify_etl.sql`。脚本会删除旧批次、
源批次、checkpoint 和 quality 表，创建 `t_etl_sync_log`、精简任务表，并为所有
ODS 月表的 `trade_id` 增加唯一约束。严禁在门架源库执行该脚本。

## 命令

```powershell
python -m app.etl.cli live-once
python -m app.etl.cli live
python -m app.etl.cli backfill --start 2026-01-01T00:00:00 --end 2026-02-01T00:00:00
python -m app.etl.cli nightly-check --days 1 2
python -m app.etl.cli repair --sync-id <sync_id>
python -m app.etl.cli repair --server <server_code> --start <start> --end <end>
python -m app.etl.cli worker
```

前五类命令只入队；只有最后的 `worker` 读取门架。生产不得启动第二个 worker。

当前月固定读 `dfs_gantry_transaction`，过去月固定读 `dfs_gantry_transactionYYYYMM`；
调试时可显式指定 `--source-mode realtime|history`。不会双表扫描或自动拆窗。

历史初始化建议逐月提交。默认窗口 120 分钟、流式批量 2000、窗口间休眠 5 秒、
单 worker。BACKFILL 在同月全部窗口完成后只重建一次事实；LIVE 与 REPAIR 重建当前
窗口事实；CHECK 不写业务数据。

夜间 04:30 运行 `nightly-check`，默认只检查 D-1 与 D-2，各拆 12 个两小时窗口，
不自动补数。缺失仅表示 `source TradeId - center TradeId` 非空。

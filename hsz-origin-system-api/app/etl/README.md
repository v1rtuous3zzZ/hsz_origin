# ETL 运行说明

所有命令和 HTTP 入口先写中心任务队列，唯一常驻 worker 串行处理“一个服务器 + 一个时间窗口”。门架连接仅执行带
`GantryId IN (...)` 和 `[start,end)` 时间条件的只读查询，读取结束立即关闭。

## 数据库迁移

按维护者要求无需保留旧 ETL 数据，直接执行 `migrations/20260723_simplify_etl.sql`。脚本会删除重建 ODS、
命中和同步日志，清空 15 张 ETL 派生事实表的数据并保留其结构；历史回填完成后重新
生成事实数据。配置、字典、门架关系、规则等基础数据保留。ODS 以 `trade_id` 主键保证
唯一。严禁在门架源库执行该脚本。

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

历史初始化建议逐月提交。BACKFILL 固定使用 120 分钟标准窗口，流式批量 2000、窗口间休眠 5 秒、
单 worker；恢复后即使全部窗口均 SKIPPED，也会在最新日志证明整月 COMPLETE 后重建事实。
某个两小时窗口需要更小范围补数时使用 REPAIR，REPAIR 可处理指定时间范围。LIVE 重建当前窗口；REPAIR
整个任务无失败和缺失后按受影响自然月分别重建；CHECK 不写业务数据也不重建事实。

worker 启动时先将遗留 RUNNING 同步日志标记为 `WorkerRestart` 失败，再把 RUNNING 手工
任务恢复为 PENDING；任务重跑会生成新的唯一同步日志。

夜间 03:00 运行 `nightly-check`，默认只检查 D-1 与 D-2，各拆 12 个两小时窗口，
不自动补数。缺失仅表示 `source TradeId - center TradeId` 非空。

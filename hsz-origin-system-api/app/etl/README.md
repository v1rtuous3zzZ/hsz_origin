# ETL

ETL 是独立 CLI 进程；它不运行在 FastAPI lifespan、请求线程或 Uvicorn worker 中。

## 命令

```powershell
python -m app.etl.cli inspect --source-mode legacy-test
python -m app.etl.cli live-once --source-mode legacy-test --start "2026-06-26 09:30:00" --end "2026-06-26 09:40:00" --dry-run
python -m app.etl.cli backfill --source-mode legacy-test --start "..." --end "..." --window-minutes 60 --job-name legacy_test --dry-run
python -m app.etl.cli status
```

源凭据由 `CREDENTIAL_KEY_USER` 和 `CREDENTIAL_KEY_PASSWORD` 环境变量提供，例如 `SOURCE_DB_DEFAULT_USER`。不提供凭据时 remote 读取会失败，不会回退到默认账号。

实时与历史分别使用 MySQL 锁；断点按 `job_code + source_server_id` 保存，只有全窗口成功且事实重算成功后才推进。事件键是 `SHA256(source_server_id|source_table_name|source_trade_id)`，月度 ODS 和命中表用唯一键实现幂等。

每个物理门架都由中心库动态映射；同一逻辑 HEX 的两个物理门架都读取并自然聚合，绝不按逻辑门架去重。

当前远程网络只可访问沿江公司 `10.13.*` 网段。`t_legacy_gantry_info` 是项目库内的 32 条门架母表参考；不在该母表的中心门架不得默认作为实际采集源。已知可取得的出本路段数据可能仅覆盖 G50，外部方向必须如实报告为不可达或待确认。

事实重算只能由协调器在全部源成功后集中执行，不能在每个源线程中累加。当前实现提供安全的 dry-run 验证路径；正式写入前仍须确认成功交易口径、上一门架介质选择和所有事实表重算 SQL。

当前 remote 成功交易口径未确认，故 remote 模式拒绝 `ALL_ROWS_TEST`；legacy-test dry-run 使用该测试口径。车型字典以 `t_vehicle_type_dict` 为准，未知值应使用 `UNKNOWN`，不猜测车型分类。legacy-test 只读 `hsz_origin_sys.t_gantry_transaction`，不代表所有正式源库。

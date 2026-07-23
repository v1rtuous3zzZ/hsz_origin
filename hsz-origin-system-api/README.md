# 沪苏浙 G50 溯源系统 API

## 环境与启动

复制 `.env.example` 为 `.env`，填写中心库、源库凭据和 JWT Secret：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

API 文档：`http://127.0.0.1:8000/docs`；健康检查：`/health`。

## ETL 迁移

确认中心库备份后执行 `migrations/20260723_simplify_etl.sql`。该迁移删除旧 ETL
批次/checkpoint 表，创建唯一窗口日志和精简任务表，并对 ODS `source_trade_id`
建立唯一约束。只允许在中心库执行。

## ETL 进程

ETL 不在 FastAPI 请求、startup 或 BackgroundTasks 中执行：

```powershell
# 两小时实时同步
.venv\Scripts\python.exe -m app.etl.cli live-once
.venv\Scripts\python.exe -m app.etl.cli live

# 历史初始化（建议逐月）
.venv\Scripts\python.exe -m app.etl.cli backfill --start 2026-01-01T00:00:00 --end 2026-02-01T00:00:00

# D-1、D-2 TradeId 检查
.venv\Scripts\python.exe -m app.etl.cli nightly-check --days 1 2

# 缺失窗口补数
.venv\Scripts\python.exe -m app.etl.cli repair --sync-id <sync_id>

# HTTP 任务单 worker
.venv\Scripts\python.exe -m app.etl.cli worker
```

除 `worker` 外的 CLI 与 HTTP 入口都只写中心任务队列。唯一常驻 worker 串行处理
LIVE/BACKFILL/REPAIR/CHECK 的服务器和窗口；当前月只读实时表、过去月只读历史月表，
不双表扫描、不递归拆窗。源读取完成即关闭连接，中心失败使用内存快照重试。

## HTTP ETL 接口

```text
GET  /api/v1/etl/sync-logs
GET  /api/v1/etl/missing-windows
POST /api/v1/etl/jobs/backfill
POST /api/v1/etl/jobs/check
POST /api/v1/etl/sync-logs/{sync_id}/repair
GET  /api/v1/etl/jobs/{job_id}
```

POST 接口只入队并返回 `job_id/task_no/status=PENDING`。`missing-windows` 对每个
服务器窗口只取最新有效日志，因此后续 REPAIR COMPLETE 会覆盖旧 MISSING 的展示，
但旧日志保持不变。

## systemd

`scripts/systemd/` 提供实时入队、唯一 worker 与 `hsz-origin-nightly-check.service/.timer`。
实时和夜检 service 只入队，不读取门架；夜检默认 04:30 运行。三年初始化期间可不启用该 timer。

## 验证

```powershell
.venv\Scripts\ruff.exe check .
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m app.etl.cli --help
```

# 沪苏浙 G50 溯源系统 API

## 环境配置

复制 `.env.example` 为 `.env`，填写中心库和源库连接信息，然后安装依赖：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` 包含 `tzdata`，Windows、CI 和精简容器都可加载 `Asia/Shanghai`。

## 本地启动

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

API 文档：`http://127.0.0.1:8000/docs`；健康检查：`/health`。

## ETL 进程

ETL 不在 FastAPI 请求、startup 或 BackgroundTasks 中执行。生产至少运行两个独立进程：

```powershell
# 两小时实时同步循环
.venv\Scripts\python.exe -m app.etl.cli live

# HTTP 手动同步任务 worker
.venv\Scripts\python.exe -m app.etl.cli worker
```

其他命令：

```powershell
# 最近一个完整两小时窗口
.venv\Scripts\python.exe -m app.etl.cli live-once

# 命令行历史补数
.venv\Scripts\python.exe -m app.etl.cli backfill --start 2026-01-01T00:00:00 --end 2026-02-01T00:00:00

# 只重建中心库事实
.venv\Scripts\python.exe -m app.etl.cli rebuild-facts --start 2026-01-01T00:00:00 --end 2026-02-01T00:00:00

# 查看后台任务
.venv\Scripts\python.exe -m app.etl.cli job-status 1
```

`scripts/run_live_sync.py` 和 `scripts/run_sync.py` 只是上述 CLI 的薄包装。

## HTTP 手动同步

`POST /api/v1/etl/manual-sync` 只向中心库 `t_etl_manual_job` 插入任务并立即返回 HTTP 202，不在 HTTP 请求内读取门架。示例：

```json
{
  "start": "2026-01-01T00:00:00",
  "end": "2026-02-01T00:00:00",
  "window_minutes": 120,
  "sleep_seconds": 2,
  "resume": true,
  "continue_on_error": true,
  "rebuild_facts": false
}
```

返回内容包含 `job_id`、`job_no`、`status=PENDING` 和 `status_url`。查询状态：

```text
GET /api/v1/etl/manual-sync-jobs/{job_id}
```

worker 每个窗口更新一次心跳和进度；超时的 `RUNNING` 任务会重新进入队列。任务表仅创建在中心库，所有门架源库仍只执行只读查询。

## 同步策略

1. 门架采集阶段使用 `GantryId IN (...)` 和有界 `TransTime` 范围，利用现有联合索引；读取完成立即关闭源连接。
2. 实时表与月表按 `TradeId` 去重，实时表优先；中心写入、匹配和事实重建失败不会重新读取门架。
3. 实时、历史和手动任务共享门架读取锁，避免多个进程同时压源库；不同物理服务器可控并行，同一 IP 串行。
4. 历史补数按两小时循环并断点续跑；过去月份直接读月表，全部窗口完成后按月重建事实。

## 验证

```powershell
.venv\Scripts\ruff.exe check .
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m app.etl.cli --help
```

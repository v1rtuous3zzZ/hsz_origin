# 沪苏浙 G50 溯源系统 API

## 环境配置

复制 `.env.example` 为 `.env`，并在本地填写新库连接信息。`.env` 不会被 Git 跟踪。

## 本地启动

```powershell
.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

API 文档：`http://127.0.0.1:8000/docs`；健康检查：`/health`；系统接口：`/api/v1/system/*`。

## 报表接口

`GET /api/v1/reports/directions?flow=entry|exit` 返回方向选择框数据。出口中仅 G50 两个方向的 `availability` 为 `AVAILABLE`；其余方向为 `UNAVAILABLE`，表示当前数据不可达或待确认。

四个统计接口为 `entry-flow`、`exit-flow`、`vehicle-types` 与 `entry-stations`。它们均接受 `start`、`end`、`granularity`（`hour`、`day`、`week`、`month`、`year`）、可重复的 `direction_ids`、`page` 和 `page_size` 参数，响应为 `{page, page_size, total, items}`。`vehicle-types` 返回车型编码，名称由前端枚举；`entry-stations` 在收费站字典缺名时返回 `station_name: "未知"`。

## 测试

```powershell
.venv\\Scripts\\python.exe -m pytest
.venv\\Scripts\\ruff.exe check .
```

## ETL

ETL 是独立 CLI 进程，绝不在 FastAPI startup、lifespan 或 BackgroundTasks 中启动。本阶段仅保留 `python -m app.etl.cli --help` 的命令骨架。

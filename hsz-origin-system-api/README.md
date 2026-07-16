# 沪苏浙 G50 溯源系统 API

## 环境配置

复制 `.env.example` 为 `.env`，并在本地填写新库连接信息。`.env` 不会被 Git 跟踪。

## 本地启动

```powershell
.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

API 文档：`http://127.0.0.1:8000/docs`；健康检查：`/health`；系统接口：`/api/v1/system/*`。

## 测试

```powershell
.venv\\Scripts\\python.exe -m pytest
.venv\\Scripts\\ruff.exe check .
```

## ETL

ETL 是独立 CLI 进程，绝不在 FastAPI startup、lifespan 或 BackgroundTasks 中启动。本阶段仅保留 `python -m app.etl.cli --help` 的命令骨架。

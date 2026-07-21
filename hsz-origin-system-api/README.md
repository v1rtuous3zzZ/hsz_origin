# 沪苏浙 G50 溯源系统 API

## 环境配置

复制 `.env.example` 为 `.env`，并在本地填写新库连接信息。`.env` 不会被 Git 跟踪。

## 本地启动

```powershell
.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

API 文档：`http://127.0.0.1:8000/docs`；健康检查：`/health`；系统接口：`/api/v1/system/*`。

## 登录

`POST /api/v1/auth/login` 请求体为 `{"username":"...","password":"..."}`。成功后返回 Bearer JWT、有效秒数与 `must_change_password`。本地初始化管理员账号为 `admin`，首次登录密码为 `123456`，响应会要求改密；部署时必须在首次登录后修改。

除 `/health` 和登录接口外，所有 `/api/v1/*` 业务接口都必须提供 `Authorization: Bearer <access_token>`。JWT 不保存服务端会话，因此同一账号可在多个客户端同时登录。

创建或重置管理员账号：

```powershell
.venv\Scripts\python.exe -m app.admin --username admin --password 123456 --display-name 系统管理员
```

## 报表接口

`GET /api/v1/reports/directions?flow=entry|exit` 返回方向选择框数据。出口中仅 G50 两个方向的 `availability` 为 `AVAILABLE`；其余方向为 `UNAVAILABLE`，表示当前数据不可达或待确认。

四个统计接口为 `entry-flow`、`exit-flow`、`vehicle-types` 与 `entry-stations`。它们均接受 `start`、`end`、`granularity`（`hour`、`day`、`week`、`month`、`year`）、可重复的 `direction_ids`、`page` 和 `page_size` 参数，响应为 `{page, page_size, total, items}`。`vehicle-types` 返回车型编码，名称由前端枚举；`entry-stations` 在收费站字典缺名时返回 `station_name: "未知"`。

## 手动同步

`GET /api/v1/etl/batches` 分页查看同步批次日志。`POST /api/v1/etl/manual-sync` 接受 `{"start":"...","end":"...","rebuild_facts":false}`，按连续 2 小时窗口同步；窗口跨月时自动切分。每个窗口读取实时交易表，仅为实时数据不完整的物理门架补读当月历史表，并按源服务器与交易主键去重。源连接在明细读取完成后立即关闭，后续转换、匹配和写入只访问中心库。手动批量补数默认不在每个窗口重建事实表，可传 `rebuild_facts=true` 用于小范围补数；大范围历史补数应先写 ODS/命中，完成后统一重建事实。

## 测试

```powershell
.venv\\Scripts\\python.exe -m pytest
.venv\\Scripts\\ruff.exe check .
```

## ETL

ETL 是独立 CLI 进程，绝不在 FastAPI startup、lifespan 或 BackgroundTasks 中启动。源库读取并发由 `HSZ_ETL_MAX_WORKERS` 控制，默认 `4`。同步不使用跨任务 MySQL 命名锁，幂等由 ODS/命中唯一键保证。历史回填可使用 `python -m app.etl.cli backfill --source-mode remote --start ... --end ... --window-minutes 120 --job-name ... --skip-fact-rebuild` 延后事实重建。

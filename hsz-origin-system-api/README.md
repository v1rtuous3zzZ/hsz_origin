# 沪苏浙 G50 溯源系统 API

## 环境配置

复制 `.env.example` 为 `.env`，并在本地填写中心库和源库连接信息。`.env` 不会被 Git 跟踪。

## 本地启动

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

API 文档：`http://127.0.0.1:8000/docs`；健康检查：`/health`；系统接口：`/api/v1/system/*`。

## 登录

`POST /api/v1/auth/login` 请求体为 `{"username":"...","password":"..."}`。成功后返回 Bearer JWT、有效秒数与 `must_change_password`。本地初始化管理员账号为 `admin`，首次登录密码为 `123456`，部署时必须修改。

除 `/health` 和登录接口外，所有 `/api/v1/*` 业务接口都必须提供 `Authorization: Bearer <access_token>`。

创建或重置管理员账号：

```powershell
.venv\Scripts\python.exe -m app.admin --username admin --password 123456 --display-name 系统管理员
```

## ETL 运行方式

统一入口：

```powershell
# 同步最近一个完整的两小时窗口
.venv\Scripts\python.exe -m app.etl.cli live-once

# 常驻循环，每分钟检查一次，只在新窗口出现时读取门架
.venv\Scripts\python.exe -m app.etl.cli live

# 循环补历史数据；默认两小时一个窗口、跳过已成功窗口、窗口间休眠 2 秒
.venv\Scripts\python.exe -m app.etl.cli backfill --start 2026-01-01T00:00:00 --end 2026-02-01T00:00:00

# 只重建中心库事实，不访问门架
.venv\Scripts\python.exe -m app.etl.cli rebuild-facts --start 2026-01-01T00:00:00 --end 2026-02-01T00:00:00
```

兼容原 systemd timer 的 `scripts/run_live_sync.py` 仍可使用；`scripts/run_sync.py` 是统一脚本包装。

同步分为两个阶段：

1. 门架采集：使用 `(GantryId, TransTime, ...)` 索引和流式游标读取；实时表不完整时仅补读对应物理门架的月表；读取完成立即关闭源连接。
2. 中心处理：按 `TradeId` 去重、标准化、分批写入 ODS/命中并重建事实。中心库失败只重试这一阶段，不重新访问门架。

实时同步和历史补数通过中心库命名锁串行化“门架读取阶段”，避免两个任务同时压门架；中心库处理阶段不占用该锁。不同物理服务器最多按 `HSZ_ETL_MAX_WORKERS` 并行，同一 IP 始终串行。

历史补数默认：过去月份直接读月表；当前月份使用实时表并只为覆盖不完整的物理门架补读月表。全部窗口成功后按月统一重建事实，不在每个窗口重复重建。

`POST /api/v1/etl/manual-sync` 支持 `start`、`end`、`rebuild_facts`、`window_minutes`、`sleep_seconds`、`resume` 和 `continue_on_error`。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\ruff.exe check .
```

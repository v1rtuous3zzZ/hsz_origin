# 项目基础构建状态

## 软件环境

- Git 2.42.0.windows.2
- Python 3.12.0
- Node.js 24.18.0
- npm 11.16.0
- MySQL 命令行客户端未安装（可选）；数据库检查经 PyMySQL 完成。

## 项目与依赖

- 后端：`hsz-origin-system-api`，FastAPI、Uvicorn、SQLAlchemy 2、PyMySQL、Pydantic Settings、Alembic、PyJWT、passlib/bcrypt、pytest、httpx、Ruff。
- 前端：`hsz-origin-system-web`，Vue 3、Vite、TypeScript、Vue Router、Pinia、Axios、Element Plus、ECharts、ESLint、Prettier。

## 数据库

新库连接成功，MySQL 8.0.46。主要表数量、字符集与门架完整性详见 [database-inspection.md](database-inspection.md)。未对数据库执行任何写操作。

## 运行与验证

后端启动：

```powershell
cd hsz-origin-system-api
.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

前端启动：

```powershell
cd hsz-origin-system-web
npm run dev -- --host 127.0.0.1
```

测试：`cd hsz-origin-system-api; .venv\\Scripts\\python.exe -m pytest`。

静态检查：`cd hsz-origin-system-api; .venv\\Scripts\\ruff.exe check .`。

构建：`cd hsz-origin-system-web; npm run build`。

## Git 与安全

当前根目录是单一 Git 仓库，包含 `hsz-origin-system-api` 与 `hsz-origin-system-web` 两个子目录。原独立仓库历史已本地保存在被忽略的 `.git-history-backups/` 中，未推送。后端 `.env`、`.venv`，前端 `node_modules`、`dist` 与日志均未纳入 Git 跟踪；所有示例配置均使用占位值或非敏感本地 API 地址。

## 未完成项与建议

认证接口、用户会话策略与授权模型仍待确认；ETL 仅有 CLI 骨架，尚未连接 13 台源服务器或写入数据。下一阶段建议先完成认证：现有 `t_user`/`t_user_session` 已明确，可在不扩展数据同步风险的前提下建立前后端访问边界。

# 沪苏浙 G50 溯源系统 Web

## 环境配置

开发 API 地址由 `.env.development` 的 `VITE_API_BASE_URL` 配置；生产构建使用 `.env.production` 的同名变量，通过 Nginx 的 `/api/` 反向代理访问 API。示例见 `.env.example`。

## 本地启动

```powershell
npm run dev -- --host 127.0.0.1
```

默认访问地址：`http://127.0.0.1:5173`。

## 构建

```powershell
npm run build
```

前端提供管理员登录以及入口流量、出口流量、车型和入口收费站四个报表页面。接口地址由 `VITE_API_BASE_URL` 配置；导出 Excel 接口尚未接入。

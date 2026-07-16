# 沪苏浙 G50 溯源系统 Web

## 环境配置

开发 API 地址由 `.env.development` 的 `VITE_API_BASE_URL` 配置；示例见 `.env.example`。

## 本地启动

```powershell
npm run dev -- --host 127.0.0.1
```

默认访问地址：`http://127.0.0.1:5173`。

## 构建

```powershell
npm run build
```

Dashboard 仅调用 `/system/gantry-summary` 展示基础数量；认证接口未确认，登录页明确提示待接入。

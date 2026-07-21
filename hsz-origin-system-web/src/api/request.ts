import axios from "axios";
import type { AxiosError } from "axios";
import { ElMessage } from "element-plus";

let onUnauthorized: (() => void) | undefined;
export const setUnauthorizedHandler = (handler: () => void) => {
  onUnauthorized = handler;
};

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 300_000,
  paramsSerializer: { indexes: null },
});

request.interceptors.request.use((config) => {
  const token = sessionStorage.getItem("hsz_access_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});
request.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: unknown }>) => {
    const detail = error.response?.data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map((item) =>
                typeof item === "object" && item
                  ? String((item as { msg?: string }).msg ?? "")
                  : String(item),
              )
              .filter(Boolean)
              .join("；")
          : detail && typeof detail === "object"
            ? JSON.stringify(detail)
            : error.code === "ECONNABORTED"
              ? "请求超时，请稍后重试"
              : error.request
                ? "无法连接服务器，请检查网络或服务状态"
                : "请求失败，请稍后重试";
    if (
      error.response?.status === 401 &&
      !error.config?.url?.includes("/auth/login")
    )
      onUnauthorized?.();
    if (message) ElMessage.error(message);
    return Promise.reject(error);
  },
);

export default request;

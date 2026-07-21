import request from "./request";
import type { LoginRequest, LoginResponse } from "../types/auth";
export const login = (payload: LoginRequest) =>
  request.post<LoginResponse>("/auth/login", payload).then(({ data }) => data);

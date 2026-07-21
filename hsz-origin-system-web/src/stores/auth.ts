import { defineStore } from "pinia";
import { login } from "../api/auth";
import type { LoginRequest } from "../types/auth";

const storageKey = "hsz_auth";
interface StoredAuth {
  token: string;
  username: string;
  expiresAt: number;
  loginAt: number;
}
const read = (): StoredAuth | null => {
  const raw = sessionStorage.getItem(storageKey);
  if (!raw) return null;
  try {
    const data = JSON.parse(raw) as StoredAuth;
    return data.expiresAt > Date.now() ? data : null;
  } catch {
    return null;
  }
};

export const useAuthStore = defineStore("auth", {
  state: () => ({
    token: read()?.token ?? "",
    username: read()?.username ?? "",
    expiresAt: read()?.expiresAt ?? 0,
    loginAt: read()?.loginAt ?? 0,
  }),
  getters: {
    authenticated: (state) =>
      Boolean(state.token) && state.expiresAt > Date.now(),
  },
  actions: {
    async signIn(payload: LoginRequest) {
      const response = await login(payload);
      const data: StoredAuth = {
        token: response.access_token,
        username: payload.username,
        loginAt: Date.now(),
        expiresAt: Date.now() + response.expires_in * 1000,
      };
      this.token = data.token;
      this.username = data.username;
      this.loginAt = data.loginAt;
      this.expiresAt = data.expiresAt;
      sessionStorage.setItem(storageKey, JSON.stringify(data));
      sessionStorage.setItem("hsz_access_token", data.token);
      return response;
    },
    signOut() {
      this.token = "";
      this.username = "";
      this.expiresAt = 0;
      this.loginAt = 0;
      sessionStorage.removeItem(storageKey);
      sessionStorage.removeItem("hsz_access_token");
    },
    validate() {
      if (!this.authenticated) this.signOut();
      return this.authenticated;
    },
  },
});

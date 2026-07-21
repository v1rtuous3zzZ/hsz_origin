<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const form = reactive({ username: "", password: "" });
const loading = ref(false);
const submit = async () => {
  if (!form.username || !form.password) return;
  loading.value = true;
  try {
    await auth.signIn(form);
    const redirect =
      typeof route.query.redirect === "string"
        ? route.query.redirect
        : "/reports/entry-flow";
    await router.replace(redirect);
  } catch {
    form.password = "";
  } finally {
    loading.value = false;
  }
};
</script>
<template>
  <main class="login-page">
    <section class="login-brand">
      <div>
        <p>管理报表系统</p>
        <h1>沪苏浙溯源平台</h1>
        <span>G50 高速路段通行数据统计</span>
      </div>
    </section>
    <section class="login-form-area">
      <el-form class="login-form" @submit.prevent="submit"
        ><h2>管理员登录</h2>
        <p>请使用管理员账号登录系统</p>
        <el-form-item label="账号"
          ><el-input
            v-model="form.username"
            autocomplete="username" /></el-form-item
        ><el-form-item label="密码"
          ><el-input
            v-model="form.password"
            type="password"
            show-password
            autocomplete="current-password"
            @keyup.enter="submit" /></el-form-item
        ><el-button
          type="primary"
          native-type="submit"
          :loading="loading"
          :disabled="!form.username || !form.password"
          >登录</el-button
        ></el-form
      >
    </section>
  </main>
</template>

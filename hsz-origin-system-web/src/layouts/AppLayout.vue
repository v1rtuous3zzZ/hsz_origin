<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { reportMenu } from "../constants/menu";
import { useAuthStore } from "../stores/auth";
import { Expand, Fold } from "@element-plus/icons-vue";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const collapsed = ref(localStorage.getItem("hsz_sidebar_collapsed") === "true");
const pageTitle = computed(() => String(route.meta.title ?? ""));
const toggle = () => {
  collapsed.value = !collapsed.value;
  localStorage.setItem("hsz_sidebar_collapsed", String(collapsed.value));
};
const logout = () => {
  auth.signOut();
  void router.push("/login");
};
</script>

<template>
  <el-container class="app-layout">
    <el-aside :width="collapsed ? '56px' : '224px'" class="app-sidebar">
      <div class="brand" :title="collapsed ? '沪苏浙溯源平台' : ''">
        <span v-if="!collapsed">沪苏浙溯源平台</span><span v-else>沪</span>
      </div>
      <el-menu
        :default-active="route.path"
        router
        :collapse="collapsed"
        background-color="#26383e"
        text-color="#b8c4c8"
        active-text-color="#ffffff"
      >
        <el-menu-item
          v-for="item in reportMenu"
          :key="item.path"
          :index="item.path"
        >
          <el-icon><component :is="item.icon" /></el-icon
          ><span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="app-header"
        ><el-button
          class="header-menu-toggle"
          text
          :icon="collapsed ? Expand : Fold"
          :aria-label="collapsed ? '展开菜单' : '收起菜单'"
          @click="toggle"
        /><strong>沪苏浙溯源平台</strong
        ><span v-if="pageTitle" class="page-title">{{ pageTitle }}</span>
        <div class="account">
          <span>{{ auth.username }}</span
          ><el-button text @click="logout">退出登录</el-button>
        </div></el-header
      >
      <el-main class="app-main"><router-view /></el-main>
    </el-container>
  </el-container>
</template>

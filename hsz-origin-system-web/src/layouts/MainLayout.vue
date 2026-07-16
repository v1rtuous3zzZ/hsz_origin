<script setup lang="ts">
import { useAppStore } from '../stores/app'

const app = useAppStore()
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px" class="sidebar">
      <h1>{{ app.title }}</h1>
      <el-menu router default-active="/dashboard">
        <el-menu-item index="/dashboard">系统概览</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">基础运行监控</el-header>
      <el-main><slot /></el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { getGantrySummary, type GantrySummary } from '../api/system'
import MainLayout from '../layouts/MainLayout.vue'

const summary = ref<GantrySummary>()
const error = ref('')

onMounted(async () => {
  try {
    summary.value = await getGantrySummary()
  } catch {
    error.value = '暂时无法读取后端汇总数据，请确认 API 服务已启动。'
  }
})

const cards = [
  ['source_server_count', '源服务器数量'],
  ['physical_gantry_count', '物理门架数量'],
  ['logical_gantry_count', '逻辑门架数量'],
  ['active_mapping_count', '有效映射数量'],
  ['stat_object_count', '统计对象数量'],
  ['stat_rule_count', '正式规则数量'],
] as const
</script>

<template>
  <MainLayout>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-row v-else :gutter="16">
      <el-col v-for="[key, label] in cards" :key="key" :span="8">
        <el-card class="metric-card">
          <div>{{ label }}</div>
          <strong>{{ summary?.[key] ?? '加载中' }}</strong>
        </el-card>
      </el-col>
    </el-row>
  </MainLayout>
</template>

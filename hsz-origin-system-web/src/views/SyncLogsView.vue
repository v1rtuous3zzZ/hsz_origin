<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  getMissingWindows,
  getSyncLogs,
  repairSyncWindow,
  startManualSync,
  type MissingWindow,
  type SyncLogResult,
} from "../api/reports";
import { defaultHourRange, toLocalIso } from "../utils/date";

const range = ref(defaultHourRange());
const loading = ref(false);
const syncing = ref(false);
const retrying = ref<string>();
const status = ref("");
const page = ref(1);
const pageSize = ref(20);
const result = ref<SyncLogResult>();
const missingWindows = ref<MissingWindow[]>([]);
const now = new Date();
const visibleMissing = computed(() => missingWindows.value.filter((item) => {
  const { start, end } = currentRange();
  return item.window_start < end && item.window_end > start;
}));
const disabledDate = (date: Date) => date.getTime() > now.getTime();
const formatTime = (value: string) => value.replace("T", " ").slice(0, 16);
const statusType = (value: string) =>
  value === "SUCCESS" || value === "SKIPPED" ? "success" : value === "FAILED" ? "danger" : "warning";
const statusLabel = (value: string) =>
  ({ SUCCESS: "成功", FAILED: "失败", RUNNING: "执行中", SKIPPED: "已跳过" })[value] ?? value;
const checkLabel = (value: string) =>
  ({ COMPLETE: "完整", MISSING: "缺失", UNCHECKED: "未检查" })[value] ?? value;
const operationLabel = (value: string) =>
  ({ LIVE: "实时", BACKFILL: "历史", REPAIR: "补数", CHECK: "检查" })[value] ?? value;
const numberLabel = (value: number | null | undefined) => value == null ? "--" : value.toLocaleString("zh-CN");
const currentRange = () => ({ start: toLocalIso(range.value[0]), end: toLocalIso(range.value[1]) });

const load = async () => {
  const { start, end } = currentRange();
  if (new Date(end) > new Date()) return ElMessage.warning("结束时间不能晚于当前时间");
  loading.value = true;
  try {
    [result.value, missingWindows.value] = await Promise.all([
      getSyncLogs(start, end, status.value || undefined, page.value, pageSize.value),
      getMissingWindows(),
    ]);
  } finally {
    loading.value = false;
  }
};

const repair = async (syncId: string) => {
  retrying.value = syncId;
  try {
    const response = await repairSyncWindow(syncId);
    ElMessage.success(`补数任务 ${response.task_no} 已提交后台执行`);
  } finally {
    retrying.value = undefined;
  }
};

const sync = async () => {
  const { start, end } = currentRange();
  if (new Date(end) > new Date()) return ElMessage.warning("结束时间不能晚于当前时间");
  try {
    await ElMessageBox.confirm("是否提交所选时间区间的历史同步任务？", "提交历史同步", {
      confirmButtonText: "是", cancelButtonText: "否", type: "warning",
    });
  } catch { return; }
  syncing.value = true;
  try {
    const response = await startManualSync(start, end);
    ElMessage.success(`历史同步任务 ${response.task_no} 已提交后台执行`);
  } finally { syncing.value = false; }
};
onMounted(load);
</script>

<template>
  <section class="sync-log-page">
    <el-form class="sync-log-filter" @submit.prevent="load">
      <el-form-item label="日志状态"><el-select v-model="status" clearable style="width: 130px"><el-option label="成功" value="SUCCESS" /><el-option label="失败" value="FAILED" /><el-option label="执行中" value="RUNNING" /><el-option label="已跳过" value="SKIPPED" /></el-select></el-form-item>
      <el-form-item label="时间区间"><el-date-picker v-model="range" type="datetimerange" :disabled-date="disabledDate" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间" style="width: 390px" /></el-form-item>
      <el-form-item><el-button type="primary" native-type="submit" :loading="loading">查询</el-button><el-button :loading="syncing" @click="sync">提交历史同步</el-button></el-form-item>
    </el-form>
    <el-alert v-if="visibleMissing.length" type="warning" :closable="false" show-icon title="存在 TradeId 缺失窗口">
      <template #default><span v-for="item in visibleMissing" :key="item.latest_sync_id" class="missing-window">{{ item.server_code }}：{{ formatTime(item.window_start) }} 至 {{ formatTime(item.window_end) }}，缺失 {{ item.missing_count }} 条</span></template>
    </el-alert>
    <el-alert v-else-if="result" type="success" :closable="false" show-icon title="所选区间没有最新状态为缺失的窗口" />
    <el-table v-loading="loading" :data="result?.items ?? []" border height="calc(100vh - 260px)" empty-text="所选区间暂无同步日志">
      <el-table-column prop="server_code" label="服务器" min-width="170" />
      <el-table-column label="操作" width="100"><template #default="{ row }">{{ operationLabel(row.operation) }}</template></el-table-column>
      <el-table-column label="同步区间" min-width="270"><template #default="{ row }">{{ formatTime(row.window_start) }} 至 {{ formatTime(row.window_end) }}</template></el-table-column>
      <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="statusType(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
      <el-table-column label="完整性" width="90"><template #default="{ row }">{{ checkLabel(row.check_status) }}</template></el-table-column>
      <el-table-column label="源唯一数" align="right" width="110"><template #default="{ row }">{{ numberLabel(row.source_unique_count) }}</template></el-table-column>
      <el-table-column label="中心匹配" align="right" width="110"><template #default="{ row }">{{ numberLabel(row.center_matched_count) }}</template></el-table-column>
      <el-table-column label="缺失" align="right" width="90"><template #default="{ row }">{{ numberLabel(row.missing_count) }}</template></el-table-column>
      <el-table-column label="源查询(ms)" align="right" width="115"><template #default="{ row }">{{ numberLabel(row.query_duration_ms) }}</template></el-table-column>
      <el-table-column label="错误摘要" min-width="180" show-overflow-tooltip><template #default="{ row }">{{ row.error_message || "--" }}</template></el-table-column>
      <el-table-column label="操作" width="90"><template #default="{ row }"><el-button v-if="row.check_status === 'MISSING'" link type="primary" :loading="retrying === row.sync_id" @click="repair(row.sync_id)">补数</el-button><span v-else>--</span></template></el-table-column>
    </el-table>
    <el-pagination class="report-pagination" v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" :total="result?.total ?? 0" @current-change="load" @size-change="page = 1; load()" />
  </section>
</template>

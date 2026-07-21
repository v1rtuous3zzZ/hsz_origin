<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  getSyncLogs,
  retrySyncSource,
  startManualSync,
  type SyncLogResult,
} from "../api/reports";
import { defaultHourRange, toLocalIso } from "../utils/date";

const range = ref(defaultHourRange());
const loading = ref(false);
const syncing = ref(false);
const retrying = ref<number>();
const status = ref("");
const result = ref<SyncLogResult>();
const now = new Date();
const missing = computed(() => result.value?.summary?.missing_windows ?? []);
const disabledDate = (date: Date) =>
  date.getTime() >
  new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
const formatTime = (value: string) => value.replace("T", " ").slice(0, 16);
const statusType = (status: string) =>
  status === "SUCCESS" ? "success" : status === "FAILED" ? "danger" : "warning";
const statusLabel = (status: string) =>
  ({ SUCCESS: "成功", PARTIAL: "部分失败", FAILED: "失败", RUNNING: "执行中" })[
    status
  ] ?? status;
const currentRange = () => ({
  start: toLocalIso(range.value[0]),
  end: toLocalIso(range.value[1]),
});
const load = async () => {
  const { start, end } = currentRange();
  if (new Date(end) > new Date())
    return ElMessage.warning("结束时间不能晚于当前时间");
  loading.value = true;
  try {
    result.value = await getSyncLogs(start, end, status.value || undefined);
  } finally {
    loading.value = false;
  }
};
const retrySource = async (batchId: number, sourceId: number) => {
  retrying.value = sourceId;
  try {
    const response = await retrySyncSource(batchId, sourceId);
    ElMessage.success(`补同步任务 ${response.job_no} 已提交后台执行`);
  } finally {
    retrying.value = undefined;
  }
};
const sync = async () => {
  const { start, end } = currentRange();
  if (new Date(end) > new Date())
    return ElMessage.warning("结束时间不能晚于当前时间");
  try {
    await ElMessageBox.confirm(
      "是否提交所选时间区间的门架同步任务？",
      "提交手动同步",
      { confirmButtonText: "是", cancelButtonText: "否", type: "warning" },
    );
  } catch {
    return;
  }
  syncing.value = true;
  try {
    const response = await startManualSync(start, end);
    ElMessage.success(`手动同步任务 ${response.job_no} 已提交后台执行`);
  } finally {
    syncing.value = false;
  }
};
onMounted(load);
</script>

<template>
  <section class="sync-log-page">
    <el-form class="sync-log-filter" @submit.prevent="load">
      <el-form-item label="日志状态"><el-select v-model="status" clearable style="width: 130px"><el-option label="成功" value="SUCCESS" /><el-option label="部分失败" value="PARTIAL" /><el-option label="失败" value="FAILED" /><el-option label="执行中" value="RUNNING" /></el-select></el-form-item>
      <el-form-item label="时间区间"
        ><el-date-picker
          v-model="range"
          type="datetimerange"
          :disabled-date="disabledDate"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          style="width: 390px"
      /></el-form-item>
      <el-form-item
        ><el-button type="primary" native-type="submit" :loading="loading"
          >查询</el-button
        ><el-button type="primary" :loading="syncing" @click="sync"
          >提交同步</el-button
        ></el-form-item
      >
    </el-form>
    <el-alert
      v-if="missing.length"
      type="warning"
      :closable="false"
      show-icon
      title="发现未成功同步的时间段"
      ><template #default
        ><span v-for="item in missing" :key="item.start" class="missing-window"
          >{{ formatTime(item.start) }} 至 {{ formatTime(item.end) }}</span
        ></template
      ></el-alert
    >
    <el-alert
      v-else-if="result"
      type="success"
      :closable="false"
      show-icon
      title="所选区间的两小时同步窗口均已有成功批次覆盖"
    />
    <div v-if="result?.summary" class="sync-summary">
      <span>成功 {{ result.summary.success_count }}</span
      ><span>失败 {{ result.summary.failed_count }}</span
      ><span>执行中 {{ result.summary.running_count }}</span>
    </div>
    <el-table
      v-loading="loading"
      :data="result?.items ?? []"
      border
      height="calc(100vh - 300px)"
      empty-text="所选区间暂无同步日志"
    >
      <el-table-column
        prop="batch_no"
        label="批次号"
        min-width="190"
      /><el-table-column label="同步区间" min-width="270"
        ><template #default="{ row }"
          >{{ formatTime(row.window_start) }} 至
          {{ formatTime(row.window_end) }}</template
        ></el-table-column
      ><el-table-column label="状态" width="100"
        ><template #default="{ row }"
          ><el-tag :type="statusType(row.status)" effect="plain">{{
            statusLabel(row.status)
          }}</el-tag></template
        ></el-table-column
      ><el-table-column
        prop="source_row_count"
        label="源数据"
        align="right"
        width="100"
      /><el-table-column
        prop="success_event_count"
        label="成功事件"
        align="right"
        width="110"
      /><el-table-column
        prop="error_count"
        label="错误数"
        align="right"
        width="90"
      /><el-table-column label="错误摘要" min-width="220" show-overflow-tooltip
        ><template #default="{ row }">{{
          row.error_summary || "--"
        }}</template></el-table-column
      >
      <el-table-column label="失败服务器" min-width="220"><template #default="{ row }"><div v-for="source in row.sources?.filter((item: any) => item.status === 'FAILED')" :key="source.source_server_id">{{ source.server_code }} <el-button link type="primary" :loading="retrying === source.source_server_id" @click="retrySource(row.batch_id, source.source_server_id)">补同步</el-button></div></template></el-table-column>
    </el-table>
  </section>
</template>

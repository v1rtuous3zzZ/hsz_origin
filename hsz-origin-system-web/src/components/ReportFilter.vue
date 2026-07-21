<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessageBox } from "element-plus";
import { defaultHourRange, defaultRange, toLocalIso } from "../utils/date";
import { granularityLabels } from "../constants/time-granularity";
import type {
  Granularity,
  ReportQuery,
  SelectableOption,
} from "../types/reports";
export interface ExtraFilterOption {
  key: "vehicle_type_codes" | "media_type_codes";
  label: string;
  options: SelectableOption[];
  placeholder?: string;
}
const props = defineProps<{
  options: SelectableOption[];
  optionLabel?: string;
  selectionParam?: "direction_ids" | "station_ids";
  granularities: Granularity[];
  loading?: boolean;
  requireSingleDirection?: boolean;
  extraFilters?: ExtraFilterOption[];
}>();
const emit = defineEmits<{ query: [ReportQuery]; export: [ReportQuery] }>();
const granularity = ref<Granularity>("hour");
const directionIds = ref<number[]>([]);
const directionId = ref<number>();
const dateRange = ref(defaultRange());
const dateTimeRange = ref(defaultHourRange());
const extraSelections = ref<Record<string, string[]>>({});
const dayStart = (value: Date) => {
  const date = new Date(value);
  date.setHours(0, 0, 0, 0);
  return date;
};
const dayEnd = (value: Date) => {
  const date = new Date(value);
  date.setHours(23, 59, 59, 999);
  return date;
};
const monthStart = (value: Date) =>
  new Date(value.getFullYear(), value.getMonth(), 1);
const monthEnd = (value: Date) =>
  dayEnd(new Date(value.getFullYear(), value.getMonth() + 1, 0));
const yearStart = (value: Date) => new Date(value.getFullYear(), 0, 1);
const yearEnd = (value: Date) => dayEnd(new Date(value.getFullYear(), 11, 31));
const weekStart = (value: Date) => {
  const date = dayStart(value);
  const day = date.getDay() || 7;
  date.setDate(date.getDate() - day + 1);
  return date;
};
const weekEnd = (value: Date) =>
  dayEnd(
    new Date(
      weekStart(value).getFullYear(),
      weekStart(value).getMonth(),
      weekStart(value).getDate() + 6,
    ),
  );
const recentDays = (days: number) => {
  const end = new Date();
  const start = dayStart(end);
  start.setDate(start.getDate() - days + 1);
  return [start, dayEnd(end)];
};
const rangeShortcuts = [
  {
    text: "今日",
    value: () => {
      const now = new Date();
      return [dayStart(now), dayEnd(now)];
    },
  },
  {
    text: "昨日",
    value: () => {
      const yesterday = new Date();
      yesterday.setDate(yesterday.getDate() - 1);
      return [dayStart(yesterday), dayEnd(yesterday)];
    },
  },
  {
    text: "本周",
    value: () => {
      const now = new Date();
      return [weekStart(now), weekEnd(now)];
    },
  },
  {
    text: "上周",
    value: () => {
      const previous = new Date();
      previous.setDate(previous.getDate() - 7);
      return [weekStart(previous), weekEnd(previous)];
    },
  },
  { text: "近7日", value: () => recentDays(7) },
  {
    text: "本月",
    value: () => {
      const now = new Date();
      return [monthStart(now), monthEnd(now)];
    },
  },
  {
    text: "上月",
    value: () => {
      const now = new Date();
      const previous = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      return [monthStart(previous), monthEnd(previous)];
    },
  },
  { text: "近30日", value: () => recentDays(30) },
  {
    text: "本年",
    value: () => {
      const now = new Date();
      return [yearStart(now), yearEnd(now)];
    },
  },
  {
    text: "去年",
    value: () => {
      const previous = new Date(new Date().getFullYear() - 1, 0, 1);
      return [yearStart(previous), yearEnd(previous)];
    },
  },
];
const directionSelection = computed<number | number[]>({
  get: () =>
    props.requireSingleDirection
      ? (directionId.value ?? 0)
      : directionIds.value,
  set: (value) => {
    if (props.requireSingleDirection) directionId.value = Number(value);
    else directionIds.value = value as number[];
  },
});
const range = computed({
  get: () =>
    granularity.value === "hour" ? dateTimeRange.value : dateRange.value,
  set: (value: [Date, Date]) => {
    if (granularity.value === "hour") dateTimeRange.value = value;
    else dateRange.value = value;
  },
});
watch(granularity, (next) => {
  if (next === "hour") {
    dateTimeRange.value = [...dateRange.value] as [Date, Date];
    return;
  }
  dateRange.value = [
    dayStart(dateTimeRange.value[0]),
    dayStart(dateTimeRange.value[1]),
  ];
});
watch(
  () => props.options,
  (options) => {
    if (
      props.requireSingleDirection &&
      !options.some(
        (item) =>
          item.value === directionId.value &&
          item.availability === "AVAILABLE",
      )
    )
      directionId.value = options.find(
        (item) => item.availability === "AVAILABLE",
      )?.value as number | undefined;
  },
  { immediate: true },
);
watch(
  () => props.extraFilters,
  (filters) => {
    const next: Record<string, string[]> = {};
    for (const filter of filters ?? [])
      next[filter.key] = extraSelections.value[filter.key] ?? [];
    extraSelections.value = next;
  },
  { immediate: true },
);
const buildQuery = () => {
  const [start, selectedEnd] = range.value;
  const end = new Date(selectedEnd);
  const selectedDirection = directionId.value;
  if (granularity.value !== "hour") end.setDate(end.getDate() + 1);
  if (
    start >= end ||
    (props.requireSingleDirection && selectedDirection === undefined)
  )
    return;
  const selectedIds = props.requireSingleDirection
    ? [selectedDirection as number]
    : directionIds.value;
  const extras = Object.fromEntries(
    Object.entries(extraSelections.value).map(([key, value]) => [
      key,
      value.length ? value : undefined,
    ]),
  );
  return {
    start: toLocalIso(start),
    end: toLocalIso(end),
    granularity: granularity.value,
    direction_ids: props.selectionParam === "station_ids" ? [] : selectedIds,
    station_ids: props.selectionParam === "station_ids" ? selectedIds : undefined,
    ...extras,
    page: 1,
    page_size: 20,
  };
};
const confirmLargeHourlyQuery = async (query: ReportQuery) => {
  const days =
    (new Date(query.end).getTime() - new Date(query.start).getTime()) /
    86400000;
  if (query.granularity !== "hour" || days <= 7) return true;
  try {
    await ElMessageBox.confirm(
      "当前选择的时间范围超过 7 日，按小时维度查询的数据量较大，处理时间可能较长。是否继续？",
      "查询确认",
      { confirmButtonText: "继续", cancelButtonText: "取消", type: "warning" },
    );
    return true;
  } catch {
    return false;
  }
};
const submit = async () => {
  const query = buildQuery();
  if (query && (await confirmLargeHourlyQuery(query))) emit("query", query);
};
const exportExcel = async () => {
  const query = buildQuery();
  if (query && (await confirmLargeHourlyQuery(query))) emit("export", query);
};
defineExpose({ submit });
</script>
<template>
  <el-form class="report-filter" @submit.prevent="submit"
    ><el-form-item :label="optionLabel ?? '方向名称'"
      ><el-select
        v-model="directionSelection"
        :multiple="!requireSingleDirection"
        :clearable="!requireSingleDirection"
        :collapse-tags="!requireSingleDirection"
        :placeholder="requireSingleDirection ? '请选择方向' : '全部'"
        style="width: 260px"
        ><el-option
          v-for="item in options"
          :key="item.value"
          :value="item.value"
          :label="
            item.availability === 'UNAVAILABLE'
              ? `${item.label}（数据不可达）`
              : item.label
          "
          :disabled="
            item.availability === 'UNAVAILABLE'
          " /></el-select></el-form-item
    ><el-form-item
      v-for="filter in extraFilters ?? []"
      :key="filter.key"
      :label="filter.label"
      ><el-select
        v-model="extraSelections[filter.key]"
        multiple
        clearable
        collapse-tags
        collapse-tags-tooltip
        :placeholder="filter.placeholder ?? '全部'"
        style="width: 220px"
        ><el-option
          v-for="item in filter.options"
          :key="item.value"
          :value="String(item.value)"
          :label="item.label" /></el-select></el-form-item
    ><el-form-item label="时间区间"
      ><el-date-picker
        v-model="range"
        :type="granularity === 'hour' ? 'datetimerange' : 'daterange'"
        :shortcuts="rangeShortcuts"
        popper-class="report-date-picker"
        :value-format="undefined"
        range-separator="至"
        start-placeholder="开始时间"
        end-placeholder="结束时间"
        style="width: 390px" /></el-form-item
    ><el-form-item label="时间维度"
      ><el-select v-model="granularity" style="width: 110px"
        ><el-option
          v-for="item in granularities"
          :key="item"
          :value="item"
          :label="granularityLabels[item]" /></el-select></el-form-item
    ><el-form-item
      ><el-button type="primary" native-type="submit" :disabled="loading"
        >查询</el-button
      ><el-button :disabled="loading" @click="exportExcel"
        >导出Excel</el-button
      ></el-form-item
    ></el-form
  >
</template>

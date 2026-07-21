<script
  setup
  lang="ts"
  generic="T extends { period: string | number; event_count: number }"
>
import { computed, nextTick, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import ReportFilter from "../../components/ReportFilter.vue";
import type { ExtraFilterOption } from "../../components/ReportFilter.vue";
import { useReportOptionsStore } from "../../stores/report-options";
import type {
  DirectionOption,
  Granularity,
  PageResult,
  ReportQuery,
  SelectableOption,
} from "../../types/reports";
import { formatPeriodHeaderInContext } from "../../utils/date";
import { formatNumber, formatPercent } from "../../utils/number";

interface RowField {
  key: string;
  label: string;
}
interface MatrixRow {
  key: string;
  values: Record<string, number>;
  fields: Record<string, unknown>;
  directionOrder?: number;
  optionOrder?: number;
}

const props = defineProps<{
  flow: "entry" | "exit";
  load: (query: ReportQuery) => Promise<PageResult<T>>;
  rowFields: RowField[];
  fieldFormatters?: Record<string, (value: unknown) => string>;
  requireSingleDirection?: boolean;
  topN?: number;
  includePercent?: boolean;
  showTotals?: boolean;
  note?: string;
  filterOptions?: SelectableOption[];
  filterLabel?: string;
  selectionParam?: "direction_ids" | "station_ids";
  preserveRowOptionOrder?: boolean;
  extraFilters?: ExtraFilterOption[];
}>();

const route = useRoute();
const options = useReportOptionsStore();
const filter = ref<InstanceType<typeof ReportFilter>>();
const query = ref<ReportQuery>();
const loading = ref(false);
const error = ref("");
const periods = ref<string[]>([]);
const periodTotals = ref<Record<string, number>>({});
const rows = ref<MatrixRow[]>([]);
const currentPage = ref(1);
const pageSize = ref(20);
const directions = computed<DirectionOption[]>(() =>
  props.flow === "entry"
    ? (options.data?.entry_directions ?? [])
    : (options.data?.exit_directions ?? []),
);
const filterOptions = computed<SelectableOption[]>(() =>
  props.filterOptions ??
  directions.value.map((item) => ({
    value: item.direction_id,
    label: item.direction_name,
    availability: item.availability,
  })),
);
const showsDirection = computed(() =>
  props.rowFields.some((field) => field.key === "direction_name"),
);
const directionOrder = computed(
  () =>
    new Map(directions.value.map((item, index) => [item.direction_id, index])),
);
const optionOrder = computed(
  () => new Map(filterOptions.value.map((item, index) => [item.label, index])),
);
const granularities = computed<Granularity[]>(
  () =>
    options.data?.time_granularities ?? [
      "hour",
      "day",
      "week",
      "month",
      "year",
    ],
);
const pageRows = computed(() =>
  rows.value.slice(
    (currentPage.value - 1) * pageSize.value,
    currentPage.value * pageSize.value,
  ),
);
const rowTotal = (row: MatrixRow) =>
  Object.values(row.values).reduce((sum, value) => sum + value, 0);
const grandTotal = computed(() =>
  Object.values(periodTotals.value).reduce((sum, value) => sum + value, 0),
);

const readField = (item: T, key: string) =>
  (item as unknown as Record<string, unknown>)[key];
const formatField = (key: string, value: unknown) =>
  props.fieldFormatters?.[key]?.(value) ??
  (value == null || value === "" ? "--" : String(value));
const periodLabel = (period: string) =>
  formatPeriodHeaderInContext(
    period,
    query.value?.granularity ?? "day",
    query.value?.start ?? period,
    query.value?.end ?? period,
  );
const fileSafe = (value: string) =>
  value.replace(/[\\/:*?"<>|]/g, "").replace(/\s+/g, "");
const exportDateLabel = (next: ReportQuery) => {
  const start = next.start.slice(0, 10);
  const end = new Date(next.end);
  if (next.granularity !== "hour")
    end.setMilliseconds(end.getMilliseconds() - 1);
  const endLabel = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, "0")}-${String(end.getDate()).padStart(2, "0")}`;
  return start === endLabel ? start : `${start}至${endLabel}`;
};
const exportDirectionLabel = (next: ReportQuery) => {
  const selectedIds = next.station_ids ?? next.direction_ids;
  if (!selectedIds.length) return props.filterLabel ? "全部收费站" : "全部方向";
  const names = selectedIds.map(
    (id) =>
      filterOptions.value.find((item) => item.value === id)?.label ?? String(id),
  );
  return names.join("+");
};

const fetchAll = async (next: ReportQuery) => {
  const first = await props.load({ ...next, page: 1, page_size: 500 });
  const pages = Math.ceil(first.total / 500);
  const results = [first];
  for (let page = 2; page <= pages; page += 1)
    results.push(await props.load({ ...next, page, page_size: 500 }));
  return results.flatMap((result) => result.items);
};

const fetch = async (next: ReportQuery) => {
  loading.value = true;
  error.value = "";
  query.value = next;
  currentPage.value = 1;
  try {
    const items = await fetchAll(next);
    const periodSet = new Set<string>();
    const totals: Record<string, number> = {};
    const matrix = new Map<string, MatrixRow>();
    for (const item of items) {
      const period = String(item.period);
      const eventCount = Number(item.event_count) || 0;
      periodSet.add(period);
      totals[period] = (totals[period] ?? 0) + eventCount;
      const fields = Object.fromEntries(
        props.rowFields.map((field) => [field.key, readField(item, field.key)]),
      );
      const key = props.rowFields
        .map((field) => String(fields[field.key] ?? ""))
        .join("|");
      const row = matrix.get(key) ?? {
        key,
        fields,
        values: {},
        directionOrder: showsDirection.value
          ? directionOrder.value.get(Number(readField(item, "direction_id")))
          : undefined,
        optionOrder: props.preserveRowOptionOrder
          ? optionOrder.value.get(String(fields[props.rowFields[0]?.key] ?? ""))
          : undefined,
      };
      row.values[period] = (row.values[period] ?? 0) + eventCount;
      matrix.set(key, row);
    }
    periods.value = [...periodSet].sort();
    periodTotals.value = totals;
    const matrixRows = [...matrix.values()].sort((left, right) => {
      if (
        left.directionOrder !== undefined ||
        right.directionOrder !== undefined
      )
        return (
          (left.directionOrder ?? Number.MAX_SAFE_INTEGER) -
          (right.directionOrder ?? Number.MAX_SAFE_INTEGER)
        );
      if (left.optionOrder !== undefined || right.optionOrder !== undefined)
        return (
          (left.optionOrder ?? Number.MAX_SAFE_INTEGER) -
          (right.optionOrder ?? Number.MAX_SAFE_INTEGER)
        );
      return (
        Object.values(right.values).reduce((sum, value) => sum + value, 0) -
        Object.values(left.values).reduce((sum, value) => sum + value, 0)
      );
    });
    if (props.topN && matrixRows.length > props.topN) {
      const other: MatrixRow = {
        key: "other",
        fields: Object.fromEntries(
          props.rowFields.map((field, index) => [
            field.key,
            index === 0 ? "其他" : "--",
          ]),
        ),
        values: {},
      };
      for (const row of matrixRows.slice(props.topN))
        for (const [period, value] of Object.entries(row.values))
          other.values[period] = (other.values[period] ?? 0) + value;
      rows.value = [...matrixRows.slice(0, props.topN), other];
    } else rows.value = matrixRows;
    return true;
  } catch {
    error.value = "报表请求失败，请检查条件或稍后重新查询。";
    return false;
  } finally {
    loading.value = false;
  }
};

const changePage = (page: number) => {
  currentPage.value = page;
};
const changeSize = (size: number) => {
  pageSize.value = size;
  currentPage.value = 1;
};
const summaryMethod = ({ columns }: { columns: unknown[] }) =>
  columns.map((_, index) => {
    if (index === 0) return "合计";
    if (index < props.rowFields.length) return "";
    const periodIndex = index - props.rowFields.length;
    if (periodIndex < periods.value.length)
      return formatNumber(periodTotals.value[periods.value[periodIndex]]);
    return formatNumber(grandTotal.value);
  });
const exportExcel = async (next: ReportQuery) => {
  if (!query.value || JSON.stringify(next) !== JSON.stringify(query.value)) {
    const ok = await fetch(next);
    if (!ok) return;
  }
  const XLSX = await import("xlsx");
  const headers = [
    ...props.rowFields.map((field) => field.label),
    ...periods.value.flatMap((period) =>
      props.includePercent
        ? [`${periodLabel(period)} 数量`, `${periodLabel(period)} 占比`]
        : [periodLabel(period)],
    ),
    ...(props.showTotals ? ["合计"] : []),
  ];
  const body = rows.value.map((row) => [
    ...props.rowFields.map((field) =>
      formatField(field.key, row.fields[field.key]),
    ),
    ...periods.value.flatMap((period) =>
      props.includePercent
        ? [
            row.values[period] ?? 0,
            formatPercent(row.values[period], periodTotals.value[period]),
          ]
        : [row.values[period] ?? 0],
    ),
    ...(props.showTotals ? [rowTotal(row)] : []),
  ]);
  if (props.showTotals)
    body.push([
      ...props.rowFields.map((_, index) => (index === 0 ? "合计" : "")),
      ...periods.value.map((period) => periodTotals.value[period] ?? 0),
      grandTotal.value,
    ]);
  const worksheet = XLSX.utils.aoa_to_sheet([headers, ...body]);
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, worksheet, "报表");
  const menu = String(route.meta.title ?? "报表");
  XLSX.writeFile(
    workbook,
    `${fileSafe(exportDirectionLabel(next))}${fileSafe(menu)}${exportDateLabel(next)}.xlsx`,
  );
};
onMounted(async () => {
  try {
    await options.load();
    await nextTick();
    filter.value?.submit();
  } catch {
    ElMessage.error("报表选项加载失败，请稍后重试");
  }
});
</script>

<template>
  <section class="report-page">
    <p v-if="note" class="report-note">{{ note }}</p>
    <ReportFilter
      ref="filter"
      :options="filterOptions"
      :option-label="filterLabel"
      :selection-param="selectionParam"
      :granularities="granularities"
      :loading="loading"
      :require-single-direction="requireSingleDirection"
      :extra-filters="extraFilters"
      @query="fetch"
      @export="exportExcel"
    />
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
    >
      <template #default
        ><el-button text type="primary" @click="query && fetch(query)"
          >重新查询</el-button
        ></template
      >
    </el-alert>
    <el-table
      v-loading="loading"
      :data="pageRows"
      border
      height="calc(100vh - 246px)"
      empty-text="暂无符合条件的数据"
      :show-summary="showTotals"
      :summary-method="summaryMethod"
    >
      <el-table-column
        v-for="field in rowFields"
        :key="field.key"
        :label="field.label"
        min-width="170"
        show-overflow-tooltip
      >
        <template #default="scope">{{
          formatField(field.key, scope.row.fields[field.key])
        }}</template>
      </el-table-column>
      <template v-for="period in periods" :key="period">
        <el-table-column
          v-if="includePercent"
          :label="periodLabel(period)"
          align="center"
        >
          <el-table-column label="数量" min-width="104" align="right"
            ><template #default="scope">{{
              formatNumber(scope.row.values[period])
            }}</template></el-table-column
          >
          <el-table-column label="占比" min-width="94" align="right"
            ><template #default="scope">{{
              formatPercent(scope.row.values[period], periodTotals[period])
            }}</template></el-table-column
          >
        </el-table-column>
        <el-table-column
          v-else
          :label="periodLabel(period)"
          min-width="104"
          align="right"
          ><template #default="scope">{{
            formatNumber(scope.row.values[period])
          }}</template></el-table-column
        >
      </template>
      <el-table-column
        v-if="showTotals"
        label="合计"
        min-width="112"
        align="right"
        ><template #default="scope">{{
          formatNumber(rowTotal(scope.row))
        }}</template></el-table-column
      >
    </el-table>
    <el-pagination
      class="report-pagination"
      background
      layout="total, sizes, prev, pager, next"
      :current-page="currentPage"
      :page-size="pageSize"
      :page-sizes="[20, 50, 100]"
      :total="rows.length"
      @current-change="changePage"
      @size-change="changeSize"
    />
  </section>
</template>

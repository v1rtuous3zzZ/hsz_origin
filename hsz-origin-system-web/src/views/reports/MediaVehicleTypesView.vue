<script setup lang="ts">
import { computed } from "vue";
import ReportPage from "./ReportPage.vue";
import { getMediaVehicleTypes } from "../../api/reports";
import { useReportOptionsStore } from "../../stores/report-options";

const rowFields = [
  { key: "media_type_name", label: "通行介质" },
  { key: "vehicle_type_name", label: "车型" },
];
const options = useReportOptionsStore();
const extraFilters = computed(() => [
  {
    key: "vehicle_type_codes" as const,
    label: "车型",
    placeholder: "全部车型",
    options: (options.data?.vehicle_types ?? []).map((item) => ({
      value: item.vehicle_type_code,
      label: item.vehicle_type_name,
    })),
  },
  {
    key: "media_type_codes" as const,
    label: "介质",
    placeholder: "全部介质",
    options: (options.data?.media_types ?? []).map((item) => ({
      value: item.media_type_code,
      label: item.media_type_name,
    })),
  },
]);
</script>

<template>
  <ReportPage
    flow="entry"
    :load="getMediaVehicleTypes"
    :row-fields="rowFields"
    :extra-filters="extraFilters"
    require-single-direction
    include-percent
    note="通行介质按 media_type 统计：1=OBU，2=CPC，其他或空值归为无介质。"
  />
</template>

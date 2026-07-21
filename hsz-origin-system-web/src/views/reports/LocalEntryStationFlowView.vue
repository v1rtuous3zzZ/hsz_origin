<script setup lang="ts">
import { computed } from "vue";
import { getLocalEntryStationFlow } from "../../api/reports";
import { useReportOptionsStore } from "../../stores/report-options";
import ReportPage from "./ReportPage.vue";

const options = useReportOptionsStore();
const stationOptions = computed(() =>
  (options.data?.local_entry_stations ?? []).map((station) => ({
    value: station.station_id,
    label: station.station_name,
    availability: "AVAILABLE" as const,
  })),
);
const rowFields = [{ key: "station_name", label: "收费站名称" }];
</script>

<template>
  <ReportPage
    flow="entry"
    :load="getLocalEntryStationFlow"
    :row-fields="rowFields"
    :filter-options="stationOptions"
    filter-label="收费站名称"
    selection-param="station_ids"
    preserve-row-option-order
    show-totals
  />
</template>

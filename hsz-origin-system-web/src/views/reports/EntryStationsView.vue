<script setup lang="ts">
import ReportPage from "./ReportPage.vue";
import { getEntryStations } from "../../api/reports";
const rowFields = [
  { key: "station_name", label: "收费站名称" },
  { key: "station_code", label: "收费站编码" },
];
</script>

<template>
  <ReportPage
    flow="entry"
    :load="getEntryStations"
    :row-fields="rowFields"
    require-single-direction
    :top-n="10"
    include-percent
  />
</template>

<script setup lang="ts">
import ReportPage from "./ReportPage.vue";
import { getExitFlow } from "../../api/reports";
const rowFields = [{ key: "direction_name", label: "方向名称" }];
</script>

<template>
  <ReportPage
    flow="exit"
    :load="getExitFlow"
    :row-fields="rowFields"
    show-totals
  />
</template>

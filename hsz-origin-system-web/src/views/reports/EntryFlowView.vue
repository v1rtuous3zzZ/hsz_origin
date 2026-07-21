<script setup lang="ts">
import ReportPage from "./ReportPage.vue";
import { getEntryFlow } from "../../api/reports";
const rowFields = [{ key: "direction_name", label: "方向名称" }];
</script>
<template>
  <ReportPage
    flow="entry"
    :load="getEntryFlow"
    :row-fields="rowFields"
    show-totals
  />
</template>

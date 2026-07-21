<script setup lang="ts">
import ReportPage from "./ReportPage.vue";
import { getVehicleTypes } from "../../api/reports";
const rowFields = [{ key: "vehicle_type_name", label: "车型" }];
</script>

<template>
  <ReportPage
    flow="entry"
    :load="getVehicleTypes"
    :row-fields="rowFields"
    require-single-direction
    include-percent
  />
</template>

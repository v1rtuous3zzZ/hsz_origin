<script setup lang="ts">
import ReportPage from "./ReportPage.vue";
import { getEntryProvinces } from "../../api/reports";
import { formatProvince } from "../../constants/provinces";

const rowFields = [{ key: "province_code", label: "入口省份" }];
const fieldFormatters = {
  province_code: (value: unknown) => formatProvince(String(value)),
};
</script>

<template>
  <ReportPage
    flow="entry"
    :load="getEntryProvinces"
    :row-fields="rowFields"
    :field-formatters="fieldFormatters"
    require-single-direction
    :top-n="5"
    include-percent
  />
</template>

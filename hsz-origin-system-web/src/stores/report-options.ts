import { defineStore } from "pinia";
import { getReportOptions } from "../api/reports";
import type { ReportOptions } from "../types/reports";
export const useReportOptionsStore = defineStore("report-options", {
  state: () => ({ data: null as ReportOptions | null, loading: false }),
  actions: {
    async load() {
      if (this.data) return this.data;
      this.loading = true;
      try {
        this.data = await getReportOptions();
        return this.data;
      } finally {
        this.loading = false;
      }
    },
  },
});

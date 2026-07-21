import {
  DataAnalysis,
  Location,
  OfficeBuilding,
  Tickets,
  TrendCharts,
  Clock,
  Monitor,
} from "@element-plus/icons-vue";

export const reportMenu = [
  { path: "/dashboard", title: "数据大屏", icon: Monitor },
  { path: "/reports/entry-flow", title: "入口流量统计", icon: TrendCharts },
  { path: "/reports/exit-flow", title: "出口流量统计", icon: DataAnalysis },
  {
    path: "/reports/local-entry-station-flow",
    title: "本路段数据统计",
    icon: OfficeBuilding,
  },
  { path: "/reports/vehicle-types", title: "入口车型统计", icon: Tickets },
  {
    path: "/reports/media-vehicle-types",
    title: "介质车型统计",
    icon: Tickets,
  },
  {
    path: "/reports/entry-stations",
    title: "入口站点统计",
    icon: OfficeBuilding,
  },
  { path: "/reports/entry-provinces", title: "入口省份统计", icon: Location },
  { path: "/sync-logs", title: "同步日志查看", icon: Clock },
];

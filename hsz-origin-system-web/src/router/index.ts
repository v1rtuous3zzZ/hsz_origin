import { createRouter, createWebHistory } from "vue-router";

import LoginView from "../views/LoginView.vue";
import NotFoundView from "../views/NotFoundView.vue";
import AppLayout from "../layouts/AppLayout.vue";
import EntryFlowView from "../views/reports/EntryFlowView.vue";
import ExitFlowView from "../views/reports/ExitFlowView.vue";
import LocalEntryStationFlowView from "../views/reports/LocalEntryStationFlowView.vue";
import VehicleTypesView from "../views/reports/VehicleTypesView.vue";
import MediaVehicleTypesView from "../views/reports/MediaVehicleTypesView.vue";
import EntryStationsView from "../views/reports/EntryStationsView.vue";
import EntryProvincesView from "../views/reports/EntryProvincesView.vue";
import SyncLogsView from "../views/SyncLogsView.vue";
import DashboardView from "../views/DashboardView.vue";
import { useAuthStore } from "../stores/auth";
import { setUnauthorizedHandler } from "../api/request";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/reports/entry-flow" },
    { path: "/login", component: LoginView, meta: { title: "登录" } },
    {
      path: "/dashboard",
      component: DashboardView,
      meta: { requiresAuth: true, title: "数据大屏" },
    },
    {
      path: "/reports",
      component: AppLayout,
      meta: { requiresAuth: true },
      children: [
        {
          path: "entry-flow",
          component: EntryFlowView,
          meta: { requiresAuth: true, title: "入口流量统计" },
        },
        {
          path: "exit-flow",
          component: ExitFlowView,
          meta: { requiresAuth: true, title: "出口流量统计" },
        },
        {
          path: "local-entry-station-flow",
          component: LocalEntryStationFlowView,
          meta: { requiresAuth: true, title: "本路段数据统计" },
        },
        {
          path: "vehicle-types",
          component: VehicleTypesView,
          meta: { requiresAuth: true, title: "入口车型统计" },
        },
        {
          path: "media-vehicle-types",
          component: MediaVehicleTypesView,
          meta: { requiresAuth: true, title: "介质车型统计" },
        },
        {
          path: "entry-stations",
          component: EntryStationsView,
          meta: { requiresAuth: true, title: "入口站点统计" },
        },
        {
          path: "entry-provinces",
          component: EntryProvincesView,
          meta: { requiresAuth: true, title: "入口省份统计" },
        },
      ],
    },
    {
      path: "/sync-logs",
      component: AppLayout,
      meta: { requiresAuth: true },
      children: [
        {
          path: "",
          component: SyncLogsView,
          meta: { requiresAuth: true, title: "同步日志查看" },
        },
      ],
    },
    { path: "/:pathMatch(.*)*", component: NotFoundView },
  ],
});

router.beforeEach((to) => {
  const auth = useAuthStore();
  const signedIn = auth.validate();
  const title = String(to.meta.title ?? "");
  document.title = title ? `沪苏浙溯源平台 - ${title}` : "沪苏浙溯源平台";
  if (to.meta.requiresAuth && !signedIn)
    return { path: "/login", query: { redirect: to.fullPath } };
  if (to.path === "/login" && signedIn) return "/reports/entry-flow";
  return true;
});
setUnauthorizedHandler(() => {
  const auth = useAuthStore();
  auth.signOut();
  if (router.currentRoute.value.path !== "/login")
    void router.push({
      path: "/login",
      query: { redirect: router.currentRoute.value.fullPath },
    });
});

export default router;

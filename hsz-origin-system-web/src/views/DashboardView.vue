<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import * as echarts from "echarts";
import {
  getDirectionFlow,
  getLocalStationFlow,
  getProvinceSummary,
  getRouteStack,
  getSectionRank,
  getVehicleTypeRatio,
} from "../api/dashboard";
import { formatProvince } from "../constants/provinces";

type ChartRef = echarts.ECharts | undefined;
type SeriesRow = { name: string; counts?: number[]; data?: number[]; stack?: string };
type RankRow = { name: string; count: number };
type ProvinceRow = {
  provinceId: string;
  count: number;
  compareCount?: number;
  weekCount?: number;
};
type DirectionRoute = {
  key: string;
  directionALabel?: string;
  directionBLabel?: string;
  directionACounts?: number[];
  directionBCounts?: number[];
};

const router = useRouter();
const now = ref("");
const routeChartEl = ref<HTMLDivElement>();
const directionChartEl = ref<HTMLDivElement>();
const stationChartEl = ref<HTMLDivElement>();
const vehicleChartEl = ref<HTMLDivElement>();
let routeChart: ChartRef;
let directionChart: ChartRef;
let stationChart: ChartRef;
let vehicleChart: ChartRef;
let clockTimer: number | undefined;
let refreshTimer: number | undefined;

const sectionItems = ref<RankRow[]>([]);
const sectionTotal = computed(() =>
  sectionItems.value.reduce((sum, item) => sum + Number(item.count || 0), 0),
);
const provinceRange = ref<"day" | "hour">("day");
const provinceRows = ref<ProvinceRow[]>([]);
const vehicleItems = ref<{ name: string; count: number }[]>([]);

const numberText = (value: number | string | undefined | null) =>
  String(Number(value) || 0).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const vehicleCount = (names: string[]) =>
  vehicleItems.value
    .filter((item) => names.includes(item.name))
    .reduce((sum, item) => sum + Number(item.count || 0), 0);
const passengerTotal = computed(() => vehicleCount(["客车1-3", "客车其他"]));
const truckTotal = computed(() => vehicleCount(["货车1-4", "货车其他"]));
const specialTotal = computed(() => vehicleCount(["专项作业车"]));

const updateTime = () => {
  const date = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  now.value = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
};

const ensureCharts = () => {
  if (!routeChart && routeChartEl.value) routeChart = echarts.init(routeChartEl.value);
  if (!directionChart && directionChartEl.value) directionChart = echarts.init(directionChartEl.value);
  if (!stationChart && stationChartEl.value) stationChart = echarts.init(stationChartEl.value);
  if (!vehicleChart && vehicleChartEl.value) vehicleChart = echarts.init(vehicleChartEl.value);
};

const baseAxis = (times: string[]) => ({
  xAxis: {
    type: "category",
    data: times,
    axisLine: { lineStyle: { color: "rgba(255,255,255,0.2)" } },
    axisTick: { show: false },
    axisLabel: { color: "#a9c9e8", fontSize: 10 },
  },
  yAxis: {
    type: "value",
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: "#a9c9e8", fontSize: 10 },
    splitLine: { lineStyle: { color: "rgba(120,190,255,0.22)", type: "dashed" } },
  },
});

const tooltip = {
  trigger: "axis",
  confine: true,
  backgroundColor: "rgba(9,18,35,0.92)",
  borderColor: "rgba(63,183,255,0.4)",
  borderWidth: 1,
  textStyle: { color: "#e6f2ff", fontSize: 11 },
};

const normalize = (list: unknown, size: number) => {
  const result = new Array(size).fill(0);
  if (!Array.isArray(list)) return result;
  list.slice(0, size).forEach((value, index) => {
    result[index] = Number(value) || 0;
  });
  return result;
};

const drawRouteStack = async () => {
  const { data } = await getRouteStack();
  const times = Array.isArray(data.times) ? data.times : [];
  const series = (Array.isArray(data.series) ? data.series : []).map((item: SeriesRow) => ({
    name: item.name,
    type: "bar",
    stack: item.stack,
    barWidth: 8,
    data: normalize(item.data, times.length),
  }));
  routeChart?.setOption(
    {
      color: ["#f2a03f", "#3fb7ff", "#39d6c6", "#58c0ff", "#7fe0d6", "#7fb8ff", "#8fe6e0"],
      grid: { left: 36, right: 16, top: 24, bottom: 42 },
      legend: { show: false },
      tooltip,
      ...baseAxis(times),
      dataZoom: [
        {
          type: "slider",
          height: 14,
          bottom: 8,
          start: 0,
          end: 70,
          handleSize: 10,
          handleStyle: { color: "#3fb7ff" },
          textStyle: { color: "#a9c9e8", fontSize: 9 },
          borderColor: "rgba(63,183,255,0.3)",
          fillerColor: "rgba(63,183,255,0.18)",
          backgroundColor: "rgba(15,35,60,0.6)",
        },
        { type: "inside" },
      ],
      series,
    },
    true,
  );
};

const drawDirectionFlow = async () => {
  const { data } = await getDirectionFlow();
  const times = Array.isArray(data.times) ? data.times : [];
  const routes: DirectionRoute[] = Array.isArray(data.routes) ? data.routes : [];
  const route = routes.find((item) => item.key === "G50") ?? routes[0];
  const series = [];
  if (route?.directionALabel) {
    series.push({
      name: route.directionALabel,
      type: "line",
      smooth: true,
      symbol: "none",
      lineStyle: { width: 2, shadowColor: "rgba(63,183,255,0.55)", shadowBlur: 10 },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: "rgba(63,183,255,0.45)" },
          { offset: 1, color: "rgba(63,183,255,0.06)" },
        ]),
      },
      data: normalize(route.directionACounts, times.length),
    });
  }
  if (route?.directionBLabel) {
    series.push({
      name: route.directionBLabel,
      type: "line",
      smooth: true,
      symbol: "none",
      lineStyle: { width: 1.8, shadowColor: "rgba(57,214,198,0.45)", shadowBlur: 8 },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: "rgba(57,214,198,0.32)" },
          { offset: 1, color: "rgba(57,214,198,0.05)" },
        ]),
      },
      data: normalize(route.directionBCounts, times.length),
    });
  }
  directionChart?.setOption(
    {
      color: ["#3fb7ff", "#39d6c6"],
      grid: { left: 32, right: 16, top: 34, bottom: 28 },
      legend: { top: 2, right: 8, textStyle: { color: "#cfe8ff", fontSize: 10 }, itemWidth: 14, itemHeight: 8 },
      tooltip,
      ...baseAxis(times),
      series,
    },
    true,
  );
};

const drawStationFlow = async () => {
  const { data } = await getLocalStationFlow();
  const times = Array.isArray(data.times) ? data.times : [];
  const palette = ["#5FB27A", "#C7886B", "#6E8FE0", "#D4838F", "#5E9DD8", "#A3C26A", "#D4A14A"];
  const series = (Array.isArray(data.series) ? data.series : []).map((item: SeriesRow, index: number) => ({
    name: item.name,
    type: "line",
    smooth: true,
    showSymbol: false,
    lineStyle: { width: 2, color: palette[index % palette.length] },
    itemStyle: { color: palette[index % palette.length] },
    data: normalize(item.counts, times.length),
  }));
  stationChart?.setOption(
    {
      color: palette,
      grid: { left: 32, right: 32, top: 32, bottom: 26 },
      legend: {
        type: "scroll",
        top: 2,
        left: "center",
        icon: "line",
        textStyle: { color: "#cfe8ff", fontSize: 10 },
        itemWidth: 18,
        itemHeight: 2,
        pageIconColor: "#79aef8",
        pageIconInactiveColor: "rgba(121,174,248,0.25)",
        pageTextStyle: { color: "#a9c9e8", fontSize: 10 },
      },
      tooltip,
      ...baseAxis(times),
      series,
    },
    true,
  );
};

const drawVehicleRatio = async () => {
  const { data } = await getVehicleTypeRatio();
  const items = Array.isArray(data.items) ? data.items : [];
  vehicleItems.value = items.map((item: { name: string; count: number }) => ({
    name: item.name,
    count: Number(item.count) || 0,
  }));
  vehicleChart?.setOption(
    {
      color: ["#3fb7ff", "#39d6c6", "#2b62ff", "#4fd17a", "#f2a03f"],
      tooltip: { trigger: "item", backgroundColor: "rgba(9,18,35,0.92)", textStyle: { color: "#e6f2ff" } },
      series: [
        {
          type: "pie",
          radius: ["30%", "58%"],
          center: ["44%", "44%"],
          avoidLabelOverlap: false,
          minAngle: 4,
          label: {
            color: "#d7ecff",
            fontSize: 8,
            lineHeight: 10,
            formatter: (params: { name: string; value: number }) => (params.value ? params.name : ""),
          },
          labelLine: { length: 16, length2: 14, lineStyle: { color: "rgba(255,255,255,0.45)" } },
          labelLayout: { hideOverlap: true },
          data: vehicleItems.value.map((item) => ({ name: item.name, value: item.count })),
        },
      ],
    },
    true,
  );
};

const loadSectionRank = async () => {
  const { data } = await getSectionRank();
  sectionItems.value = Array.isArray(data.items) ? data.items : [];
};

const loadProvince = async () => {
  const { data } = await getProvinceSummary(provinceRange.value);
  provinceRows.value = (Array.isArray(data.items) ? data.items : []).slice(0, 4);
};

const refresh = async () => {
  await nextTick();
  ensureCharts();
  await Promise.allSettled([
    drawRouteStack(),
    drawDirectionFlow(),
    drawStationFlow(),
    drawVehicleRatio(),
    loadSectionRank(),
    loadProvince(),
  ]);
};

const resize = () => {
  routeChart?.resize();
  directionChart?.resize();
  stationChart?.resize();
  vehicleChart?.resize();
};

onMounted(() => {
  updateTime();
  clockTimer = window.setInterval(updateTime, 1000);
  void refresh();
  refreshTimer = window.setInterval(refresh, 10 * 60 * 1000);
  window.addEventListener("resize", resize);
});

onBeforeUnmount(() => {
  if (clockTimer) window.clearInterval(clockTimer);
  if (refreshTimer) window.clearInterval(refreshTimer);
  window.removeEventListener("resize", resize);
  routeChart?.dispose();
  directionChart?.dispose();
  stationChart?.dispose();
  vehicleChart?.dispose();
});
</script>

<template>
  <div class="dashboard-screen">
    <button
      class="dashboard-back"
      type="button"
      @click="router.push('/reports/entry-flow')"
    >
      返回管理后台
    </button>
    <div class="dashboard-title">沪苏浙溯源平台</div>
    <div class="dashboard-time">{{ now }}</div>
    <div class="dashboard-panels">
      <div class="panel-col panel-col--left">
        <section class="panel-item panel-item--left">
          <div class="panel-title-bg"></div>
          <div class="panel-title-text">流量趋势</div>
          <div class="panel-item__content"><div ref="routeChartEl" class="chart"></div></div>
        </section>
        <section class="panel-item panel-item--left">
          <div class="panel-title-bg"></div>
          <div class="panel-title-text">外省流量趋势</div>
          <div class="panel-item__content">
            <div class="direction-tabs"><span class="direction-tab direction-tab--active">G50</span><span class="direction-tab">G1521</span><span class="direction-tab">G1522</span><span class="direction-tab">S17</span></div>
            <div class="chart-label">流量趋势</div>
            <div ref="directionChartEl" class="chart chart--with-tabs"></div>
          </div>
        </section>
        <section class="panel-item panel-item--left">
          <div class="panel-title-bg"></div>
          <div class="panel-title-text">本路段流量趋势</div>
          <div class="panel-item__content"><div ref="stationChartEl" class="chart"></div></div>
        </section>
      </div>
      <div class="panel-col panel-col--right">
        <section class="panel-item panel-item--right">
          <div class="panel-title-bg"></div>
          <div class="panel-title-text">断面流量排名</div>
          <div class="panel-item__content">
            <div class="rank-layout">
              <div class="rank-total"><strong>{{ numberText(sectionTotal) }}</strong><span>实时流量总数</span></div>
              <div class="rank-list">
                <div v-for="(item, index) in sectionItems" :key="item.name" class="rank-row">
                  <div><span>No.{{ index + 1 }}</span><b>{{ item.name }}</b><em>{{ numberText(item.count) }}</em></div>
                  <i :style="{ width: `${sectionTotal ? Math.min((item.count / Math.max(...sectionItems.map((row) => row.count))) * 100, 100) : 0}%` }"></i>
                </div>
                <div v-if="!sectionItems.length" class="empty">暂无数据</div>
              </div>
            </div>
          </div>
        </section>
        <section class="panel-item panel-item--right">
          <div class="panel-title-bg"></div>
          <div class="panel-title-text">当天车型占比</div>
          <div class="panel-item__content">
            <div class="vehicle-layout">
              <div class="vehicle-chart"><div ref="vehicleChartEl" class="chart"></div></div>
              <div class="vehicle-summary">
                <div class="vehicle-card"><span>客车数量</span><strong>{{ numberText(passengerTotal) }}</strong></div>
                <div class="vehicle-card"><span>货车数量</span><strong>{{ numberText(truckTotal) }}</strong></div>
                <div class="vehicle-card"><span>专项车数量</span><strong>{{ numberText(specialTotal) }}</strong></div>
              </div>
            </div>
          </div>
        </section>
        <section class="panel-item panel-item--right">
          <div class="panel-title-bg"></div>
          <div class="panel-title-text">来源省份统计</div>
          <div class="panel-item__content">
            <div class="province-tabs">
              <button :class="{ active: provinceRange === 'day' }" @click="provinceRange = 'day'; loadProvince()">当日</button>
              <button :class="{ active: provinceRange === 'hour' }" @click="provinceRange = 'hour'; loadProvince()">近1小时</button>
            </div>
            <div class="province-table">
              <div class="province-row province-head"><span>省名称</span><span>数量</span><span>昨日</span><span>一周内</span></div>
              <div v-for="item in provinceRows" :key="item.provinceId" class="province-row">
                <span>{{ formatProvince(item.provinceId) }}</span><span>{{ numberText(item.count) }}</span><span>{{ item.compareCount == null ? "--" : numberText(item.compareCount) }}</span><span>{{ item.weekCount == null ? "--" : numberText(item.weekCount) }}</span>
              </div>
              <div v-if="!provinceRows.length" class="empty">暂无数据</div>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard-screen {
  position: fixed;
  inset: 0;
  overflow: hidden;
  background: #061526;
  font-family: "IBM Plex Sans", "Microsoft YaHei", Arial, sans-serif;
}
.dashboard-screen::before,
.dashboard-screen::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.dashboard-screen::before {
  background: url("../assets/dashboard/demo.jpg") center center / 100% 100% no-repeat;
  z-index: 0;
}
.dashboard-screen::after {
  background: url("../assets/dashboard/bg.png") center center / 100% 100% no-repeat;
  z-index: 1;
}
.dashboard-title,
.dashboard-time,
.dashboard-back,
.dashboard-panels {
  position: absolute;
  z-index: 3;
}
.dashboard-title {
  top: 15px;
  left: 50%;
  transform: translateX(-50%);
  color: #fff;
  font-size: 32px;
  font-weight: 600;
  letter-spacing: 2px;
  text-align: center;
  white-space: nowrap;
}
.dashboard-time {
  top: 18px;
  right: 24px;
  color: #fff;
  font-size: 18px;
}
.dashboard-back {
  top: 16px;
  left: 16px;
  height: 32px;
  padding: 0 14px;
  border: 1px solid rgba(63, 183, 255, 0.5);
  border-radius: 6px;
  background: linear-gradient(135deg, rgba(20, 72, 118, 0.8), rgba(8, 24, 42, 0.4));
  color: #e6f2ff;
  font-size: 13px;
  cursor: pointer;
  box-shadow: inset 0 0 10px rgba(63, 183, 255, 0.25);
}
.dashboard-panels {
  top: 88px;
  left: 10px;
  right: 10px;
  bottom: 24px;
  display: flex;
  justify-content: space-between;
}
.panel-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  width: 25%;
  min-width: 0;
}
.panel-item {
  position: relative;
  flex: 1;
  margin: 0;
  background-position: center;
  background-repeat: no-repeat;
  background-size: 100% 100%;
  overflow: hidden;
}
.panel-item--left {
  background-image: url("../assets/dashboard/left_bg.png");
}
.panel-item--right {
  background-image: url("../assets/dashboard/right_bg.png");
}
.panel-title-bg {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 46px;
  background: url("../assets/dashboard/title_bg.png") center center / 100% 100% no-repeat;
}
.panel-title-text {
  position: absolute;
  top: 0;
  left: 58px;
  height: 46px;
  display: flex;
  align-items: center;
  font-size: 16px;
  font-weight: 700;
  color: #fff;
  z-index: 2;
}
.panel-item__content {
  position: absolute;
  top: 46px;
  left: 0;
  right: 0;
  bottom: 40px;
  padding: 6px 10px 46px;
  overflow: hidden;
  box-sizing: border-box;
  z-index: 2;
}
.chart {
  width: 100%;
  height: 100%;
}
.chart--with-tabs {
  height: calc(100% - 64px);
}
.direction-tabs {
  display: flex;
  gap: 8px;
  padding: 4px 6px;
}
.direction-tab {
  flex: 1;
  text-align: center;
  padding: 8px 0;
  border-radius: 6px;
  border: 1px solid rgba(63, 183, 255, 0.18);
  background: linear-gradient(135deg, rgba(20, 72, 118, 0.55), rgba(8, 24, 42, 0.25));
  color: rgba(255, 255, 255, 0.45);
  font-size: 13px;
}
.direction-tab--active {
  color: #e9f7ff;
  border-color: rgba(63, 183, 255, 0.7);
  box-shadow: inset 0 0 14px rgba(63, 183, 255, 0.45), 0 0 10px rgba(63, 183, 255, 0.35);
}
.chart-label {
  padding: 6px 8px 0;
  color: rgba(255, 255, 255, 0.7);
  font-size: 12px;
}
.rank-layout {
  display: grid;
  grid-template-columns: 160px 1fr;
  gap: 10px;
  height: 100%;
  color: #d7ecff;
  padding-bottom: 18px;
  box-sizing: border-box;
}
.rank-total {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-right: 1px solid rgba(255, 255, 255, 0.15);
}
.rank-total strong {
  color: #37c6ff;
  font-size: 30px;
}
.rank-total span {
  margin-top: 6px;
  font-size: 14px;
}
.rank-list {
  position: relative;
  overflow: hidden;
  padding-right: 6px;
}
.rank-row {
  padding: 4px 0;
}
.rank-row div {
  display: flex;
  align-items: center;
}
.rank-row span {
  color: #3fb7ff;
  font-weight: 700;
}
.rank-row b {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-left: 6px;
  font-size: 13px;
  max-width: 180px;
}
.rank-row em {
  color: #9ad9ff;
  font-style: normal;
  font-size: 12px;
}
.rank-row i {
  display: block;
  height: 5px;
  margin-top: 4px;
  border-radius: 4px;
  background: linear-gradient(90deg, #3fb7ff, #2b62ff);
}
.vehicle-layout {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 100%;
  min-height: 0;
  padding: 4px 6px 14px 4px;
  box-sizing: border-box;
}
.vehicle-chart {
  flex: 1 1 auto;
  height: 100%;
  min-width: 0;
  padding-right: 6px;
}
.vehicle-summary {
  flex: 0 0 22%;
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
}
.vehicle-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: flex-start;
  padding: 8px 10px;
  border: 1px solid rgba(63, 183, 255, 0.25);
  border-radius: 6px;
  background: linear-gradient(135deg, rgba(18, 55, 92, 0.75), rgba(9, 26, 45, 0.35));
  box-shadow: inset 0 0 14px rgba(38, 118, 189, 0.25);
}
.vehicle-card span {
  color: rgba(255, 255, 255, 0.65);
  font-size: 12px;
  white-space: nowrap;
}
.vehicle-card strong {
  margin-top: 4px;
  color: #37c6ff;
  font-size: 18px;
  letter-spacing: 0.5px;
}
.province-tabs {
  display: flex;
  justify-content: flex-end;
  gap: 0;
  padding: 4px;
}
.province-tabs button {
  min-width: 64px;
  padding: 4px 10px;
  border: 1px solid rgba(63, 183, 255, 0.2);
  background: rgba(16, 36, 62, 0.6);
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
}
.province-tabs button.active {
  color: #e9f7ff;
  background: rgba(63, 183, 255, 0.18);
}
.province-table {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 12px 12px;
  color: #d7ecff;
}
.province-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  padding: 6px 8px;
  border-radius: 6px;
  background: rgba(16, 36, 62, 0.35);
  font-size: 12px;
}
.province-row span:not(:first-child) {
  text-align: right;
}
.province-head {
  background: rgba(31, 74, 120, 0.35);
}
.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 80px;
  color: rgba(255, 255, 255, 0.6);
  font-size: 12px;
}
</style>

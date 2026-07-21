import request from "./request";

const pad = (value: number) => String(value).padStart(2, "0");
const formatDateTime = (value: Date) =>
  `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}:00`;

export const todayRange = () => {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  return { start: formatDateTime(start), end: formatDateTime(end) };
};

type DashboardRange = { start: string; end: string };
let cachedRange: DashboardRange | undefined;

export const getLatestDashboardRange = async (): Promise<DashboardRange> => {
  if (cachedRange) return cachedRange;
  const { data } = await request.get<{
    start: string | null;
    end: string | null;
    latest_hour: string | null;
  }>("/dashboard/latest-range");
  cachedRange = data.start && data.end ? { start: data.start, end: data.end } : todayRange();
  return cachedRange;
};

export const currentHourRange = () => {
  const end = new Date();
  const start = new Date(end);
  start.setHours(start.getHours() - 1, start.getMinutes(), 0, 0);
  return { start: formatDateTime(start), end: formatDateTime(end) };
};

export const provinceRanges = (type: "day" | "hour", dayRange?: DashboardRange) => {
  const range = type === "day" && dayRange ? dayRange : type === "day" ? todayRange() : currentHourRange();
  const currentStart = new Date(range.start);
  const currentEnd = new Date(range.end);
  const compareStart = new Date(currentStart);
  compareStart.setDate(compareStart.getDate() - 1);
  const compareEnd = new Date(currentEnd);
  compareEnd.setDate(compareEnd.getDate() - 1);
  const weekStart = new Date();
  weekStart.setDate(weekStart.getDate() - 7);
  weekStart.setHours(0, 0, 0, 0);
  return {
    start: range.start,
    end: range.end,
    compare_start: formatDateTime(compareStart),
    compare_end: formatDateTime(compareEnd),
    week_start: formatDateTime(weekStart),
    week_end: formatDateTime(new Date()),
  };
};

export const getRouteStack = () =>
  getLatestDashboardRange().then((params) => request.get("/dashboard/route-stack", { params }));

export const getDirectionFlow = () =>
  getLatestDashboardRange().then((params) => request.get("/dashboard/direction-flow", { params }));

export const getLocalStationFlow = () =>
  getLatestDashboardRange().then((range) =>
    request.get("/dashboard/local-station-flow", {
      params: { ...range, limit: 30 },
    }),
  );

export const getSectionRank = () =>
  getLatestDashboardRange().then((range) => {
    const end = new Date(range.end);
    const start = new Date(end);
    start.setHours(start.getHours() - 1);
    return request.get("/dashboard/section-rank", {
      params: { start: formatDateTime(start), end: formatDateTime(end), limit: 20 },
    });
  });

export const getVehicleTypeRatio = () =>
  getLatestDashboardRange().then((params) => request.get("/dashboard/vehicle-type-ratio", { params }));

export const getProvinceSummary = (type: "day" | "hour") =>
  getLatestDashboardRange().then((range) =>
    request.get("/dashboard/province-summary", { params: provinceRanges(type, range) }),
  );

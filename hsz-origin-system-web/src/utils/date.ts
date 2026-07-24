import type { Granularity, ReportPeriod } from "../types/reports";

const pad = (value: number) => String(value).padStart(2, "0");
export const toLocalIso = (value: Date) =>
  `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}:00`;
export const defaultRange = () => {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return [today, new Date(today)] as [Date, Date];
};

export const defaultHourRange = () => {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  return [start, new Date()] as [Date, Date];
};
const formatPeriod = (
  period: ReportPeriod,
  granularity: Granularity,
) => {
  const value = String(period);
  if (granularity === "year") return `${value}年`;
  if (granularity === "month") return value.slice(0, 7);
  return value.replace("T", " ").slice(0, granularity === "hour" ? 13 : 10);
};

export const formatPeriodHeaderInContext = (
  period: ReportPeriod,
  granularity: Granularity,
  start: string,
  end: string,
) => {
  const value = String(period);
  const rangeEnd = new Date(end);
  rangeEnd.setMilliseconds(rangeEnd.getMilliseconds() - 1);
  const endDate = `${rangeEnd.getFullYear()}-${pad(rangeEnd.getMonth() + 1)}-${pad(rangeEnd.getDate())}`;
  const spansMultipleDays = start.slice(0, 10) !== endDate;
  const spansMultipleMonths = start.slice(0, 7) !== endDate.slice(0, 7);
  const month = Number(value.slice(5, 7));
  const day = Number(value.slice(8, 10));
  if (granularity === "hour") {
    const hour = Number(value.slice(11, 13));
    return spansMultipleDays ? `${month}月${day}日 ${hour}时` : `${hour}时`;
  }
  if (granularity === "day")
    return spansMultipleMonths ? `${month}月${day}日` : `${day}日`;
  if (granularity === "month") return `${month}月`;
  if (granularity === "year") return `${value}年`;
  return formatPeriod(period, granularity);
};

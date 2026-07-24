import request from "./request";
import type {
  EntryProvinceRow,
  EntryStationRow,
  FlowRow,
  LocalEntryStationFlowRow,
  MediaVehicleTypeRow,
  PageResult,
  ReportOptions,
  ReportQuery,
  VehicleTypeRow,
} from "../types/reports";

interface SyncLog {
  sync_id: string;
  task_no: string;
  operation: "LIVE" | "BACKFILL" | "REPAIR" | "CHECK";
  server_code: string;
  source_table: string | null;
  status: "SUCCESS" | "FAILED" | "RUNNING" | "SKIPPED";
  check_status: "UNCHECKED" | "COMPLETE" | "MISSING";
  window_start: string;
  window_end: string;
  started_at: string;
  finished_at: string | null;
  source_unique_count: number;
  center_matched_count: number;
  missing_count: number;
  inserted_count: number;
  query_duration_ms: number;
  total_duration_ms: number;
  error_message: string | null;
}

export interface ManualSyncJob {
  job_id: number;
  task_no: string;
  status: "PENDING" | "RUNNING" | "SUCCESS" | "PARTIAL" | "FAILED";
}

export interface SyncLogResult {
  total: number;
  items: SyncLog[];
}

export interface MissingWindow extends Pick<SyncLog, "server_code" | "window_start" | "window_end" | "source_unique_count" | "center_matched_count" | "missing_count" | "check_status"> {
  latest_sync_id: string;
}

const params = (query: ReportQuery) => ({
  ...query,
  direction_ids: query.direction_ids.length ? query.direction_ids : undefined,
});
export const getReportOptions = () =>
  request.get<ReportOptions>("/reports/options").then(({ data }) => data);
export const getEntryFlow = (query: ReportQuery) =>
  request
    .get<PageResult<FlowRow>>("/reports/entry-flow", { params: params(query) })
    .then(({ data }) => data);
export const getExitFlow = (query: ReportQuery) =>
  request
    .get<PageResult<FlowRow>>("/reports/exit-flow", { params: params(query) })
    .then(({ data }) => data);
export const getLocalEntryStationFlow = (query: ReportQuery) =>
  request
    .get<PageResult<LocalEntryStationFlowRow>>("/reports/local-entry-station-flow", {
      params: {
        ...query,
        direction_ids: undefined,
        station_ids: query.station_ids?.length ? query.station_ids : undefined,
      },
    })
    .then(({ data }) => data);
export const getVehicleTypes = (query: ReportQuery) =>
  request
    .get<PageResult<VehicleTypeRow>>("/reports/vehicle-types", {
      params: params(query),
    })
    .then(({ data }) => data);
export const getMediaVehicleTypes = (query: ReportQuery) =>
  request
    .get<PageResult<MediaVehicleTypeRow>>("/reports/media-vehicle-types", {
      params: params(query),
    })
    .then(({ data }) => data);
export const getEntryStations = (query: ReportQuery) =>
  request
    .get<PageResult<EntryStationRow>>("/reports/entry-stations", {
      params: params(query),
    })
    .then(({ data }) => data);
export const getEntryProvinces = (query: ReportQuery) =>
  request
    .get<PageResult<EntryProvinceRow>>("/reports/entry-provinces", {
      params: params(query),
    })
    .then(({ data }) => data);
export const getSyncLogs = (start: string, end: string, status?: string, page = 1, pageSize = 20) =>
  request
    .get<SyncLogResult>("/etl/sync-logs", {
      params: { start, end, status, page, page_size: pageSize },
    })
    .then(({ data }) => data);
export const getMissingWindows = () => request
  .get<{ items: MissingWindow[] }>("/etl/missing-windows")
  .then(({ data }) => data.items);
export const startManualSync = (start: string, end: string) =>
  request
    .post<ManualSyncJob>("/etl/jobs/backfill", { start, end })
    .then(({ data }) => data);
export const repairSyncWindow = (syncId: string) =>
  request
    .post<ManualSyncJob>(`/etl/sync-logs/${syncId}/repair`)
    .then(({ data }) => data);

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

export interface SyncBatch {
  batch_id: number;
  batch_no: string;
  status: "SUCCESS" | "FAILED" | "RUNNING";
  window_start: string;
  window_end: string;
  started_at: string;
  finished_at: string | null;
  source_row_count: number;
  success_event_count: number;
  matched_event_count: number;
  error_count: number;
  error_summary: string | null;
}
export interface SyncLogResult {
  total: number;
  items: SyncBatch[];
  summary: null | {
    success_count: number;
    failed_count: number;
    running_count: number;
    missing_windows: { start: string; end: string }[];
  };
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
export const getSyncLogs = (start: string, end: string, status?: string) =>
  request
    .get<SyncLogResult>("/etl/batches", {
      params: { start, end, status, page_size: 100 },
    })
    .then(({ data }) => data);
export const startManualSync = (start: string, end: string) =>
  request.post("/etl/manual-sync", { start, end }).then(({ data }) => data);
export const retrySyncSource = (batchId: number, sourceId: number) =>
  request.post(`/etl/batches/${batchId}/sources/${sourceId}/retry`).then(({ data }) => data);

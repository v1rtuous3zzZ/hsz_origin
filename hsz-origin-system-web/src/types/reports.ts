export type Granularity = "hour" | "day" | "week" | "month" | "year";
export type ReportPeriod = string | number;

export interface DirectionOption {
  direction_id: number;
  direction_name: string;
  availability: "AVAILABLE" | "UNAVAILABLE";
}
interface LocalEntryStationOption {
  station_id: number;
  station_name: string;
}
interface VehicleTypeOption {
  vehicle_type_code: string;
  vehicle_type_name: string;
}
interface MediaTypeOption {
  media_type_code: string;
  media_type_name: string;
}
export interface SelectableOption {
  value: number | string;
  label: string;
  availability?: "AVAILABLE" | "UNAVAILABLE";
}
export interface ReportOptions {
  entry_directions: DirectionOption[];
  exit_directions: DirectionOption[];
  local_entry_stations: LocalEntryStationOption[];
  vehicle_types: VehicleTypeOption[];
  media_types: MediaTypeOption[];
  time_granularities: Granularity[];
}
export interface PageResult<T> {
  page: number;
  page_size: number;
  total: number;
  items: T[];
}
export interface ReportQuery {
  start: string;
  end: string;
  granularity: Granularity;
  direction_ids: number[];
  station_ids?: number[];
  vehicle_type_codes?: string[];
  media_type_codes?: string[];
  page: number;
  page_size: number;
}
export interface FlowRow {
  period: ReportPeriod;
  direction_id: number;
  direction_name: string;
  event_count: number;
}
export interface LocalEntryStationFlowRow {
  period: ReportPeriod;
  station_name: string;
  event_count: number;
}
export interface VehicleTypeRow extends FlowRow {
  vehicle_type_code: string;
  vehicle_type_name: string;
}
export interface MediaVehicleTypeRow extends VehicleTypeRow {
  media_type_code: string;
  media_type_name: string;
}
export interface EntryStationRow extends FlowRow {
  station_code: string | null;
  station_name: string | null;
}
export interface EntryProvinceRow extends FlowRow {
  province_code: string;
}

import request from './request'

export interface GantrySummary {
  source_server_count: number
  physical_gantry_count: number
  logical_gantry_count: number
  active_mapping_count: number
  stat_object_count: number
  stat_rule_count: number
}

export const getGantrySummary = () =>
  request.get<GantrySummary>('/system/gantry-summary').then((response) => response.data)

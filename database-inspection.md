# hsz_origin 数据库只读检查

检查时间：2026-07-16（只执行 `SELECT`、`SHOW` 与 `information_schema` 查询）。

- MySQL：8.0.46
- 数据库默认字符集：`utf8mb4`，排序规则：`utf8mb4_0900_ai_ci`
- 已检查全部字符串字段，均为 `utf8mb4`。
- 已检查 `information_schema.columns` 与 `information_schema.statistics`；主要表均存在主键和查询索引。

| 表 | 实际数量 | 预期 |
| --- | ---: | ---: |
| t_stat_object | 16 | 16 |
| t_stat_rule | 28 | 28 |
| t_base_facility_catalog | 335236 | 335236 |
| t_toll_station | 15665 | 15665 |
| t_base_gantry_catalog | 39 | 39 |
| t_source_server | 13 | 13 |
| t_logical_gantry | 32 | 32 |
| t_physical_gantry | 39 | 39 |
| t_physical_logical_gantry_rel | 39 | 39 |
| t_legacy_direction_daily_stat | 1200 | 1200 |

完整性结果：13 台源服务器、39 个物理门架、32 个逻辑门架及 39 条有效映射全部一致；没有已启用物理门架缺少有效逻辑映射；没有已启用规则的当前门架缺少物理映射。

以下 7 个逻辑 HEX 各保留两个物理门架：`282C08`、`291F0F`、`292C08`、`2A2C01`、`2A2C09`、`2B2C01`、`2B2C09`。

认证相关：`t_user`（唯一用户名、密码哈希、启用与锁定状态）及 `t_user_session`。本阶段没有创建或修改这些表。

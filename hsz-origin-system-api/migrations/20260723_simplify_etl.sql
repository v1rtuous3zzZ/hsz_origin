-- ETL TradeId 主键简化迁移。仅允许在中心库 hsz_origin 执行，严禁在门架源库执行。
-- 破坏性操作范围：旧 ETL 日志/任务表、ODS 模板/月表和命中模板/月表会被删除重建。
-- 原因：TradeId 已确认为全渠道唯一，旧 event_key/source_trade_id 双标识结构不再保留。

DELIMITER $$
CREATE PROCEDURE assert_center_database_for_trade_id_migration()
BEGIN
    IF DATABASE() <> 'hsz_origin' THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT='当前数据库不是允许迁移的中心库 hsz_origin，已停止';
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.TABLES
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='dfs_gantry_transaction'
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT='当前库疑似门架源库，严禁执行中心库迁移';
    END IF;
END$$
CALL assert_center_database_for_trade_id_migration()$$
DROP PROCEDURE assert_center_database_for_trade_id_migration$$
DELIMITER ;

DROP PROCEDURE IF EXISTS sp_create_event_month_tables;

DROP TABLE IF EXISTS t_etl_checkpoint;
DROP TABLE IF EXISTS t_etl_batch_source;
DROP TABLE IF EXISTS t_etl_quality;
DROP TABLE IF EXISTS t_data_freshness;
DROP TABLE IF EXISTS t_etl_batch;
DROP TABLE IF EXISTS t_etl_manual_job;
DROP TABLE IF EXISTS t_etl_sync_log;

DELIMITER $$
CREATE PROCEDURE drop_trade_id_month_tables()
BEGIN
    DECLARE done INT DEFAULT 0;
    DECLARE table_name_value VARCHAR(128);
    DECLARE tables_cursor CURSOR FOR
        SELECT TABLE_NAME FROM information_schema.TABLES
        WHERE TABLE_SCHEMA=DATABASE()
          AND (TABLE_NAME REGEXP '^t_ods_event_[0-9]{6}$'
               OR TABLE_NAME REGEXP '^t_event_object_match_[0-9]{6}$');
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done=1;
    OPEN tables_cursor;
    table_loop: LOOP
        FETCH tables_cursor INTO table_name_value;
        IF done=1 THEN LEAVE table_loop; END IF;
        SET @sql_text=CONCAT('DROP TABLE IF EXISTS `', table_name_value, '`');
        PREPARE statement_value FROM @sql_text;
        EXECUTE statement_value;
        DEALLOCATE PREPARE statement_value;
    END LOOP;
    CLOSE tables_cursor;
END$$
CALL drop_trade_id_month_tables()$$
DROP PROCEDURE drop_trade_id_month_tables$$
DELIMITER ;

DROP TABLE IF EXISTS t_event_object_match_template;
DROP TABLE IF EXISTS t_ods_event_template;

CREATE TABLE t_etl_sync_log (
    sync_log_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '中心写入链路使用的内部日志主键',
    sync_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT '每次窗口执行生成的全局唯一 UUID',
    task_no VARCHAR(64) NOT NULL COMMENT '外层任务编号，同一任务的所有窗口共用',
    operation VARCHAR(16) NOT NULL COMMENT '操作类型：LIVE、BACKFILL、REPAIR、CHECK',
    source_server_id BIGINT UNSIGNED NOT NULL COMMENT '门架源服务器主键',
    server_code VARCHAR(64) NOT NULL COMMENT '门架源服务器稳定编码',
    window_start DATETIME(3) NOT NULL COMMENT '窗口开始时间，左闭，Asia/Shanghai',
    window_end DATETIME(3) NOT NULL COMMENT '窗口结束时间，右开，Asia/Shanghai',
    source_table VARCHAR(128) NULL COMMENT '本次唯一读取的门架表名',
    status VARCHAR(16) NOT NULL COMMENT '执行状态：RUNNING、SUCCESS、FAILED、SKIPPED',
    check_status VARCHAR(16) NOT NULL DEFAULT 'UNCHECKED' COMMENT 'TradeId 完整性：UNCHECKED、COMPLETE、MISSING',
    source_unique_count BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '源端 TradeId 去重后数量',
    center_matched_count BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '中心库已存在的源端 TradeId 数量',
    missing_count BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '源端存在但中心库缺失的 TradeId 数量',
    duplicate_count BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '源窗口内重复 TradeId 行数',
    inserted_count BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '本次新增 ODS TradeId 数量',
    updated_count BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '本次已存在并执行幂等写入的 TradeId 数量',
    query_duration_ms BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '门架查询耗时毫秒',
    write_duration_ms BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '中心业务写入耗时毫秒',
    verify_duration_ms BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '中心 TradeId 校验耗时毫秒',
    total_duration_ms BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '窗口总耗时毫秒',
    missing_sample_json JSON NULL COMMENT '最多二十个缺失 TradeId 样例',
    error_type VARCHAR(128) NULL COMMENT '异常类型，不含凭据',
    error_message VARCHAR(2000) NULL COMMENT '异常摘要，不含凭据',
    started_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '开始时间',
    finished_at DATETIME(3) NULL COMMENT '结束时间',
    PRIMARY KEY (sync_log_id),
    UNIQUE KEY uk_etl_sync_id (sync_id),
    KEY idx_etl_sync_window (server_code,window_start,window_end,sync_log_id),
    KEY idx_etl_sync_missing (check_status,status,window_start),
    KEY idx_etl_sync_task (task_no,sync_log_id),
    CONSTRAINT ck_etl_sync_operation CHECK (operation IN ('LIVE','BACKFILL','REPAIR','CHECK')),
    CONSTRAINT ck_etl_sync_status CHECK (status IN ('RUNNING','SUCCESS','FAILED','SKIPPED')),
    CONSTRAINT ck_etl_sync_check CHECK (check_status IN ('UNCHECKED','COMPLETE','MISSING')),
    CONSTRAINT ck_etl_sync_window CHECK (window_end > window_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='单服务器单窗口 ETL 唯一执行日志';

CREATE TABLE t_etl_manual_job (
    job_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'HTTP 后台任务主键',
    task_no VARCHAR(64) NOT NULL COMMENT '关联同步日志的任务编号',
    operation VARCHAR(16) NOT NULL COMMENT '任务类型：LIVE、BACKFILL、CHECK、REPAIR',
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING' COMMENT '任务状态：PENDING、RUNNING、SUCCESS、PARTIAL、FAILED',
    window_start DATETIME(3) NOT NULL COMMENT '任务范围开始时间，左闭',
    window_end DATETIME(3) NOT NULL COMMENT '任务范围结束时间，右开',
    server_code VARCHAR(64) NULL COMMENT '指定服务器编码；空值表示全部可达服务器',
    force_enabled TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否忽略既有 COMPLETE 结果重新执行',
    window_minutes INT UNSIGNED NOT NULL DEFAULT 120 COMMENT '单个窗口分钟数，默认两小时',
    sleep_seconds INT UNSIGNED NOT NULL DEFAULT 5 COMMENT '服务器窗口之间休眠秒数',
    stop_on_error TINYINT(1) NOT NULL DEFAULT 0 COMMENT '失败后是否停止任务',
    source_mode VARCHAR(16) NOT NULL DEFAULT 'auto' COMMENT '源表选择：auto、realtime、history',
    total_windows INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '服务器窗口总数',
    processed_windows INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '已处理服务器窗口数',
    complete_windows INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '完整或跳过窗口数',
    missing_windows INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '存在 TradeId 缺失窗口数',
    failed_windows INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '执行失败窗口数',
    result_json JSON NULL COMMENT '最终任务摘要',
    error_message VARCHAR(2000) NULL COMMENT '任务错误摘要，不含凭据',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    started_at DATETIME(3) NULL COMMENT '单 worker 开始消费时间',
    finished_at DATETIME(3) NULL COMMENT '任务完成时间',
    PRIMARY KEY (job_id),
    UNIQUE KEY uk_etl_job_task_no (task_no),
    KEY idx_etl_job_status (status,job_id),
    CONSTRAINT ck_etl_job_operation CHECK (operation IN ('LIVE','BACKFILL','CHECK','REPAIR')),
    CONSTRAINT ck_etl_job_status CHECK (status IN ('PENDING','RUNNING','SUCCESS','PARTIAL','FAILED')),
    CONSTRAINT ck_etl_job_source_mode CHECK (source_mode IN ('auto','realtime','history')),
    CONSTRAINT ck_etl_job_window CHECK (window_end > window_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='单 worker 串行消费的 ETL 后台任务';

CREATE TABLE t_ods_event_template (
    trade_id VARCHAR(38) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT '门架原始 TradeId，全渠道唯一交易标识',
    source_server_id BIGINT UNSIGNED NOT NULL COMMENT '门架源服务器主键，仅用于来源追踪',
    source_table_name VARCHAR(128) NOT NULL COMMENT '门架源表名，仅用于来源追踪',
    event_time DATETIME(3) NOT NULL COMMENT '交易发生时间，来自门架 TransTime',
    entry_time DATETIME(3) NULL COMMENT '入口时间，来自门架 EnTime',
    vehicle_plate_no VARCHAR(32) NULL COMMENT '车牌号码，已去除颜色后缀',
    current_physical_gantry_code VARCHAR(32) NOT NULL COMMENT '当前物理门架编码，来自 GantryId',
    current_gantry_hex VARCHAR(32) NOT NULL COMMENT '当前逻辑门架十六进制编码',
    previous_gantry_hex VARCHAR(32) NULL COMMENT '上游逻辑门架十六进制编码',
    previous_gantry_source VARCHAR(32) NULL COMMENT '上游门架字段来源',
    raw_previous_gantry_json JSON NULL COMMENT '上游门架原始候选字段',
    vehicle_type_code VARCHAR(16) NULL COMMENT '车型编码',
    entry_station_code VARCHAR(32) NULL COMMENT '入口收费站编码',
    media_type VARCHAR(16) NULL COMMENT '交易介质类型',
    trade_result VARCHAR(16) NULL COMMENT '交易结果',
    obu_trade_result VARCHAR(16) NULL COMMENT 'OBU 交易结果',
    success_flag TINYINT(1) NOT NULL COMMENT '是否按当前成功策略判定为成功交易',
    success_rule_code VARCHAR(64) NOT NULL COMMENT '成功策略命中规则编码',
    batch_id BIGINT UNSIGNED NOT NULL COMMENT '写入该行的 ETL 日志主键',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
    PRIMARY KEY (trade_id),
    UNIQUE KEY uk_ods_trade_id (trade_id),
    KEY idx_ods_event_time (event_time),
    KEY idx_ods_source (source_server_id,source_table_name,event_time),
    KEY idx_ods_current_gantry (current_gantry_hex,event_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='中心 ODS 交易事件模板表';

CREATE TABLE t_event_object_match_template (
    match_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '命中记录主键',
    trade_id VARCHAR(38) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT '门架原始 TradeId，关联 ODS 交易事件',
    event_time DATETIME(3) NOT NULL COMMENT '交易发生时间',
    source_server_id BIGINT UNSIGNED NOT NULL COMMENT '门架源服务器主键',
    object_no BIGINT UNSIGNED NOT NULL COMMENT '统计对象编号',
    rule_no BIGINT UNSIGNED NOT NULL COMMENT '命中的规则编号',
    previous_gantry_hex VARCHAR(32) NULL COMMENT '上游逻辑门架十六进制编码',
    current_gantry_hex VARCHAR(32) NOT NULL COMMENT '当前逻辑门架十六进制编码',
    entry_station_code VARCHAR(32) NULL COMMENT '入口收费站编码',
    vehicle_type_code VARCHAR(16) NULL COMMENT '车型编码',
    vehicle_category_code VARCHAR(16) NOT NULL COMMENT '车型分类编码',
    batch_id BIGINT UNSIGNED NOT NULL COMMENT '写入该行的 ETL 日志主键',
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
    PRIMARY KEY (match_id),
    UNIQUE KEY uk_event_object_match (trade_id,object_no),
    KEY idx_match_event_time (event_time),
    KEY idx_match_object_time (object_no,event_time),
    KEY idx_match_trade_id (trade_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='交易事件统计对象命中模板表';

DELIMITER $$
CREATE PROCEDURE sp_create_event_month_tables(IN p_month CHAR(6))
BEGIN
    IF p_month NOT REGEXP '^[0-9]{6}$' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='月份参数必须为 yyyyMM';
    END IF;
    SET @ods_table=CONCAT('t_ods_event_', p_month);
    SET @match_table=CONCAT('t_event_object_match_', p_month);
    SET @sql_text=CONCAT('CREATE TABLE IF NOT EXISTS `', @ods_table, '` LIKE t_ods_event_template');
    PREPARE statement_value FROM @sql_text; EXECUTE statement_value; DEALLOCATE PREPARE statement_value;
    SET @sql_text=CONCAT('CREATE TABLE IF NOT EXISTS `', @match_table, '` LIKE t_event_object_match_template');
    PREPARE statement_value FROM @sql_text; EXECUTE statement_value; DEALLOCATE PREPARE statement_value;
END$$
DELIMITER ;

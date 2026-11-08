-- CT-01 audit metadata migration. Run once with the target database selected.
-- All new fields are nullable. This migration adds columns/indexes only and
-- does not rewrite or remove consultas_tributos records or existing indexes.
-- Keep any deployed idx_consultas_criado(criado_em, id) index.
-- Never persist credentials/tokens or a full raw IBPT response in these fields.

ALTER TABLE consultas_tributos
    ADD COLUMN comparison_id CHAR(36) NULL,
    ADD COLUMN unidade_medida VARCHAR(20) NULL,
    ADD COLUMN gtin VARCHAR(20) NULL,
    ADD COLUMN ex INT NULL,
    ADD COLUMN cenario VARCHAR(10) NULL,
    ADD COLUMN provedor VARCHAR(30) NULL,
    ADD COLUMN versao_fonte VARCHAR(100) NULL,
    ADD COLUMN vigencia_inicio DATE NULL,
    ADD COLUMN vigencia_fim DATE NULL,
    ADD COLUMN obtido_em_utc DATETIME(6) NULL,
    ADD COLUMN percentual_total DECIMAL(10, 4) NULL,
    ADD COLUMN valor_federal DECIMAL(15, 2) NULL,
    ADD COLUMN valor_estadual DECIMAL(15, 2) NULL,
    ADD COLUMN valor_municipal DECIMAL(15, 2) NULL,
    ADD COLUMN total_estimado DECIMAL(15, 2) NULL,
    ADD COLUMN algoritmo_versao VARCHAR(30) NULL,
    ADD COLUMN politica_arredondamento VARCHAR(50) NULL,
    ADD COLUMN status_consulta VARCHAR(20) NULL,
    ADD COLUMN erro_consulta TEXT NULL;

-- Add comparison/history support only when the exact composite indexes are absent.
-- Existing criado_em-only indexes are intentionally left untouched.
SET @ct01_has_comparison_index = (
    SELECT COUNT(*)
    FROM (
        SELECT INDEX_NAME
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'consultas_tributos'
        GROUP BY INDEX_NAME
        HAVING GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) = 'comparison_id,criado_em,id'
    ) AS matching_indexes
);
SET @ct01_comparison_index_ddl = IF(
    @ct01_has_comparison_index = 0,
    'ALTER TABLE consultas_tributos ADD INDEX idx_consultas_comparison_criado (comparison_id, criado_em, id)',
    'SELECT ''Comparison index already exists; no index change required'''
);
PREPARE ct01_comparison_index_stmt FROM @ct01_comparison_index_ddl;
EXECUTE ct01_comparison_index_stmt;
DEALLOCATE PREPARE ct01_comparison_index_stmt;

-- Add the NCM/UF/history index when absent. Existing codigo_ncm/uf indexes,
-- including legacy names, are preserved; this index also supports NCM/UF lookups.
SET @ct01_has_history_index = (
    SELECT COUNT(*)
    FROM (
        SELECT INDEX_NAME
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'consultas_tributos'
        GROUP BY INDEX_NAME
        HAVING GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) = 'codigo_ncm,uf,criado_em'
    ) AS matching_indexes
);
SET @ct01_history_index_ddl = IF(
    @ct01_has_history_index = 0,
    'ALTER TABLE consultas_tributos ADD INDEX idx_consultas_codigo_uf_criado (codigo_ncm, uf, criado_em)',
    'SELECT ''NCM/UF/history index already exists; no index change required'''
);
PREPARE ct01_history_index_stmt FROM @ct01_history_index_ddl;
EXECUTE ct01_history_index_stmt;
DEALLOCATE PREPARE ct01_history_index_stmt;

-- DATETIME(6) values in obtido_em_utc are recorded as UTC by the application.

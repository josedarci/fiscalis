CREATE DATABASE IF NOT EXISTS db_tributos_app
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE db_tributos_app;

CREATE TABLE IF NOT EXISTS consultas_tributos (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    cnpj_empresa VARCHAR(20) NOT NULL,
    uf CHAR(2) NOT NULL,
    codigo_ncm VARCHAR(20) NOT NULL,
    descricao_produto VARCHAR(255) NOT NULL,
    valor_unitario DECIMAL(15, 4) NOT NULL,
    aliquota_nacional DECIMAL(10, 4) NULL,
    aliquota_estadual DECIMAL(10, 4) NULL,
    aliquota_municipal DECIMAL(10, 4) NULL,
    aliquota_importado DECIMAL(10, 4) NULL,
    fonte_informacao VARCHAR(255) NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    comparison_id CHAR(36) NULL,
    unidade_medida VARCHAR(20) NULL,
    gtin VARCHAR(20) NULL,
    ex INT NULL,
    cenario VARCHAR(10) NULL,
    provedor VARCHAR(30) NULL,
    versao_fonte VARCHAR(100) NULL,
    vigencia_inicio DATE NULL,
    vigencia_fim DATE NULL,
    obtido_em_utc DATETIME(6) NULL,
    percentual_total DECIMAL(10, 4) NULL,
    valor_federal DECIMAL(15, 2) NULL,
    valor_estadual DECIMAL(15, 2) NULL,
    valor_municipal DECIMAL(15, 2) NULL,
    total_estimado DECIMAL(15, 2) NULL,
    algoritmo_versao VARCHAR(30) NULL,
    politica_arredondamento VARCHAR(50) NULL,
    status_consulta VARCHAR(20) NULL,
    erro_consulta TEXT NULL,
    PRIMARY KEY (id),
    INDEX idx_consultas_tributos_criado (criado_em, id),
    INDEX idx_consultas_tributos_codigo_uf (codigo_ncm, uf),
    INDEX idx_consultas_codigo_uf_criado (codigo_ncm, uf, criado_em),
    INDEX idx_consultas_comparison_criado (comparison_id, criado_em, id)
) ENGINE=InnoDB
  DEFAULT CHARACTER SET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

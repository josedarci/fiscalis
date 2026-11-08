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
    PRIMARY KEY (id),
    INDEX idx_consultas_tributos_criado (criado_em, id),
    INDEX idx_consultas_tributos_codigo_uf (codigo_ncm, uf)
) ENGINE=InnoDB
  DEFAULT CHARACTER SET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema.sql"
MIGRATION_PATH = ROOT / "migrations" / "001_ct01_audit.sql"
ROLLBACK_PATH = ROOT / "migrations" / "001_ct01_audit_rollback.md"

AUDIT_COLUMNS = (
    "comparison_id",
    "unidade_medida",
    "gtin",
    "ex",
    "cenario",
    "provedor",
    "versao_fonte",
    "vigencia_inicio",
    "vigencia_fim",
    "obtido_em_utc",
    "percentual_total",
    "valor_federal",
    "valor_estadual",
    "valor_municipal",
    "total_estimado",
    "algoritmo_versao",
    "politica_arredondamento",
    "status_consulta",
    "erro_consulta",
)

AUDIT_COLUMN_TYPES = {
    "comparison_id": r"CHAR\(36\)",
    "unidade_medida": r"VARCHAR\(20\)",
    "gtin": r"VARCHAR\(20\)",
    "ex": r"INT",
    "cenario": r"VARCHAR\(10\)",
    "provedor": r"VARCHAR\(30\)",
    "versao_fonte": r"VARCHAR\(100\)",
    "vigencia_inicio": r"DATE",
    "vigencia_fim": r"DATE",
    "obtido_em_utc": r"DATETIME\(6\)",
    "percentual_total": r"DECIMAL\(10,\s*4\)",
    "valor_federal": r"DECIMAL\(15,\s*2\)",
    "valor_estadual": r"DECIMAL\(15,\s*2\)",
    "valor_municipal": r"DECIMAL\(15,\s*2\)",
    "total_estimado": r"DECIMAL\(15,\s*2\)",
    "algoritmo_versao": r"VARCHAR\(30\)",
    "politica_arredondamento": r"VARCHAR\(50\)",
    "status_consulta": r"VARCHAR\(20\)",
    "erro_consulta": r"TEXT",
}


def remove_sql_comments(sql):
    return re.sub(r"--[^\n]*|/\*.*?\*/", "", sql, flags=re.DOTALL)


class Ct01MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = SCHEMA_PATH.read_text(encoding="utf-8")
        cls.migration = MIGRATION_PATH.read_text(encoding="utf-8")
        cls.rollback = ROLLBACK_PATH.read_text(encoding="utf-8")

    def test_fresh_schema_has_nullable_audit_fields(self):
        table_definition = self.schema.split("CREATE TABLE IF NOT EXISTS consultas_tributos", 1)[1]
        for column in AUDIT_COLUMNS:
            with self.subTest(column=column):
                self.assertRegex(
                    table_definition,
                    rf"\b{column}\b\s+{AUDIT_COLUMN_TYPES[column]}\s+NULL\b",
                )
        self.assertIn("INDEX idx_consultas_codigo_uf_criado (codigo_ncm, uf, criado_em)", table_definition)
        self.assertIn("INDEX idx_consultas_comparison_criado (comparison_id, criado_em, id)", table_definition)
        self.assertIn("DATETIME(6) values in obtido_em_utc are recorded as UTC", self.migration)

    def test_migration_adds_all_audit_fields_without_data_rewrites(self):
        executable_sql = remove_sql_comments(self.migration)
        statement = re.search(
            r"ALTER\s+TABLE\s+consultas_tributos(.*?);",
            executable_sql,
            re.I | re.S,
        )
        self.assertIsNotNone(statement)
        alter_statement = statement.group(1)
        for column in AUDIT_COLUMNS:
            with self.subTest(column=column):
                self.assertRegex(
                    alter_statement,
                    rf"\bADD\s+COLUMN\s+{column}\s+{AUDIT_COLUMN_TYPES[column]}\s+NULL\b",
                )

        forbidden = re.compile(r"\b(?:DROP|UPDATE|DELETE|TRUNCATE|RENAME)\b", re.I)
        self.assertIsNone(forbidden.search(executable_sql))

    def test_indexes_are_additive_and_history_index_is_preserved(self):
        executable_sql = remove_sql_comments(self.migration)
        self.assertIn("idx_consultas_criado(criado_em, id)", self.migration)
        self.assertIn("comparison_id,criado_em,id", executable_sql)
        self.assertIn("codigo_ncm,uf,criado_em", executable_sql)
        self.assertIn("idx_consultas_comparison_criado (comparison_id, criado_em, id)", executable_sql)
        self.assertIn("idx_consultas_codigo_uf_criado (codigo_ncm, uf, criado_em)", executable_sql)
        self.assertNotRegex(
            executable_sql,
            r"\b(?:DROP|RENAME)\s+INDEX\b|\bidx_consultas_criado\b",
        )

    def test_sensitive_payloads_are_explicitly_excluded(self):
        self.assertIn("never persist credentials/tokens or a full raw ibpt response", self.migration.lower())
        normalized_rollback = " ".join(self.rollback.lower().split())
        self.assertIn("leave the additive database schema in place", normalized_rollback)
        self.assertIn("No destructive rollback SQL", self.rollback)


if __name__ == "__main__":
    unittest.main()

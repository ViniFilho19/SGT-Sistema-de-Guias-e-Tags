"""Migrações simples e idempotentes: adiciona colunas novas a bancos já existentes (create_all não altera tabelas)."""
from sqlalchemy import inspect, text

# tabela -> [(coluna, tipo SQL)]
COLUNAS = {
    "guias": [
        ("status", "VARCHAR(20)"),
        ("entregue_por", "VARCHAR(200)"),
        ("retirado_por", "VARCHAR(200)"),
        ("entregue_em", "TIMESTAMP"),
        ("entrega_operador_id", "INTEGER REFERENCES users(id)"),
    ],
}


def migrar(engine) -> None:
    existentes = {t: {c["name"] for c in inspect(engine).get_columns(t)} for t in COLUNAS}
    with engine.begin() as con:
        for tabela, cols in COLUNAS.items():
            for nome, tipo in cols:
                if nome not in existentes[tabela]:
                    con.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}"))
        # guias de saída antigas passam a constar como "pronta"
        con.execute(text("UPDATE guias SET status = 'pronta' WHERE tipo = 'GUIA DE SAÍDA' AND status IS NULL"))
        con.execute(text("CREATE INDEX IF NOT EXISTS ix_guias_status ON guias (status)"))

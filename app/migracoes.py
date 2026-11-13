"""Migrações simples e idempotentes: adiciona colunas novas a bancos já existentes (create_all não altera tabelas)."""
from sqlalchemy import inspect, text

# tabela -> [(coluna, tipo SQL)]
COLUNAS = {
    "etiquetas": [
        ("operador_original", "VARCHAR(100)"),
        ("hostname", "VARCHAR(100)"), ("ip", "VARCHAR(45)"), ("patrimonio", "VARCHAR(100)"), ("serial", "VARCHAR(100)"),
        ("localidade", "VARCHAR(200)"), ("mascara", "VARCHAR(45)"), ("gateway", "VARCHAR(45)"),
    ],
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
        # etiquetas antigas sem "foto": copia os dados atuais do equipamento (melhor informação disponível)
        cols = ("hostname", "ip", "patrimonio", "serial", "localidade", "mascara", "gateway")
        sets = ", ".join(f"{c} = (SELECT e.{c} FROM equipamentos e WHERE e.id = etiquetas.equipamento_id)" for c in cols)
        con.execute(text(f"UPDATE etiquetas SET {sets} WHERE " + " AND ".join(f"{c} IS NULL" for c in cols)))

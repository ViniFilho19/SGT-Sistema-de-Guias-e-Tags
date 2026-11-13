"""Importa histórico de etiquetas de uma planilha CSV (exportada do sistema antigo).

Uso:
    python importar_etiquetas.py planilha.csv            -> SIMULAÇÃO: mostra o que seria feito, não grava nada
    python importar_etiquetas.py planilha.csv --aplicar  -> grava no banco (faz backup antes)

Colunas esperadas: Data/Hora, Operador, Hostname, IP, Patrimônio, Nº Série, Localidade, Máscara, Gateway

Regras:
- Equipamento identificado pelo patrimônio (ou, sem patrimônio, pelo nº de série); linhas em ordem cronológica,
  a mais recente define os dados atuais. Valores vazios ou inválidos não apagam um dado bom já conhecido.
- Cada linha vira uma etiqueta no histórico, com a data original, ligada ao usuário inativo "importacao";
  o nome do operador da planilha fica em etiquetas.operador_original.
- Etiquetas importadas ficam fora da lista de "recentes" (oculta), mas contam nos relatórios.
- Pode rodar de novo: etiquetas já importadas (mesmo equipamento + mesma data/hora) são ignoradas.
"""
import csv
import ipaddress
import re
import secrets
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.migracoes import migrar
from app.models import Equipamento, Etiqueta, User
from app.security import hash_senha

FUSO = ZoneInfo("America/Bahia")
USUARIO_IMPORT = "importacao"
# correções de digitação evidentes na localidade (após maiúsculas)
LOCALIDADES = {
    "CIRETRAN BUMADO": "CIRETRAN BRUMADO",
    "IRETRAN ILHEUS": "CIRETRAN ILHEUS",
    "CIRETRAN DE TEIXEIRA DE FREITAS": "CIRETRAN TEIXEIRA DE FREITAS",
}
CAMPOS = ("hostname", "ip", "patrimonio", "serial", "localidade", "mascara", "gateway")


def limpo(v: str | None) -> str | None:
    v = re.sub(r"\s+", " ", (v or "")).strip()
    if not v or re.fullmatch(r"X+", v, re.I) or v.lower() == "não informado":
        return None
    return v


def ip_ok(v: str | None) -> bool:
    try:
        ipaddress.ip_address(v)
        return True
    except ValueError:
        return False


def ler(caminho: Path, avisos: list[str]) -> list[dict]:
    linhas = []
    with caminho.open(encoding="utf-8-sig", newline="") as f:
        for n, r in enumerate(csv.DictReader(f), start=2):
            d = {
                "linha": n,
                "data": datetime.strptime(r["Data/Hora"].strip(), "%d/%m/%Y %H:%M:%S").replace(tzinfo=FUSO),
                "operador": limpo(r.get("Operador")),
                "hostname": limpo(r.get("Hostname")),
                "ip": limpo(r.get("IP")),
                "patrimonio": limpo(r.get("Patrimônio")),
                "serial": limpo(r.get("Nº Série")),
                "localidade": limpo(r.get("Localidade")),
                "mascara": limpo(r.get("Máscara")),
                "gateway": limpo(r.get("Gateway")),
            }
            if d["hostname"]:
                d["hostname"] = d["hostname"].upper()
            if d["localidade"]:
                orig = d["localidade"].upper()
                d["localidade"] = LOCALIDADES.get(orig, orig)
                if orig in LOCALIDADES:
                    avisos.append(f"linha {n}: localidade corrigida “{orig}” → “{d['localidade']}”")
            for c in ("ip", "mascara", "gateway"):
                if d[c] and not ip_ok(d[c]):
                    avisos.append(f"linha {n} ({d['hostname']}): {c} inválido “{d[c]}” ignorado")
                    d[c] = None
            linhas.append(d)
    return sorted(linhas, key=lambda d: d["data"])


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    aplicar = "--aplicar" in sys.argv
    if len(args) != 1:
        raise SystemExit(__doc__)
    avisos: list[str] = []
    linhas = ler(Path(args[0]), avisos)

    if aplicar and settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.removeprefix("sqlite:///"))
        if db_path.exists():
            bkp = db_path.with_name(f"{db_path.stem}.backup-{datetime.now():%Y%m%d-%H%M%S}{db_path.suffix}")
            shutil.copy2(db_path, bkp)
            print(f"Backup: {bkp}")

    Base.metadata.create_all(engine)
    migrar(engine)
    novos, atualizados, criadas, puladas = set(), set(), 0, 0
    with SessionLocal() as db:
        imp = db.scalar(select(User).where(User.username == USUARIO_IMPORT))
        if not imp:
            imp = User(username=USUARIO_IMPORT, nome="Importação (planilha)", papel="operador", ativo=False,
                       senha_hash=hash_senha(secrets.token_urlsafe(32)))
            db.add(imp)
            db.flush()

        for d in linhas:
            eq = None
            if d["patrimonio"]:
                eq = db.scalar(select(Equipamento).where(Equipamento.patrimonio == d["patrimonio"]))
            elif d["serial"]:
                eq = db.scalar(select(Equipamento).where(Equipamento.patrimonio.is_(None),
                                                         Equipamento.serial == d["serial"]))
            if eq is None:
                eq = Equipamento(tipo="Computador", criado_em=d["data"].astimezone(timezone.utc))
                db.add(eq)
                db.flush()
                novos.add(eq.id)
            else:
                if eq.hostname and d["hostname"] and eq.hostname != d["hostname"]:
                    avisos.append(f"linha {d['linha']}: patrimônio {d['patrimonio'] or '-'} trocou de hostname "
                                  f"{eq.hostname} → {d['hostname']} (fica o mais recente)")
                if eq.id not in novos:
                    atualizados.add(eq.id)
            for c in CAMPOS:
                if d[c]:
                    setattr(eq, c, d[c])
            eq.atualizado_em = d["data"].astimezone(timezone.utc)
            db.flush()

            quando = d["data"].astimezone(timezone.utc)
            existe = db.scalar(select(Etiqueta.id).where(Etiqueta.equipamento_id == eq.id,
                                                         Etiqueta.operador_id == imp.id, Etiqueta.criado_em == quando))
            if existe:
                puladas += 1
                continue
            db.add(Etiqueta(equipamento_id=eq.id, operador_id=imp.id, criado_em=quando, oculta=True,
                            operador_original=d["operador"] or "Não informado"))
            criadas += 1

        repetidas = Counter((d["hostname"], d["patrimonio"]) for d in linhas)
        print(f"\nLinhas lidas: {len(linhas)}")
        print(f"Equipamentos novos: {len(novos)}   atualizados (já existiam): {len(atualizados)}")
        print(f"Etiquetas a registrar: {criadas}   já importadas antes (ignoradas): {puladas}")
        rep = [f"{h} ({n}x)" for (h, _), n in repetidas.items() if n > 1]
        if rep:
            print("Etiquetas repetidas (reimpressões, todas mantidas no histórico): " + ", ".join(rep))
        if avisos:
            print("\nAvisos:")
            for a in avisos:
                print("  - " + a)
        if aplicar:
            db.commit()
            print("\nImportação GRAVADA no banco.")
        else:
            db.rollback()
            print("\nSIMULAÇÃO: nada foi gravado. Rode de novo com --aplicar para importar.")


if __name__ == "__main__":
    main()

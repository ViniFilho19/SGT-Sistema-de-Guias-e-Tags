"""Importa histórico de guias de uma planilha CSV (exportada do sistema antigo).

Uso:
    python importar_guias.py planilha.csv            -> SIMULAÇÃO (não grava)
    python importar_guias.py planilha.csv --aplicar  -> grava no banco (faz backup antes)

Colunas: Data/Hora, Operador, ID Guia, Tipo da Guia, Chamado, Remetente, Destinatário, Responsável CTI,
         Tipo Equipamento, Modelo/Marca, Patrimônio, Nº Série, Hostname, IP

Regras:
- Cada "ID Guia" vira uma guia (com todos os seus itens), na data original; o ID antigo fica em guias.codigo_original
  e o operador da planilha em guias.operador_original (dono no sistema: usuário inativo "importacao").
- Guias de saída antigas entram como "entregue" (sem nomes), para não poluir a aba "Prontas p/ entrega".
- Itens são ligados ao cadastro de equipamentos pelo patrimônio (ignorando zeros à esquerda); o cadastro não é alterado.
- Pode rodar de novo: guias com o mesmo ID antigo são ignoradas.
"""
import csv
import ipaddress
import re
import secrets
import shutil
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.migracoes import migrar
from app.models import Equipamento, Guia, GuiaItem, User
from app.security import hash_senha

FUSO = ZoneInfo("America/Bahia")
USUARIO_IMPORT = "importacao"
VAZIOS = {"SEM INF", "SEM IN", "S/N", "N/A", "NÃO INFORMADO"}
TIPOS = {t.upper(): t for t in ["Computador", "Monitor", "Teclado", "Mouse", "Switch", "Estabilizador",
                                "Notebook", "Projetor", "Webcam"]}
# grafias diferentes do mesmo lugar (comparação em maiúsculas, sem espaços extras)
LUGARES = {
    "CIRETRAN ARMARGOSA": "CIRETRAN AMARGOSA",
    "RETRAN RIBEIRA DE POMBAL": "RETRAN RIBEIRA DO POMBAL",
    "RETRAN - ITAPARICA": "RETRAN ITAPARICA",
    "ITAPARICA": "RETRAN ITAPARICA",
    "RETRAN - RUY BARBOSA": "RETRAN RUY BARBOSA",
    "RETRAN RUI BARBOSA": "RETRAN RUY BARBOSA",
    "CIRETRAN - ILHEUS": "CIRETRAN ILHEUS",
    "UNIDADE/CIRETRAN DE DIAS D'ÁVILA.": "RETRAN DIAS D'ÁVILA",
    "DIAS DAVILA": "RETRAN DIAS D'ÁVILA",
    "RETRAN DIAS DÁVILA": "RETRAN DIAS D'ÁVILA",
    "CIRETRAN RIACHAO DE JACUIPE": "CIRETRAN RIACHÃO DE JACUIPE",
    "CCI - CONTROLE INTERNO": "CONTROLE INTERNO",
}


def limpo(v):
    v = re.sub(r"\s+", " ", (v or "")).strip()
    if not v or re.fullmatch(r"X+", v, re.I) or v.upper() in VAZIOS:
        return None
    return v


def lugar(v):
    v = limpo(v)
    if not v:
        return "NÃO INFORMADO"
    v = v.upper()
    return LUGARES.get(v, v)


def eh_ip(v):
    try:
        ipaddress.ip_address(v)
        return True
    except (ValueError, TypeError):
        return False


def ler(caminho: Path, avisos: list[str]) -> "OrderedDict[str, dict]":
    guias: "OrderedDict[str, dict]" = OrderedDict()
    with caminho.open(encoding="utf-8-sig", newline="") as f:
        for n, r in enumerate(csv.DictReader(f), start=2):
            cod = r["ID Guia"].strip()
            g = guias.get(cod)
            if g is None:
                chamado = limpo(r["Chamado"])
                g = guias[cod] = {
                    "data": datetime.strptime(r["Data/Hora"].strip(), "%d/%m/%Y %H:%M:%S").replace(tzinfo=FUSO),
                    "operador": limpo(r["Operador"]) or "Não informado",
                    "tipo": r["Tipo da Guia"].strip().upper(),
                    "chamado": chamado.strip("-/ ") if chamado else None,
                    "remetente": lugar(r["Remetente"]),
                    "destinatario": lugar(r["Destinatário"]),
                    "responsavel": limpo(r["Responsável CTI"]),
                    "itens": [],
                }
                if g["tipo"] not in ("GUIA DE ENTRADA", "GUIA DE SAÍDA"):
                    raise SystemExit(f"linha {n}: tipo de guia desconhecido {g['tipo']!r}")
            tipo = limpo(r["Tipo Equipamento"]) or "Computador"
            item = {
                "tipo_equipamento": TIPOS.get(tipo.upper(), tipo),
                "modelo": limpo(r["Modelo/Marca"]),
                "patrimonio": limpo(r["Patrimônio"]),
                "serial": limpo(r["Nº Série"]),
                "hostname": limpo(r["Hostname"]),
                "ip": limpo(r["IP"]),
            }
            if item["serial"] and eh_ip(item["serial"]) and not eh_ip(item["ip"]):  # colunas trocadas na digitação
                item["serial"], item["ip"] = item["ip"], item["serial"]
                avisos.append(f"linha {n} ({cod}): série e IP estavam trocados, corrigido")
            if item["hostname"]:
                item["hostname"] = item["hostname"].upper()
            g["itens"].append(item)
    return guias


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    aplicar = "--aplicar" in sys.argv
    if len(args) != 1:
        raise SystemExit(__doc__)
    avisos: list[str] = []
    guias = ler(Path(args[0]), avisos)

    if aplicar and settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.removeprefix("sqlite:///"))
        if db_path.exists():
            bkp = db_path.with_name(f"{db_path.stem}.backup-{datetime.now():%Y%m%d-%H%M%S}{db_path.suffix}")
            shutil.copy2(db_path, bkp)
            print(f"Backup: {bkp}")

    Base.metadata.create_all(engine)
    migrar(engine)
    criadas = puladas = itens_total = ligados = 0
    with SessionLocal() as db:
        imp = db.scalar(select(User).where(User.username == USUARIO_IMPORT))
        if not imp:
            imp = User(username=USUARIO_IMPORT, nome="Importação (planilha)", papel="operador", ativo=False,
                       senha_hash=hash_senha(secrets.token_urlsafe(32)))
            db.add(imp)
            db.flush()
        cadastro = {e.patrimonio.lstrip("0"): e.id for e in db.scalars(select(Equipamento)) if e.patrimonio}

        for cod, g in guias.items():
            if db.scalar(select(Guia.id).where(Guia.codigo_original == cod)):
                puladas += 1
                continue
            quando = g["data"].astimezone(timezone.utc)
            guia = Guia(tipo=g["tipo"], chamado=g["chamado"], remetente=g["remetente"], destinatario=g["destinatario"],
                        responsavel=g["responsavel"], operador_id=imp.id, criado_em=quando,
                        codigo_original=cod, operador_original=g["operador"],
                        status="entregue" if g["tipo"] == "GUIA DE SAÍDA" else None)
            for it in g["itens"]:
                eq_id = cadastro.get(it["patrimonio"].lstrip("0")) if it["patrimonio"] else None
                ligados += eq_id is not None
                guia.itens.append(GuiaItem(**it, equipamento_id=eq_id))
                itens_total += 1
            db.add(guia)
            criadas += 1

        print(f"\nGuias na planilha: {len(guias)}   novas: {criadas}   já importadas (ignoradas): {puladas}")
        print(f"Itens: {itens_total}   ligados a equipamentos do cadastro: {ligados}")
        lugares = sorted({g["remetente"] for g in guias.values()} | {g["destinatario"] for g in guias.values()})
        print("Lugares: " + " | ".join(lugares))
        if avisos:
            print("\nAvisos:\n  - " + "\n  - ".join(avisos))
        if aplicar:
            db.commit()
            print("\nImportação GRAVADA no banco.")
        else:
            db.rollback()
            print("\nSIMULAÇÃO: nada foi gravado. Rode de novo com --aplicar para importar.")


if __name__ == "__main__":
    main()

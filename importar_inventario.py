"""Importa o inventário de máquinas (CSV do agente de inventário ou do consolidado Forescout) para o cadastro.

Uso:
    python importar_inventario.py inventario.csv                     -> SIMULAÇÃO (não grava nada)
    python importar_inventario.py inventario.csv --aplicar           -> grava no banco (faz backup antes)
    python importar_inventario.py inventario.csv --desde 2025-01-01  -> ignora máquinas vistas pela última vez antes da data

Usa SÓ as colunas hostname, ip, patrimonio, serial, localidade, mascara, gateway e modelo (+ ultimo_inventario,
quando existir, para saber qual linha é a mais recente). As demais (MAC, status de rede, origem, SO, usuário
conectado...) são ignoradas.

Formatos aceitos (detectados pelo cabeçalho):
- CSV do agente: separado por vírgula, UTF-8, colunas hostname, ip, ..., manufacturer, model, ultimo_inventario.
- Consolidado Forescout: separado por ";", Latin-1/UTF-8, colunas "Hostname", "IP", "Máscara de Sub-rede",
  "Gateway", "Modelo", "Serial Number", "Patrimônio", "Localidade / Segmento" (sem data: vale a ordem do arquivo).

Regras:
- Uma máquina é identificada pelo patrimônio; sem patrimônio, pelo nº de série; sem nenhum dos dois, pelo
  hostname (exceto hostnames genéricos como DESKTOP-XXXX, BACKUP, PROVA-ELETRONIC, que são ignorados).
- Patrimônios "039252" e "39252" são o mesmo (zeros à esquerda e pontos não contam na comparação).
- Linhas em ordem cronológica: a mais recente define os dados. Valor vazio/inválido não apaga dado bom.
- Equipamentos que já existiam no sistema mantêm a localidade que já tinham.
- Não cria etiquetas nem guias: só o cadastro de equipamentos. Pode rodar de novo sem duplicar.
- Servidores e máquinas virtuais (VMware, VirtualBox, Qemu, PowerEdge; localidade Datacenter/Servidores/
  Virtualização/VPN) são ignorados: o cadastro é só de máquinas físicas.
"""
import csv
import ipaddress
import re
import shutil
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.migracoes import migrar
from app.models import Equipamento

FUSO = ZoneInfo("America/Bahia")
CAMPOS = ("hostname", "ip", "patrimonio", "serial", "localidade", "mascara", "gateway", "modelo")
FABRICANTES = {  # nome curto do fabricante (minúsculas -> como mostrar)
    "positivo informatica sa": "Positivo", "positivo tecnologia sa": "Positivo", "positivo": "Positivo",
    "dell inc.": "Dell", "daten tecnologia ltda": "Daten", "daten tecnologia": "Daten",
    "hewlett-packard": "HP", "hp": "HP", "lenovo": "Lenovo", "itautec s.a.": "Itautec",
    "login informatica ltda": "Login", "login": "Login", "login2": "Login",
    "gigabyte technology co., ltd.": "Gigabyte", "micro-star international co., ltd.": "MSI",
    "micro-star international co.,ltd": "MSI", "msi": "MSI", "vmware, inc.": "VMware",
    "innotek gmbh": "VirtualBox", "microsoft corporation": "Microsoft", "intel corporation": "Intel", "intel": "Intel", "duex": "Duex", "goldentec": "Goldentec",
    "digitron": "Digitron", "pcware": "PCWare",
    "biostar group": "Biostar", "asus": "ASUS", "first international computer, inc.": "FIC",
    "semp toshiba informatica ltda": "Semp Toshiba",
}
LIXO_MODELO = re.compile(r"^(to be filled by o\.?e\.?m\.?|system (manufacturer|product name)|default string|oem"
                         r"|a_m_i|all series|pppppppp.*|windows7)$", re.I)


def modelo(fab: str | None, mod: str | None) -> str | None:
    """Fabricante + modelo do gabinete, sem os textos padrão de BIOS ('To be filled by O.E.M.' etc.)."""
    fab, mod = txt(fab), txt(mod)
    fab = None if not fab or LIXO_MODELO.match(fab) else FABRICANTES.get(fab.lower(), fab)
    mod = None if not mod or LIXO_MODELO.match(mod) else mod
    if fab and mod and mod.lower().startswith(fab.lower()):
        mod = mod[len(fab):]  # 'HP'/'HP EliteDesk ...', 'Positivo'/'POSITIVO MASTER D580'
    return nome_sem_codigo(" ".join(p for p in (fab, mod) if p)) or fab


def nome_sem_codigo(nome: str) -> str | None:
    """Só o nome, sem códigos: 'Positivo POS-PIQ77CL' -> 'Positivo'; 'HP EliteDesk 800 G4 SFF' -> 'HP EliteDesk'."""
    palavras = []
    for i, p in enumerate(nome.split()):
        if re.search(r"[\d\-#.]", p) or p.upper() in ("SFF", "MT", "VIRTUAL", "STANDARD"):
            break
        if i > 0 and p.isupper() and len(p) <= 4:
            continue  # siglas de código: 'ST', 'MSW', 'STI', 'DVID', 'ONE'
        p = p.capitalize() if p.isupper() and len(p) > 3 else p
        p = p[0].upper() + p[1:]
        if p.lower() not in (x.lower() for x in palavras):
            palavras.append(p)
    return " ".join(palavras) if palavras and len(palavras[0]) > 1 else None
GENERICOS = re.compile(r"^(DESKTOP(-\w+)?|BACKUP|BAKUP\d*|PROVA-ELETRONIC|USER-PC|USUARIO-PC|DETRAN|DETRAB|LENOVO"
                       r"|X+|TESTE\d*|ATENDIMENTO|DTRD|WIN-\w+)$", re.I)


# servidores e máquinas virtuais não entram no cadastro (só máquinas físicas de usuário)
NAO_MAQUINA_MODELO = re.compile(r"vmware|virtualbox|qemu|poweredge|hyper-v|virtual machine", re.I)
NAO_MAQUINA_LOCAL = re.compile(r"datacenter|servidores|virtualiza|vpn / remoto", re.I)


def nao_e_maquina(d: dict, bruto: dict) -> bool:
    textos = " ".join(x or "" for x in (d["modelo"], bruto.get("modelo_completo"), bruto.get("manufacturer"),
                                         bruto.get("model"), bruto.get("serial")))
    return bool(NAO_MAQUINA_MODELO.search(textos) or NAO_MAQUINA_LOCAL.search(d["localidade"] or ""))


def txt(v: str | None) -> str | None:
    v = re.sub(r"\s+", " ", (v or "")).strip()
    return v or None


def ip_util(v: str | None, permitir_zero=False) -> str | None:
    try:
        ip = ipaddress.ip_address(v or "")
    except ValueError:
        return None
    if ip.version != 4 or ip.is_unspecified or ip.is_loopback or ip.is_link_local:
        return None
    return str(ip)


def patrimonio(v: str | None) -> str | None:
    """'039015-SERI1AB88V46V' -> '039015'; 'omonio 00032679' -> '00032679'; '016.478' -> '016478'."""
    m = re.search(r"\d[\d. ]*\d|\d", v or "")
    if not m:
        return None
    p = re.sub(r"[. ]", "", m.group())
    return p if len(p.lstrip("0")) >= 3 else None


def chave_pat(p: str | None) -> str | None:
    return p.lstrip("0") if p else None


def serial(v: str | None) -> str | None:
    s = re.sub(r"[\s/]+", "", v or "").upper()
    if len(s) < 5 or not re.search(r"\d", s) or "PATRIMONIO" in s:
        return None  # 'Serie', 'SEM', 'TOMBO', 'O11', '45', 'porte-patrimonio035889'...
    return s


def chave_serial(s: str | None) -> str | None:
    return re.sub(r"[^0-9A-Z]", "", s.upper()) if s else None


def _norm(nome: str) -> str:
    """Cabeçalho comparável: sem acento, minúsculo ('Máscara de Sub-rede' -> 'mascara de sub-rede')."""
    nome = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", nome).strip().lower()


# coluna do arquivo (normalizada) -> campo do importador
COLUNAS = {
    "hostname": "hostname", "ip": "ip", "patrimonio": "patrimonio", "serial": "serial", "serial number": "serial",
    "localidade": "localidade", "localidade / segmento": "localidade", "mascara": "mascara",
    "mascara de sub-rede": "mascara", "gateway": "gateway", "manufacturer": "manufacturer", "model": "model",
    "modelo": "modelo_completo", "ultimo_inventario": "ultimo_inventario",
    "status rede (forescout)": "status", "origem do registro": "origem",  # só para escolher a melhor linha
}


def qualidade(r: dict, hostname: str | None) -> tuple:
    """Sem data no arquivo: entre linhas da mesma máquina vence a de hostname real, confirmada na rede e online."""
    origem, status = _norm(r.get("origem", "")), _norm(r.get("status", ""))
    return (0 if not hostname or GENERICOS.match(hostname) else 1,
            2 if origem.startswith("atualizado") else 1 if "forescout" in origem else 0,
            1 if status == "online" else 0)


def modelo_completo(v: str | None) -> str | None:
    """'Positivo Informatica SA POS-EIQ87CY' -> separa o fabricante conhecido do início e usa modelo()."""
    v = txt(v)
    if not v:
        return None
    for fab in sorted(FABRICANTES, key=len, reverse=True):
        if v.lower().startswith(fab + " ") or v.lower() == fab:
            return modelo(v[:len(fab)], v[len(fab):])
    return modelo(None, v)


def abrir(caminho: Path) -> str:
    dados = caminho.read_bytes()
    try:
        return dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        return dados.decode("cp1252")  # planilhas salvas pelo Excel em português


def ler(caminho: Path) -> tuple[list[dict], Counter]:
    linhas, descartes = [], Counter()
    texto = abrir(caminho).splitlines()
    sep = ";" if texto and texto[0].count(";") > texto[0].count(",") else ","
    leitor = csv.reader(texto, delimiter=sep)
    cab = [COLUNAS.get(_norm(c)) for c in next(leitor)]
    agora = datetime.now(FUSO)
    for n, vals in enumerate(leitor, start=2):
        r = {c: v for c, v in zip(cab, vals) if c}
        quando = txt(r.get("ultimo_inventario"))
        d = {
            "linha": n,
            "visto": datetime.strptime(quando, "%Y-%m-%d %H:%M:%S").replace(tzinfo=FUSO) if quando else agora,
            "hostname": (txt(r.get("hostname")) or "").upper() or None,
            "ip": ip_util(r.get("ip")),
            "patrimonio": patrimonio(r.get("patrimonio")),
            "serial": serial(r.get("serial")),
            "localidade": txt(r.get("localidade")),
            "mascara": ip_util(r.get("mascara")),
            "gateway": ip_util(r.get("gateway")),
            "modelo": modelo_completo(r["modelo_completo"]) if "modelo_completo" in r
                      else modelo(r.get("manufacturer"), r.get("model")),
        }
        for c in ("patrimonio", "serial", "ip"):
            if txt(r.get(c)) and not d[c]:
                descartes[c] += 1
        d["qualidade"] = qualidade(r, d["hostname"])
        if nao_e_maquina(d, r):
            descartes["servidor/máquina virtual (ignorada)"] += 1
            continue
        linhas.append(d)
    # ordem de aplicação: a linha mais recente (ou, sem data, a de melhor qualidade) é aplicada por último e vence
    return sorted(linhas, key=lambda d: (d["visto"], d["qualidade"])), descartes


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    aplicar = "--aplicar" in sys.argv
    desde = None
    if "--desde" in sys.argv:
        desde = datetime.strptime(sys.argv[sys.argv.index("--desde") + 1], "%Y-%m-%d").replace(tzinfo=FUSO)
        args = [a for a in args if a != sys.argv[sys.argv.index("--desde") + 1]]
    if len(args) != 1:
        raise SystemExit(__doc__)
    linhas, descartes = ler(Path(args[0]))

    if aplicar and settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.removeprefix("sqlite:///"))
        if db_path.exists():
            bkp = db_path.with_name(f"{db_path.stem}.backup-{datetime.now():%Y%m%d-%H%M%S}{db_path.suffix}")
            shutil.copy2(db_path, bkp)
            print(f"Backup: {bkp}")

    Base.metadata.create_all(engine)
    migrar(engine)
    with SessionLocal() as db:
        existentes = db.scalars(select(Equipamento)).all()
        antigos = {e.id for e in existentes}
        por_pat = {chave_pat(e.patrimonio): e for e in existentes if e.patrimonio}
        por_serial = {chave_serial(e.serial): e for e in existentes if e.serial}
        por_host = {e.hostname: e for e in existentes if e.hostname and not e.patrimonio and not e.serial}
        novos, atualizados, ignoradas, conflitos = [], set(), Counter(), []
        visto_por_eq: dict[int, datetime] = {}

        for d in linhas:
            kp, ks = chave_pat(d["patrimonio"]), chave_serial(d["serial"])
            if not kp and not ks and (not d["hostname"] or GENERICOS.match(d["hostname"])):
                ignoradas["sem patrimônio, série nem hostname identificável"] += 1
                continue
            eq = por_pat.get(kp) if kp else None
            if eq is None and ks:
                cand = por_serial.get(ks)
                if cand and kp and cand.patrimonio and chave_pat(cand.patrimonio) != kp:
                    conflitos.append(f"linha {d['linha']}: série {d['serial']} já é do patrimônio "
                                     f"{cand.patrimonio}; patrimônio {d['patrimonio']} cadastrado à parte")
                else:
                    eq = cand
            if eq is None and not kp and not ks:
                eq = por_host.get(d["hostname"])
            if eq is None:
                eq = Equipamento(tipo="Computador", criado_em=datetime.now(timezone.utc))
                db.add(eq)
                db.flush()
                novos.append(eq)
            elif eq.id in antigos:
                atualizados.add(eq.id)

            for c in CAMPOS:
                if not d[c]:
                    continue
                if c == "localidade" and eq.id in antigos and eq.localidade:
                    continue  # mantém a localidade padronizada que já existia
                if c == "patrimonio" and eq.patrimonio:
                    continue  # mantém o formato já cadastrado
                if c == "hostname" and eq.hostname and GENERICOS.match(d[c]) and not GENERICOS.match(eq.hostname):
                    continue  # 'XXXX', 'DESKTOP-...' não substituem um nome de verdade
                setattr(eq, c, d[c])
            eq.atualizado_em = d["visto"].astimezone(timezone.utc)
            visto_por_eq[eq.id] = d["visto"]
            if eq.patrimonio:
                por_pat[chave_pat(eq.patrimonio)] = eq
            if eq.serial:
                por_serial.setdefault(chave_serial(eq.serial), eq)
            if eq.hostname and not eq.patrimonio and not eq.serial:
                por_host[eq.hostname] = eq

        removidos_antigos = 0
        if desde:
            for eq in list(novos):
                if visto_por_eq[eq.id] < desde:
                    db.delete(eq)
                    novos.remove(eq)
                    removidos_antigos += 1
        db.flush()

        anos = Counter(visto_por_eq[e.id].year for e in novos)
        sem_local = sum(1 for e in novos if not e.localidade)
        print(f"\nLinhas lidas: {len(linhas)}")
        print(f"Equipamentos NOVOS: {len(novos)}   já existentes atualizados: {len(atualizados)}")
        print("Novos por ano em que foram vistos pela última vez: "
              + ", ".join(f"{a}: {n}" for a, n in sorted(anos.items())))
        if desde:
            print(f"Ignorados por terem sido vistos antes de {desde:%d/%m/%Y}: {removidos_antigos}")
        print(f"Novos sem localidade: {sem_local}")
        for motivo, n in ignoradas.items():
            print(f"Linhas ignoradas ({motivo}): {n}")
        print("Valores inválidos descartados (o resto da linha foi aproveitado): "
              + ", ".join(f"{c}: {n}" for c, n in descartes.items()))
        print(f"Localidades distintas nos novos: {len({e.localidade for e in novos if e.localidade})}")
        if conflitos:
            print(f"\nConflitos patrimônio x série ({len(conflitos)}), primeiros 15:")
            for c in conflitos[:15]:
                print("  - " + c)
        if aplicar:
            db.commit()
            print("\nImportação GRAVADA no banco.")
        else:
            db.rollback()
            print("\nSIMULAÇÃO: nada foi gravado. Rode de novo com --aplicar para importar.")


if __name__ == "__main__":
    main()

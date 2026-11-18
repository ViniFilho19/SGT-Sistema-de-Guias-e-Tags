import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Equipamento, Guia, GuiaItem, User
from ..schemas import GuiaCreate, GuiaOut, TipoGuia
from ..security import usuario_atual

router = APIRouter(prefix="/guias", tags=["guias"])


def equipamento_por_patrimonio(db: Session, patrimonio: Optional[str]) -> Optional[Equipamento]:
    """Acha o equipamento pelo patrimônio; '039252' e '39252' são considerados o mesmo."""
    p = (patrimonio or "").strip()[:100]
    if not p:
        return None
    eq = db.scalar(select(Equipamento).where(func.lower(Equipamento.patrimonio) == p.lower()))
    if eq or not p.lstrip("0"):
        return eq
    return db.scalars(select(Equipamento).where(func.ltrim(Equipamento.patrimonio, "0") == p.lstrip("0"))
                      .order_by(Equipamento.id)).first()


def equipamento_por_serial(db: Session, serial: Optional[str]) -> Optional[Equipamento]:
    """Acha o equipamento pelo nº de série, ignorando espaços, hífens, barras, pontos e maiúsculas."""
    ns = re.sub(r"[^0-9A-Z]", "", (serial or "").upper())[:100]
    if len(ns) < 3:
        return None
    col = Equipamento.serial
    for ch in (" ", "-", "/", "."):
        col = func.replace(col, ch, "")
    return db.scalars(select(Equipamento).where(func.upper(col) == ns).order_by(Equipamento.id)).first()


@router.post("", response_model=GuiaOut, status_code=201)
def criar(dados: GuiaCreate, db: Session = Depends(get_db), user: User = Depends(usuario_atual)):
    guia = Guia(**dados.model_dump(exclude={"itens"}), operador_id=user.id)
    if guia.tipo.startswith("GUIA DE SAÍDA"):  # saída comum ou desfazimento
        guia.status = "pronta"
    for item in dados.itens:
        # liga ao cadastro quando o patrimônio (ou, sem patrimônio, o nº de série/IMEI) já existe
        ser = item.serial or item.imei
        eq = equipamento_por_patrimonio(db, item.patrimonio) or (
            None if item.patrimonio else equipamento_por_serial(db, ser))
        guia.itens.append(GuiaItem(**item.model_dump(), equipamento_id=eq.id if eq else None))
    db.add(guia)
    db.commit()
    db.refresh(guia)
    return guia


@router.get("", response_model=list[GuiaOut])
def listar(tipo: Optional[TipoGuia] = None,
           chamado: Optional[str] = Query(None, max_length=100),
           skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
           db: Session = Depends(get_db), _: User = Depends(usuario_atual)):
    stmt = select(Guia).options(selectinload(Guia.itens)).order_by(Guia.id.desc())
    if tipo:
        stmt = stmt.where(Guia.tipo == tipo)
    if chamado:
        stmt = stmt.where(Guia.chamado == chamado)
    return db.scalars(stmt.offset(skip).limit(limit)).all()


@router.get("/{id_}", response_model=GuiaOut)
def obter(id_: int, db: Session = Depends(get_db), _: User = Depends(usuario_atual)):
    guia = db.get(Guia, id_)
    if not guia:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Guia não encontrada")
    return guia

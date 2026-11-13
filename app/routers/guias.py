from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Equipamento, Guia, GuiaItem, User
from ..schemas import GuiaCreate, GuiaOut
from ..security import usuario_atual

router = APIRouter(prefix="/guias", tags=["guias"])


@router.post("", response_model=GuiaOut, status_code=201)
def criar(dados: GuiaCreate, db: Session = Depends(get_db), user: User = Depends(usuario_atual)):
    guia = Guia(**dados.model_dump(exclude={"itens"}), operador_id=user.id)
    if guia.tipo.startswith("GUIA DE SAÍDA"):  # saída comum ou desfazimento
        guia.status = "pronta"
    for item in dados.itens:
        eq_id = None
        if item.patrimonio:  # liga ao cadastro quando o patrimônio já existe
            eq_id = db.scalar(select(Equipamento.id).where(Equipamento.patrimonio == item.patrimonio))
        guia.itens.append(GuiaItem(**item.model_dump(), equipamento_id=eq_id))
    db.add(guia)
    db.commit()
    db.refresh(guia)
    return guia


@router.get("", response_model=list[GuiaOut])
def listar(tipo: Optional[Literal["GUIA DE ENTRADA", "GUIA DE SAÍDA", "GUIA DE SAÍDA - DESFAZIMENTO"]] = None,
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

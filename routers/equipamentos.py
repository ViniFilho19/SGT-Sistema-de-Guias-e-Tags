from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Equipamento, User
from ..schemas import EquipamentoIn, EquipamentoOut
from ..security import somente_admin, usuario_atual

router = APIRouter(prefix="/equipamentos", tags=["equipamentos"], dependencies=[Depends(usuario_atual)])


def _busca(db: Session, id_: int) -> Equipamento:
    eq = db.get(Equipamento, id_)
    if not eq:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Equipamento não encontrado")
    return eq


@router.get("", response_model=list[EquipamentoOut])
def listar(q: Optional[str] = Query(None, max_length=100, description="busca em patrimônio, série, hostname, IP"),
           tipo: Optional[str] = None,
           skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
           db: Session = Depends(get_db)):
    stmt = select(Equipamento).order_by(Equipamento.id.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Equipamento.patrimonio.ilike(like), Equipamento.serial.ilike(like),
                              Equipamento.hostname.ilike(like), Equipamento.ip.ilike(like)))
    if tipo:
        stmt = stmt.where(Equipamento.tipo == tipo)
    return db.scalars(stmt.offset(skip).limit(limit)).all()


@router.get("/{id_}", response_model=EquipamentoOut)
def obter(id_: int, db: Session = Depends(get_db)):
    return _busca(db, id_)


@router.post("", response_model=EquipamentoOut, status_code=201)
def criar(dados: EquipamentoIn, db: Session = Depends(get_db)):
    eq = Equipamento(**dados.model_dump())
    db.add(eq)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Patrimônio já cadastrado")
    db.refresh(eq)
    return eq


@router.put("/{id_}", response_model=EquipamentoOut)
def atualizar(id_: int, dados: EquipamentoIn, db: Session = Depends(get_db)):
    eq = _busca(db, id_)
    for campo, valor in dados.model_dump().items():
        setattr(eq, campo, valor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Patrimônio já cadastrado")
    db.refresh(eq)
    return eq


@router.delete("/{id_}", status_code=204)
def excluir(id_: int, db: Session = Depends(get_db), _: User = Depends(somente_admin)):
    db.delete(_busca(db, id_))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Equipamento tem etiquetas/guias vinculadas")

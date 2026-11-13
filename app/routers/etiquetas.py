import base64
import io

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Equipamento, Etiqueta, User
from ..schemas import EtiquetaCreate, EtiquetaOut
from ..security import usuario_atual

router = APIRouter(prefix="/etiquetas", tags=["etiquetas"])


def texto_qr(eq: Equipamento) -> str:
    # mesmo formato do sistema antigo, para os leitores/guias continuarem funcionando
    return (f"Host: {eq.hostname or ''}\nSetor: {eq.localidade or ''}\n"
            f"Patrimônio: {eq.patrimonio or ''}\nSérie: {eq.serial or ''}\n"
            f"IP: {eq.ip or ''}\nMáscara: {eq.mascara or ''}\nGateway: {eq.gateway or ''}")


def gerar_etiqueta(db: Session, dados: EtiquetaCreate, user: User) -> Etiqueta:
    """Cria o equipamento (ou atualiza, se o patrimônio já existir) e registra o histórico."""
    eq = db.scalar(select(Equipamento).where(Equipamento.patrimonio == dados.patrimonio))
    if eq:
        for campo, valor in dados.model_dump().items():
            setattr(eq, campo, valor)
    else:
        eq = Equipamento(tipo="Computador", **dados.model_dump())
        db.add(eq)
    db.flush()
    etiqueta = Etiqueta(equipamento_id=eq.id, operador_id=user.id, **dados.model_dump())
    db.add(etiqueta)
    db.commit()
    db.refresh(etiqueta)
    return etiqueta


def qr_data_uri(texto: str) -> str:
    buf = io.BytesIO()
    qrcode.make(texto, box_size=4, border=1).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@router.post("", response_model=EtiquetaOut, status_code=201)
def criar(dados: EtiquetaCreate, db: Session = Depends(get_db), user: User = Depends(usuario_atual)):
    return gerar_etiqueta(db, dados, user)


@router.get("", response_model=list[EtiquetaOut])
def listar(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
           db: Session = Depends(get_db), _: User = Depends(usuario_atual)):
    return db.scalars(select(Etiqueta).order_by(Etiqueta.id.desc()).offset(skip).limit(limit)).all()


@router.get("/equipamento/{id_}/qrcode.png")
def qrcode_png(id_: int, db: Session = Depends(get_db), _: User = Depends(usuario_atual)):
    eq = db.get(Equipamento, id_)
    if not eq:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Equipamento não encontrado")
    img = qrcode.make(texto_qr(eq), box_size=6, border=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")

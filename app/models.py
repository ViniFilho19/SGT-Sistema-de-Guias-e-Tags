from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def agora() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(100))
    senha_hash: Mapped[str] = mapped_column(String(100))
    papel: Mapped[str] = mapped_column(String(20), default="operador")  # admin | operador
    ativo: Mapped[bool] = mapped_column(default=True)


class Equipamento(Base):
    __tablename__ = "equipamentos"
    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(50), default="Computador")
    modelo: Mapped[Optional[str]] = mapped_column(String(200))
    patrimonio: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True)
    serial: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    hostname: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    ip: Mapped[Optional[str]] = mapped_column(String(45))
    mascara: Mapped[Optional[str]] = mapped_column(String(45))
    gateway: Mapped[Optional[str]] = mapped_column(String(45))
    localidade: Mapped[Optional[str]] = mapped_column(String(200))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, onupdate=agora)


class Etiqueta(Base):
    """Histórico: cada etiqueta gerada, por quem e quando."""
    __tablename__ = "etiquetas"
    id: Mapped[int] = mapped_column(primary_key=True)
    equipamento_id: Mapped[int] = mapped_column(ForeignKey("equipamentos.id"), index=True)
    operador_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    oculta: Mapped[bool] = mapped_column(default=False, server_default="0")  # True = removida da lista de recentes
    operador_original: Mapped[Optional[str]] = mapped_column(String(100))  # nome do operador em registros importados
    equipamento: Mapped[Equipamento] = relationship()
    operador: Mapped[User] = relationship()


class Guia(Base):
    __tablename__ = "guias"
    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(30))  # GUIA DE ENTRADA | GUIA DE SAÍDA
    chamado: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    remetente: Mapped[str] = mapped_column(String(200))
    destinatario: Mapped[str] = mapped_column(String(200))
    responsavel: Mapped[Optional[str]] = mapped_column(String(200))
    operador_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    # Controle de entrega (só guias de saída): pronta -> entregue
    status: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    entregue_por: Mapped[Optional[str]] = mapped_column(String(200))   # quem entregou o equipamento
    retirado_por: Mapped[Optional[str]] = mapped_column(String(200))   # quem pegou/retirou o equipamento
    entregue_em: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    entrega_operador_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))  # quem registrou no sistema
    operador: Mapped[User] = relationship(foreign_keys=[operador_id])
    entrega_operador: Mapped[Optional[User]] = relationship(foreign_keys=[entrega_operador_id])
    itens: Mapped[list["GuiaItem"]] = relationship(back_populates="guia", cascade="all, delete-orphan")


class GuiaItem(Base):
    """Guarda uma 'foto' dos dados no momento da guia; equipamento_id liga ao cadastro, se existir."""
    __tablename__ = "guia_itens"
    id: Mapped[int] = mapped_column(primary_key=True)
    guia_id: Mapped[int] = mapped_column(ForeignKey("guias.id", ondelete="CASCADE"), index=True)
    equipamento_id: Mapped[Optional[int]] = mapped_column(ForeignKey("equipamentos.id"), index=True)
    tipo_equipamento: Mapped[str] = mapped_column(String(50))
    modelo: Mapped[Optional[str]] = mapped_column(String(200))
    patrimonio: Mapped[Optional[str]] = mapped_column(String(100))
    serial: Mapped[Optional[str]] = mapped_column(String(100))
    hostname: Mapped[Optional[str]] = mapped_column(String(100))
    ip: Mapped[Optional[str]] = mapped_column(String(45))
    guia: Mapped[Guia] = relationship(back_populates="itens")
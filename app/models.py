from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


CAMPOS_ETIQUETA = ("hostname", "ip", "patrimonio", "serial", "localidade", "mascara", "gateway")


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
    # "foto" dos dados impressos na etiqueta, no momento em que foi gerada
    hostname: Mapped[Optional[str]] = mapped_column(String(100))
    ip: Mapped[Optional[str]] = mapped_column(String(45))
    patrimonio: Mapped[Optional[str]] = mapped_column(String(100))
    serial: Mapped[Optional[str]] = mapped_column(String(100))
    localidade: Mapped[Optional[str]] = mapped_column(String(200))
    mascara: Mapped[Optional[str]] = mapped_column(String(45))
    gateway: Mapped[Optional[str]] = mapped_column(String(45))
    uso: Mapped[Optional[str]] = mapped_column(String(20))  # atendimento | prova | vazio (marcar à mão)
    equipamento: Mapped[Equipamento] = relationship()
    operador: Mapped[User] = relationship()

    @property
    def foto(self) -> SimpleNamespace:
        """Dados como estavam na etiqueta (registros antigos sem foto caem no cadastro atual)."""
        tem_foto = any(getattr(self, c) for c in CAMPOS_ETIQUETA)
        origem = self if tem_foto else self.equipamento
        return SimpleNamespace(**{c: getattr(origem, c) for c in CAMPOS_ETIQUETA})


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
    codigo_original: Mapped[Optional[str]] = mapped_column(String(30), index=True)  # ID da guia no sistema antigo
    operador_original: Mapped[Optional[str]] = mapped_column(String(100))  # operador em registros importados
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
    marca: Mapped[Optional[str]] = mapped_column(String(100))  # celular
    imei: Mapped[Optional[str]] = mapped_column(String(30))  # celular
    ddd: Mapped[Optional[str]] = mapped_column(String(5))  # chip
    linha: Mapped[Optional[str]] = mapped_column(String(30))  # chip (número da linha)
    guia: Mapped[Guia] = relationship(back_populates="itens")

# ---------- almoxarifado (peças e insumos de TI) ----------
class CategoriaPeca(Base):
    __tablename__ = "categorias_peca"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(50), unique=True)  # sempre em MAIÚSCULAS
    icone: Mapped[str] = mapped_column(String(16), default="📦")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)


class Peca(Base):
    """Item do catálogo (SKU). `quantidade` é o saldo atual; só muda por movimentação."""
    __tablename__ = "pecas"
    id: Mapped[int] = mapped_column(primary_key=True)
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias_peca.id"), index=True)
    descricao: Mapped[str] = mapped_column(String(200))
    marca: Mapped[Optional[str]] = mapped_column(String(100))
    modelo: Mapped[Optional[str]] = mapped_column(String(100))
    quantidade: Mapped[int] = mapped_column(default=0)
    quantidade_minima: Mapped[int] = mapped_column(default=2)
    observacoes: Mapped[Optional[str]] = mapped_column(String(500))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, onupdate=agora)
    categoria: Mapped[CategoriaPeca] = relationship()
    movimentos: Mapped[list["PecaMovimento"]] = relationship(back_populates="peca", cascade="all, delete-orphan")

    @property
    def situacao(self) -> str:
        """esgotado (<= 0) | baixo (até o mínimo) | ok"""
        if self.quantidade <= 0:
            return "esgotado"
        return "baixo" if self.quantidade <= self.quantidade_minima else "ok"


class NotaFiscal(Base):
    __tablename__ = "notas_fiscais"
    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[str] = mapped_column(String(20), index=True)
    serie: Mapped[Optional[str]] = mapped_column(String(5))
    data_emissao: Mapped[Optional[date]] = mapped_column(Date)
    cnpj_fornecedor: Mapped[Optional[str]] = mapped_column(String(14))  # só dígitos
    chave_acesso: Mapped[Optional[str]] = mapped_column(String(44), unique=True)
    protocolo: Mapped[Optional[str]] = mapped_column(String(50))
    arquivo: Mapped[Optional[str]] = mapped_column(String(100))        # PDF salvo em data/notasfiscais/
    arquivo_nome: Mapped[Optional[str]] = mapped_column(String(200))   # nome original do arquivo enviado
    usuario_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)


class PecaMovimento(Base):
    """Extrato (kardex): cada entrada ou saída, por quem, quando e o saldo resultante."""
    __tablename__ = "peca_movimentos"
    id: Mapped[int] = mapped_column(primary_key=True)
    peca_id: Mapped[int] = mapped_column(ForeignKey("pecas.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(10))  # entrada | saida
    quantidade: Mapped[int] = mapped_column()
    saldo_apos: Mapped[int] = mapped_column()
    usuario_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, index=True)
    marca: Mapped[Optional[str]] = mapped_column(String(100))
    modelo: Mapped[Optional[str]] = mapped_column(String(100))
    numero_serie: Mapped[Optional[str]] = mapped_column(String(100))
    chamado: Mapped[Optional[str]] = mapped_column(String(100))       # obrigatório na saída
    patrimonio: Mapped[Optional[str]] = mapped_column(String(100))    # equipamento que recebeu a peça (saída)
    equipamento_id: Mapped[Optional[int]] = mapped_column(ForeignKey("equipamentos.id"))
    observacoes: Mapped[Optional[str]] = mapped_column(String(500))
    nota_fiscal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("notas_fiscais.id"), index=True)
    peca: Mapped[Peca] = relationship(back_populates="movimentos")
    usuario: Mapped[User] = relationship()
    equipamento: Mapped[Optional[Equipamento]] = relationship()
    nota_fiscal: Mapped[Optional[NotaFiscal]] = relationship()

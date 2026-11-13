import ipaddress
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Base(BaseModel):
    # remove espaços e transforma "" em None (ver validador abaixo)
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def vazio_vira_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


def _checa_ip(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    try:
        ipaddress.ip_address(v)
    except ValueError:
        raise ValueError("endereço inválido")
    return v


# ---------- auth / usuários ----------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(Base):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9._-]+$")
    nome: str = Field(min_length=2, max_length=100)
    senha: str = Field(min_length=8, max_length=128)
    papel: Literal["admin", "operador"] = "operador"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    nome: str
    papel: str
    ativo: bool


# ---------- equipamentos ----------
class EquipamentoIn(Base):
    tipo: str = Field(default="Computador", max_length=50)
    modelo: Optional[str] = Field(default=None, max_length=200)
    patrimonio: Optional[str] = Field(default=None, max_length=100)
    serial: Optional[str] = Field(default=None, max_length=100)
    hostname: Optional[str] = Field(default=None, max_length=100)
    ip: Optional[str] = Field(default=None, max_length=45)
    mascara: Optional[str] = Field(default=None, max_length=45)
    gateway: Optional[str] = Field(default=None, max_length=45)
    localidade: Optional[str] = Field(default=None, max_length=200)

    _ips = field_validator("ip", "mascara", "gateway")(_checa_ip)


class EquipamentoOut(EquipamentoIn):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)
    id: int
    criado_em: datetime
    atualizado_em: datetime


# ---------- etiquetas ----------
class EtiquetaCreate(Base):
    hostname: str = Field(max_length=100)
    ip: str = Field(max_length=45)
    patrimonio: str = Field(max_length=100)
    serial: str = Field(max_length=100)
    localidade: str = Field(max_length=200)
    mascara: Optional[str] = Field(default=None, max_length=45)
    gateway: Optional[str] = Field(default=None, max_length=45)

    _ips = field_validator("ip", "mascara", "gateway")(_checa_ip)


class EtiquetaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    criado_em: datetime
    equipamento: EquipamentoOut
    operador: UserOut


# ---------- guias ----------
class GuiaItemIn(Base):
    tipo_equipamento: str = Field(max_length=50)
    modelo: Optional[str] = Field(default=None, max_length=200)
    patrimonio: Optional[str] = Field(default=None, max_length=100)
    serial: Optional[str] = Field(default=None, max_length=100)
    hostname: Optional[str] = Field(default=None, max_length=100)
    ip: Optional[str] = Field(default=None, max_length=45)

    _ips = field_validator("ip")(_checa_ip)


class GuiaItemOut(GuiaItemIn):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)
    id: int
    equipamento_id: Optional[int] = None


class GuiaCreate(Base):
    tipo: Literal["GUIA DE ENTRADA", "GUIA DE SAÍDA"]
    chamado: Optional[str] = Field(default=None, max_length=100)
    remetente: str = Field(max_length=200)
    destinatario: str = Field(max_length=200)
    responsavel: Optional[str] = Field(default=None, max_length=200)
    itens: list[GuiaItemIn] = Field(min_length=1, max_length=200)


class GuiaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tipo: str
    chamado: Optional[str]
    remetente: str
    destinatario: str
    responsavel: Optional[str]
    criado_em: datetime
    status: Optional[str] = None
    entregue_por: Optional[str] = None
    retirado_por: Optional[str] = None
    entregue_em: Optional[datetime] = None
    operador: UserOut
    itens: list[GuiaItemOut]

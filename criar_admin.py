"""Uso: python criar_admin.py  -> cria o primeiro administrador."""
import getpass

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import User
from app.security import hash_senha

Base.metadata.create_all(engine)
username = input("Usuário: ").strip()
nome = input("Nome completo: ").strip()
senha = getpass.getpass("Senha (mín. 8 caracteres): ")
if len(senha) < 8:
    raise SystemExit("Senha muito curta.")

with SessionLocal() as db:
    if db.scalar(select(User).where(User.username == username)):
        raise SystemExit("Usuário já existe.")
    db.add(User(username=username, nome=nome, papel="admin", senha_hash=hash_senha(senha)))
    db.commit()
print("Administrador criado.")

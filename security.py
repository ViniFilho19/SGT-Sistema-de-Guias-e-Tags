import time
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_senha(senha: str) -> str:
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()


def confere_senha(senha: str, hash_: str) -> bool:
    try:
        return bcrypt.checkpw(senha.encode(), hash_.encode())
    except ValueError:
        return False


def criar_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode({"sub": str(user_id), "exp": exp}, settings.secret_key, algorithm="HS256")


def usuario_por_token(token: str, db: Session):
    try:
        dados = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user = db.get(User, int(dados["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    return user if user and user.ativo else None


def usuario_atual(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    user = usuario_por_token(token, db)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


# Limite de tentativas de login (em memória: vale por processo; use Redis se rodar várias instâncias)
_falhas: dict[str, list[float]] = {}
MAX_FALHAS, JANELA = 5, 900


def bloqueado(chave: str) -> bool:
    agora = time.time()
    f = [t for t in _falhas.get(chave, []) if agora - t < JANELA]
    _falhas[chave] = f
    return len(f) >= MAX_FALHAS


def registrar_falha(chave: str) -> None:
    _falhas.setdefault(chave, []).append(time.time())


def limpar_falhas(chave: str) -> None:
    _falhas.pop(chave, None)


def somente_admin(user: User = Depends(usuario_atual)) -> User:
    if user.papel != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Apenas administradores")
    return user

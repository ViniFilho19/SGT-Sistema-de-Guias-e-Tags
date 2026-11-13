from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import Token, UserCreate, UserOut
from ..security import (bloqueado, confere_senha, criar_token, hash_senha, limpar_falhas,
                        registrar_falha, somente_admin, usuario_atual)

router = APIRouter(tags=["auth"])

# hash falso para gastar o mesmo tempo quando o usuário não existe (evita enumeração de usuários)
_FALSO = hash_senha("senha-falsa")


@router.post("/auth/login", response_model=Token)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    chave = f"{request.client.host if request.client else '?'}|{form.username.lower()}"
    if bloqueado(chave):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Muitas tentativas. Aguarde 15 minutos.")
    user = db.scalar(select(User).where(User.username == form.username))
    ok = confere_senha(form.password, user.senha_hash if user else _FALSO)
    if not user or not ok or not user.ativo:
        registrar_falha(chave)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuário ou senha incorretos")
    limpar_falhas(chave)
    return Token(access_token=criar_token(user.id))


@router.get("/auth/me", response_model=UserOut)
def eu(user: User = Depends(usuario_atual)):
    return user


@router.post("/users", response_model=UserOut, status_code=201)
def criar_usuario(dados: UserCreate, db: Session = Depends(get_db), _: User = Depends(somente_admin)):
    if db.scalar(select(User).where(User.username == dados.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Usuário já existe")
    user = User(username=dados.username, nome=dados.nome, papel=dados.papel,
                senha_hash=hash_senha(dados.senha))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

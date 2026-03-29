from datetime import datetime, timedelta
from typing import Optional
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, Request, Cookie
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.database import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    access_token: Optional[str] = Cookie(default=None),
    token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[User]:
    tok = access_token or token
    if not tok:
        return None
    try:
        payload = jwt.decode(tok, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: int = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def require_user(
    current_user: Optional[User] = Depends(get_current_user),
) -> User:
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/auth/login"},
        )
    return current_user


async def require_admin(current_user: User = Depends(require_user)) -> User:
    if current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
from typing import Optional

import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# Pre-computed dummy hash for constant-time timing-safe login check
_DUMMY_HASH: str = hash_password("__dummy__")


def create_user(user_repo, email: str, password: str, name: str = "") -> dict:
    """Validate, hash password, create user. Returns user dict (no password_hash)."""
    if len(password) < 8:
        raise ValueError("Senha deve ter pelo menos 8 caracteres")
    password_hash = hash_password(password)
    user_id = user_repo.create_user(email, password_hash, name)
    return user_repo.get_by_id(user_id)


def authenticate_user(user_repo, email: str, password: str) -> Optional[dict]:
    """Verify email+password. Returns user dict (no password_hash) or None.

    Always calls verify_password even when user not found, preventing
    timing-based user enumeration attacks.
    """
    user = user_repo.get_by_email(email)
    if not user:
        verify_password(password, _DUMMY_HASH)  # constant-time dummy check
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}

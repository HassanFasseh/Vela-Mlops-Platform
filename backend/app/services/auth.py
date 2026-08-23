import os
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from backend.app.db.models import User, Workspace, WorkspaceMember, WorkspaceApiKey

SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-in-production-use-a-long-random-string")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(user_id: int, email: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": str(user_id), "username": email, "exp": expire},
        SECRET_KEY, algorithm=ALGORITHM
    )

def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

def create_user(db: Session, username: str, name: str, password: str,
                is_admin: bool = False, created_by: int = None,
                force_password_change: bool = False) -> User:
    user = User(
        username=username,
        name=name,
        password_hash=hash_password(password),
        is_admin=is_admin,
        created_by=created_by,
        force_password_change=force_password_change
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()

def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = get_user_by_username(db, username)
    if not user or not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user

def ensure_admin_exists(db: Session):
    """Create default admin account if no admin exists."""
    from backend.app.db.models import User
    admin = db.query(User).filter(User.is_admin == True).first()
    if not admin:
        admin = create_user(
            db,
            username="admin",
            name="Administrator",
            password="admin",
            is_admin=True,
            force_password_change=True
        )
        print("[auth] default admin account created — username: admin, password: admin", flush=True)
    return admin

def change_password(db: Session, user_id: int, new_password: str) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    user.password_hash = hash_password(new_password)
    user.force_password_change = False
    db.commit()
    return True

def create_workspace(db: Session, name: str, description: str, owner: User) -> Workspace:
    slug = name.lower().replace(" ", "-").replace("_", "-")
    base_slug = slug
    counter = 1
    while db.query(Workspace).filter(Workspace.slug == slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1
    workspace = Workspace(name=name, slug=slug, description=description, owner_id=owner.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    member = WorkspaceMember(user_id=owner.id, workspace_id=workspace.id, role="admin")
    db.add(member)
    db.commit()
    return workspace

def get_user_workspaces(db: Session, user_id: int) -> list:
    members = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user_id).all()
    workspace_ids = [m.workspace_id for m in members]
    return db.query(Workspace).filter(Workspace.id.in_(workspace_ids)).all()

def generate_api_key(db: Session, workspace_id: int, name: str,
                      team_id: int = None, deployment_id: int = None) -> tuple:
    raw_key = f"aodp_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]
    api_key = WorkspaceApiKey(
        workspace_id=workspace_id,
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        team_id=team_id,
        deployment_id=deployment_id,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return raw_key, api_key

def verify_api_key(db: Session, raw_key: str) -> Optional[WorkspaceApiKey]:
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = db.query(WorkspaceApiKey).filter(
        WorkspaceApiKey.key_hash == key_hash,
        WorkspaceApiKey.is_active == True
    ).first()
    if api_key:
        api_key.last_used_at = datetime.utcnow()
        db.commit()
    return api_key

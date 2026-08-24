from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, DateTime, ForeignKey, Text, Boolean, Enum
from datetime import datetime
import enum

class Base(DeclarativeBase):
    pass

class WorkspaceRole(str, enum.Enum):
    admin = "admin"
    member = "member"
    viewer = "viewer"

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=True)  # optional, for notifications
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int] = mapped_column(Integer, nullable=True)  # admin who created this user

class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))

class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    workspace_id: Mapped[int] = mapped_column(Integer, ForeignKey("workspaces.id"))
    role: Mapped[str] = mapped_column(String(20), default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class WorkspaceApiKey(Base):
    __tablename__ = "workspace_api_keys"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True)
    deployment_id: Mapped[int] = mapped_column(Integer, ForeignKey("deployments.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(200), default="")

class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, ForeignKey("workspaces.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="huggingface")  # huggingface or upload
    storage_path: Mapped[str] = mapped_column(String(500), nullable=True)  # for uploaded models
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    # Custom-runner (custom-runner/, custom-deploy.yml) fields — a
    # "huggingface" deployment (the default) leaves all four at their
    # defaults/null; a "custom" one sets model_type, input_type and
    # minio_path, and input_schema if it declared one at upload time.
    input_type: Mapped[str] = mapped_column(String(20), default="text")  # text, json, file
    model_type: Mapped[str] = mapped_column(String(20), default="huggingface")  # huggingface, custom
    minio_path: Mapped[str] = mapped_column(String(500), nullable=True)
    input_schema: Mapped[str] = mapped_column(Text, nullable=True)  # JSON string describing expected input fields for input_type="json"

class RemediationConfig(Base):
    __tablename__ = "remediation_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deployment_id: Mapped[int] = mapped_column(Integer, ForeignKey("deployments.id"), unique=True)
    workspace_id: Mapped[int] = mapped_column(Integer, ForeignKey("workspaces.id"))
    drift_threshold: Mapped[float] = mapped_column(default=0.5)
    action_type: Mapped[str] = mapped_column(String(50), default="github_issue")
    target: Mapped[str] = mapped_column(String(500), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class RemediationLog(Base):
    __tablename__ = "remediation_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_id: Mapped[int] = mapped_column(Integer, ForeignKey("remediation_configs.id"))
    deployment_id: Mapped[int] = mapped_column(Integer, ForeignKey("deployments.id"))
    drift_score: Mapped[float] = mapped_column()
    action_type: Mapped[str] = mapped_column(String(50))
    target: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20))
    response: Mapped[str] = mapped_column(Text, default="")
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ModelCard(Base):
    __tablename__ = "model_cards"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deployment_id: Mapped[int] = mapped_column(Integer, ForeignKey("deployments.id"))
    workspace_id: Mapped[int] = mapped_column(Integer, ForeignKey("workspaces.id"))
    description: Mapped[str] = mapped_column(Text, default="")
    dataset: Mapped[str] = mapped_column(Text, default="")
    dataset_size: Mapped[str] = mapped_column(String(100), default="")
    license: Mapped[str] = mapped_column(String(100), default="")
    tags: Mapped[str] = mapped_column(String(500), default="")
    performance_notes: Mapped[str] = mapped_column(Text, default="")
    limitations: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class TeamMember(Base):
    __tablename__ = "team_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(20), default="member")  # member, lead
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class TeamModelPermission(Base):
    __tablename__ = "team_model_permissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"))
    deployment_id: Mapped[int] = mapped_column(Integer, ForeignKey("deployments.id"))
    can_predict: Mapped[bool] = mapped_column(Boolean, default=True)
    can_view_metrics: Mapped[bool] = mapped_column(Boolean, default=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    granted_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

class AccessRequest(Base):
    __tablename__ = "access_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    workspace_id: Mapped[int] = mapped_column(Integer, ForeignKey("workspaces.id"))
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True)
    deployment_id: Mapped[int] = mapped_column(Integer, ForeignKey("deployments.id"), nullable=True)
    message: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, approved, denied
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str] = mapped_column(String(500), default="")

class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    ticket_type: Mapped[str] = mapped_column(String(20), default="bug")  # bug, anomaly, feedback, other
    severity: Mapped[str] = mapped_column(String(20), default="medium")  # low, medium, high, critical
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, investigating, resolved, closed
    deployment_id: Mapped[int] = mapped_column(Integer, ForeignKey("deployments.id"), nullable=True)
    workspace_id: Mapped[int] = mapped_column(Integer, ForeignKey("workspaces.id"), nullable=True)
    team_id: Mapped[int] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True)
    filed_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    filed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    resolution_note: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")  # text evidence, logs, etc

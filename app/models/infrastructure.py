"""Infrastructure models — environments, secrets, assets, services, databases."""
import json

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class Environment(Base):
    """An infrastructure environment (dev, staging, prod, etc.)."""

    __tablename__ = "infra_environments"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # local, dev, qa, uat, staging, production
    url = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="active")  # active, inactive
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "url": self.url,
            "description": self.description,
            "owner_id": self.owner_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Environment(id={self.id}, name='{self.name}', type='{self.type}')>"


class Secret(Base):
    """An encrypted secret (database password, API key, etc.)."""

    __tablename__ = "infra_secrets"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False)
    # database, authentication, ai_providers, email, storage, payments, monitoring, custom
    environment_id = Column(
        Integer, ForeignKey("infra_environments.id", ondelete="SET NULL"), nullable=True
    )
    encrypted_value = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="active")  # active, rotated, expired
    expires_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self, include_value=False, decrypted_value=None):
        d = {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "environment_id": self.environment_id,
            "description": self.description,
            "owner_id": self.owner_id,
            "status": self.status,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_value and decrypted_value:
            d["value"] = decrypted_value
        else:
            d["value"] = "••••••••"
        return d

    def __repr__(self):
        return f"<Secret(id={self.id}, name='{self.name}', category='{self.category}')>"


class SecretVersion(Base):
    """Version history for a secret (for rollback)."""

    __tablename__ = "infra_secret_versions"

    id = Column(Integer, primary_key=True, index=True)
    secret_id = Column(
        Integer, ForeignKey("infra_secrets.id", ondelete="CASCADE"), nullable=False
    )
    version = Column(Integer, nullable=False)
    encrypted_value = Column(Text, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "secret_id": self.secret_id,
            "version": self.version,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<SecretVersion(secret_id={self.secret_id}, version={self.version})>"


class SecretAccessLog(Base):
    """Audit log for all secret access (view, reveal, create, update, delete, rotate)."""

    __tablename__ = "infra_secret_access_logs"

    id = Column(Integer, primary_key=True, index=True)
    secret_id = Column(
        Integer, ForeignKey("infra_secrets.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(50), nullable=False)
    # view, reveal, create, update, delete, rotate, rollback
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ip_address = Column(String(50), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "secret_id": self.secret_id,
            "user_id": self.user_id,
            "action": self.action,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "ip_address": self.ip_address,
        }

    def __repr__(self):
        return f"<SecretAccessLog(secret_id={self.secret_id}, action='{self.action}')>"


class Asset(Base):
    """An infrastructure asset (server, VPS, GPU cluster, domain, API, certificate, etc.)."""

    __tablename__ = "infra_assets"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    asset_type = Column(String(50), nullable=False)
    # server, vps, gpu_cluster, database, domain, api, certificate, service, other
    environment_id = Column(
        Integer, ForeignKey("infra_environments.id", ondelete="SET NULL"), nullable=True
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    team = Column(String(255), nullable=True)
    status = Column(String(50), default="active")  # active, maintenance, decommissioned
    metadata_json = Column(Text, nullable=True)  # JSON: host, IP, specs, etc.
    cost_monthly = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "asset_type": self.asset_type,
            "environment_id": self.environment_id,
            "project_id": self.project_id,
            "owner_id": self.owner_id,
            "team": self.team,
            "status": self.status,
            "metadata": json.loads(self.metadata_json) if self.metadata_json else {},
            "cost_monthly": self.cost_monthly,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Asset(id={self.id}, name='{self.name}', type='{self.asset_type}')>"


class InfraService(Base):
    """A third-party or internal service (OpenAI, Anthropic, Redis, etc.)."""

    __tablename__ = "infra_services"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    service_type = Column(String(50), nullable=False)
    # ai, database, cache, storage, email, payments, monitoring, internal
    environment_id = Column(
        Integer, ForeignKey("infra_environments.id", ondelete="SET NULL"), nullable=True
    )
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="active")
    documentation_url = Column(String(500), nullable=True)
    linked_secret_ids = Column(Text, nullable=True)  # JSON array of secret IDs
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "service_type": self.service_type,
            "environment_id": self.environment_id,
            "owner_id": self.owner_id,
            "status": self.status,
            "documentation_url": self.documentation_url,
            "linked_secret_ids": json.loads(self.linked_secret_ids)
            if self.linked_secret_ids
            else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<InfraService(id={self.id}, name='{self.name}')>"


class InfraDatabase(Base):
    """A database instance (PostgreSQL, MySQL, MongoDB, Redis, Supabase)."""

    __tablename__ = "infra_databases"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    db_type = Column(String(50), nullable=False)
    # postgresql, mysql, mongodb, redis, supabase
    host = Column(String(500), nullable=True)
    port = Column(Integer, nullable=True)
    environment_id = Column(
        Integer, ForeignKey("infra_environments.id", ondelete="SET NULL"), nullable=True
    )
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    backup_policy = Column(String(255), nullable=True)
    linked_secret_ids = Column(Text, nullable=True)  # JSON array of secret IDs
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "db_type": self.db_type,
            "host": self.host,
            "port": self.port,
            "environment_id": self.environment_id,
            "owner_id": self.owner_id,
            "backup_policy": self.backup_policy,
            "linked_secret_ids": json.loads(self.linked_secret_ids)
            if self.linked_secret_ids
            else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<InfraDatabase(id={self.id}, name='{self.name}', db_type='{self.db_type}')>"

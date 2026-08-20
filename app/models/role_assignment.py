"""RoleAssignment model — links a User to a Role on a specific Project.

This is the core of RBAC: a user can have different roles on different projects.
For example, someone can be Tech Lead on PNU Cloud but QA Lead on CloudGate.
"""
from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy import DateTime
from app.database import Base


class RoleAssignment(Base):
    """Assigns a user a role on a project."""

    __tablename__ = "role_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "project_id", name="uq_user_role_project"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User", backref="role_assignments")
    role = relationship("Role", backref="assignments")
    project = relationship("Project", backref="role_assignments")

    def __repr__(self):
        return f"<RoleAssignment(id={self.id}, user_id={self.user_id}, role_id={self.role_id}, project_id={self.project_id})>"

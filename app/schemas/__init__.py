"""Init file for schemas package."""
from app.schemas.client import ClientCreate, ClientResponse, ClientUpdate
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate

__all__ = [
    "ClientCreate", "ClientUpdate", "ClientResponse",
    "ProjectCreate", "ProjectUpdate", "ProjectResponse",
]

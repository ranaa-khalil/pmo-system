"""Init file for schemas package."""
from app.schemas.client import ClientCreate, ClientUpdate, ClientResponse
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse

__all__ = [
    "ClientCreate", "ClientUpdate", "ClientResponse",
    "ProjectCreate", "ProjectUpdate", "ProjectResponse",
]

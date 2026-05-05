"""Domain entities.

Contains core business entities such as UploadSession, Chunk, FileMetadata, etc.
Entities have identity and lifecycle tracked through the domain.
"""

from src.domain.entities.upload_session import UploadSession
from src.domain.entities.workspace import Workspace


__all__ = ["UploadSession", "Workspace"]

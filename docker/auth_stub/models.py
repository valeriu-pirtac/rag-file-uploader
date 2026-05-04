"""Pydantic models for token generation API.

Request and response models for the stub authentication service endpoints.
"""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class TokenRequest(BaseModel):
    """Request to generate JWT token.

    Attributes:
        user_id: User UUID
        workspace_id: Workspace UUID
        workspace_role: Role in workspace ("owner" or "collaborator")
        shared_file_ids: Optional list of shared file UUIDs (for collaborators)
    """

    user_id: UUID = Field(..., description="User UUID")
    workspace_id: UUID = Field(..., description="Workspace UUID")
    workspace_role: str = Field(..., description="Workspace role: owner or collaborator")
    shared_file_ids: list[UUID] | None = Field(
        default=None,
        description="Shared file IDs (for collaborators)",
    )

    @field_validator("workspace_role")
    @classmethod
    def validate_workspace_role(cls, v: str) -> str:
        """Validate workspace_role is owner or collaborator.

        Args:
            v: Role string to validate

        Returns:
            Validated role string (lowercase)

        Raises:
            ValueError: If role is not "owner" or "collaborator"
        """
        v_lower = v.lower()
        if v_lower not in ["owner", "collaborator"]:
            raise ValueError("workspace_role must be 'owner' or 'collaborator'")
        return v_lower

    @field_validator("shared_file_ids")
    @classmethod
    def validate_shared_file_ids(cls, v: list[UUID] | None) -> list[UUID] | None:
        """Validate shared_file_ids list length.

        Args:
            v: List of file IDs or None

        Returns:
            Validated list

        Raises:
            ValueError: If list exceeds maximum length
        """
        if v is not None and len(v) > 1000:
            raise ValueError("shared_file_ids cannot exceed 1000 items")
        return v


class TokenResponse(BaseModel):
    """Response with generated JWT token.

    Attributes:
        access_token: JWT access token (RS256 signed)
        token_type: Token type (always "Bearer")
        expires_in: Token expiry duration in seconds (3600 = 1 hour)
    """

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="Bearer", description="Token type")
    expires_in: int = Field(default=3600, description="Token expiry in seconds")

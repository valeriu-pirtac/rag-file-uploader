"""DTO for process chunk use case response."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessChunkResponse:
    """Response DTO for process chunk use case.

    Contains the new offset after successful chunk processing. The client
    uses this offset for the next chunk upload (tus protocol).

    Attributes:
        new_offset: Updated byte offset after this chunk (offset += chunk_size)
    """

    new_offset: int

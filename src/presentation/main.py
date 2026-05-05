"""FastAPI application entry point.

This module initializes the FastAPI application with all routers,
middleware, and configuration.
"""

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.domain.exceptions import AuthenticationError
from src.presentation.api.middleware.auth import get_jwt_validator
from src.presentation.api.v1.routers import uploads


log = structlog.get_logger(__name__)


app = FastAPI(
    title="RAG File Uploader",
    description="Chunked upload service for RAG pipeline with resumability and integrity verification",
    version="0.1.0",
)


# Include routers
app.include_router(uploads.router)


@app.middleware("http")
async def jwt_validation_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Validate JWT on all /v1/* endpoints.

    This middleware enforces authentication on all API endpoints under /v1/*
    while leaving health and root endpoints public.
    """
    # Skip authentication for health and root endpoints
    if request.url.path in ["/", "/health"]:
        return await call_next(request)

    # Require authentication for /v1/* endpoints (including exact /v1 path)
    if request.url.path == "/v1" or request.url.path.startswith("/v1/"):
        authorization = request.headers.get("Authorization")
        if not authorization:
            log.warning("middleware_auth_failed", reason="missing_header", path=request.url.path)
            return JSONResponse(status_code=401, content={"detail": "Missing Authorization header"})

        try:
            # Validate JWT and attach claims to request state
            validator = get_jwt_validator()
            # Extract token from "Bearer <token>"
            if not authorization.startswith("Bearer "):
                log.warning(
                    "middleware_auth_failed", reason="invalid_format", path=request.url.path
                )
                return JSONResponse(
                    status_code=401, content={"detail": "Missing or invalid Authorization header"}
                )

            token = authorization[len("Bearer ") :]
            claims = await validator.validate(token)
            request.state.current_user = claims

            log.info(
                "middleware_auth_success",
                path=request.url.path,
                user_id=str(claims.user_id),
                workspace_id=str(claims.workspace_id),
            )
        except AuthenticationError as e:
            log.warning(
                "middleware_auth_failed", reason="auth_error", error=str(e), path=request.url.path
            )
            return JSONResponse(status_code=401, content={"detail": "Authentication failed"})
        except Exception as e:
            log.error(
                "middleware_auth_failed", reason="unexpected", error=str(e), path=request.url.path
            )
            return JSONResponse(status_code=401, content={"detail": "Authentication failed"})

    return await call_next(request)


@app.get("/")
async def root() -> dict[str, str]:
    """Health check endpoint."""
    return {"service": "rag-file-uploader", "status": "healthy", "version": "0.1.0"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint for monitoring."""
    return {"status": "healthy"}

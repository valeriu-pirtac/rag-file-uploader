"""Stub authentication service FastAPI application.

Provides JWT token generation for local development testing. This service
generates valid RS256-signed JWT tokens with configurable user/workspace claims.

DEVELOPMENT ONLY - DO NOT USE IN PRODUCTION

Endpoints:
    POST /generate-token - Generate JWT token with user/workspace claims
    GET /.well-known/jwks.json - Get public key in JWKS format
    GET /health - Health check endpoint
"""

import json
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import structlog
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from .keys import RSAKeyManager
from .models import TokenRequest, TokenResponse


# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)

log = structlog.get_logger(__name__)

# Global key manager (initialized on startup)
key_manager: RSAKeyManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[Any, Any]:
    """Lifespan context manager for startup and shutdown events.

    Initializes the RSA key manager on startup and cleans up on shutdown.
    """
    global key_manager

    # Startup
    log.info("stub_auth_starting", version="1.0.0")

    # Initialize key manager
    key_manager = RSAKeyManager()
    key_manager.initialize()

    log.info("stub_auth_started", keys_initialized=True)

    yield

    # Shutdown
    log.info("stub_auth_shutdown")


# FastAPI application
app = FastAPI(
    title="Stub Auth Service",
    description="Development-only JWT token generation service for testing auth flows",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/generate-token", response_model=TokenResponse, tags=["Authentication"])
async def generate_token(request: TokenRequest) -> TokenResponse:
    """Generate JWT token for testing.

    Creates a RS256-signed JWT token with the specified user and workspace claims.
    Token is valid for 1 hour from generation time.

    Args:
        request: Token request with user_id, workspace_id, role, and optional shared files

    Returns:
        TokenResponse with signed JWT token and metadata

    Raises:
        HTTPException: 500 if token signing fails or key manager not initialized
    """
    if key_manager is None:
        log.error("token_generation_failed", reason="key_manager_not_initialized")
        raise HTTPException(
            status_code=500,
            detail="Key manager not initialized",
        )

    start_time = time.perf_counter()

    try:
        # Build JWT claims
        now = datetime.now(UTC)
        expiry = now + timedelta(hours=1)  # 1 hour expiry

        claims = {
            "user_id": str(request.user_id),
            "active_workspace_id": str(request.workspace_id),  # Note: active_workspace_id
            "workspace_role": request.workspace_role,
            "exp": int(expiry.timestamp()),
            "iat": int(now.timestamp()),
        }

        # Add optional shared_file_ids for collaborators
        # Normalize empty list to None to avoid semantic ambiguity in JWT
        if request.shared_file_ids is not None and len(request.shared_file_ids) > 0:
            claims["shared_file_ids"] = [str(fid) for fid in request.shared_file_ids]

        # Sign token with RS256
        token = jwt.encode(
            claims,
            key_manager.get_private_key(),
            algorithm="RS256",
        )

        # Measure generation time
        duration_ms = (time.perf_counter() - start_time) * 1000

        log.info(
            "token_generated",
            user_id=str(request.user_id),
            workspace_id=str(request.workspace_id),
            workspace_role=request.workspace_role,
            has_shared_files=request.shared_file_ids is not None,
            duration_ms=duration_ms,
        )

        return TokenResponse(
            access_token=token,
            token_type="Bearer",
            expires_in=3600,
        )

    except Exception as e:
        log.error("token_generation_failed", error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail=f"Token generation failed: {str(e)}",
        ) from e


@app.get("/.well-known/jwks.json", tags=["Keys"])
async def get_jwks() -> Response:
    """Get public key in JWKS format.

    Returns the RSA public key in JSON Web Key Set (JWKS) format for token
    verification. This endpoint follows RFC 7517 specification.

    Returns:
        JWKS JSON with public key for token verification

    Raises:
        HTTPException: 500 if key manager not initialized
    """
    if key_manager is None:
        log.error("jwks_failed", reason="key_manager_not_initialized")
        raise HTTPException(
            status_code=500,
            detail="Key manager not initialized",
        )

    try:
        jwks = key_manager.get_public_key_jwks()
        log.info("jwks_retrieved")
        # Add cache headers since keys rarely change
        return Response(
            content=json.dumps(jwks),
            media_type="application/json",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except Exception as e:
        log.error("jwks_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"JWKS retrieval failed: {str(e)}",
        ) from e


@app.get("/health", tags=["Operations"])
async def health() -> dict[str, str | bool]:
    """Health check endpoint.

    Returns service status and basic information. Used by Docker healthcheck
    and monitoring systems.

    Returns:
        Health status dictionary
    """
    return {
        "status": "ok",
        "service": "stub-auth",
        "version": "1.0.0",
        "keys_initialized": key_manager is not None,
    }


@app.get("/", tags=["Operations"])
async def root() -> dict[str, str | dict[str, str]]:
    """Root endpoint with service information.

    Returns:
        Service information and available endpoints
    """
    return {
        "service": "stub-auth",
        "description": "Development-only JWT token generation service",
        "version": "1.0.0",
        "endpoints": {
            "generate_token": "POST /generate-token",
            "jwks": "GET /.well-known/jwks.json",
            "health": "GET /health",
            "docs": "GET /docs",
        },
        "warning": "DEVELOPMENT ONLY - DO NOT USE IN PRODUCTION",
    }

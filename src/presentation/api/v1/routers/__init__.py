"""API v1 routers.

FastAPI route handlers for:
- POST /v1/uploads - Initiate upload session
- PATCH /v1/uploads/{id} - Upload chunk
- HEAD /v1/uploads/{id} - Query offset
- DELETE /v1/uploads/{id} - Abort session
- GET /v1/uploads - List sessions
- GET /v1/uploads/{id} - Get session metadata
"""

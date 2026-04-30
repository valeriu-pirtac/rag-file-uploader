"""FastAPI application entry point.

This module initializes the FastAPI application with all routers,
middleware, and configuration.
"""

from fastapi import FastAPI

app = FastAPI(
    title="RAG File Uploader",
    description="Chunked upload service for RAG pipeline with resumability and integrity verification",
    version="0.1.0",
)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"service": "rag-file-uploader", "status": "healthy", "version": "0.1.0"}


@app.get("/health")
async def health():
    """Health check endpoint for monitoring."""
    return {"status": "healthy"}

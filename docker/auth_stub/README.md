# Stub Auth Service

**Development-only JWT token generation service for local testing**

⚠️ **WARNING: This service is for LOCAL DEVELOPMENT ONLY. DO NOT USE IN PRODUCTION!**

## Overview

The stub auth service is a lightweight FastAPI application that generates valid RS256-signed JWT tokens for testing authentication and authorization flows during local development. It eliminates the need for external authentication services while maintaining production-like JWT validation patterns.

## Features

- **RS256 JWT Signing**: Generates tokens with RSA asymmetric signatures (matches production)
- **Automatic Key Management**: Generates and persists RSA key pairs across restarts
- **JWKS Endpoint**: Exposes public key in standard RFC 7517 format
- **Flexible Claims**: Supports owner and collaborator roles with shared file permissions
- **Docker Ready**: Runs as a containerized service in docker-compose
- **Fast**: Token generation in <10ms, suitable for automated testing

## Architecture

### Key Generation

The service uses 2048-bit RSA keys with RS256 signing algorithm:

- **Private Key**: Used to sign JWT tokens (stored in Docker volume)
- **Public Key**: Used by main service for token verification (exposed via JWKS)
- **Persistence**: Keys are stored in `/app/keys/` volume and reused across restarts
- **Format**: PEM encoding for compatibility

### JWT Claims Structure

Generated tokens include the following claims:

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "active_workspace_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "workspace_role": "owner",
  "shared_file_ids": ["f47ac10b-58cc-4372-a567-0e02b2c3d479"],
  "exp": 1746393600,
  "iat": 1746390000
}
```

**Required Claims:**
- `user_id` (string): UUID of the user
- `active_workspace_id` (string): UUID of the workspace
- `workspace_role` (string): "owner" or "collaborator"
- `exp` (int): Expiration timestamp (1 hour from issue)
- `iat` (int): Issued-at timestamp

**Optional Claims:**
- `shared_file_ids` (list[string]): UUIDs of files accessible to collaborator

## API Endpoints

### POST /generate-token

Generate a JWT token for testing.

**Request Body:**

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "workspace_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "workspace_role": "owner",
  "shared_file_ids": ["f47ac10b-58cc-4372-a567-0e02b2c3d479"]
}
```

**Response:**

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

**Validation Rules:**
- `workspace_role` must be "owner" or "collaborator"
- `shared_file_ids` is optional (typically used for collaborators)
- All IDs must be valid UUIDs

### GET /.well-known/jwks.json

Get the public key in JWKS format (RFC 7517).

**Response:**

```json
{
  "keys": [
    {
      "kty": "RSA",
      "use": "sig",
      "alg": "RS256",
      "kid": "stub-auth-key-1",
      "n": "xGOr-H7A...",
      "e": "AQAB"
    }
  ]
}
```

### GET /health

Health check endpoint for monitoring and Docker healthcheck.

**Response:**

```json
{
  "status": "ok",
  "service": "stub-auth",
  "version": "1.0.0",
  "keys_initialized": true
}
```

## Usage

### Quick Start

1. **Start the service:**

   ```bash
   docker compose up auth-stub -d
   ```

2. **Wait for service to be healthy:**

   ```bash
   docker compose ps auth-stub
   ```

3. **Generate a token:**

   ```bash
   curl -X POST http://localhost:8001/generate-token \
     -H "Content-Type: application/json" \
     -d '{
       "user_id": "550e8400-e29b-41d4-a716-446655440000",
       "workspace_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
       "workspace_role": "owner"
     }'
   ```

4. **Use the token:**

   ```bash
   export TOKEN="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
   curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/v1/uploads
   ```

### Automated Setup

Use the provided setup script to automatically configure JWT authentication:

```bash
./docker/scripts/setup-dev-jwt.sh
```

This script:
- Starts the auth-stub service if not running
- Fetches the public key from the service
- Updates `.env` with `JWT_PUBLIC_KEY`
- Provides example token generation commands

### Testing Different Roles

**Owner Token** (full workspace access):

```bash
curl -X POST http://localhost:8001/generate-token \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "workspace_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "workspace_role": "owner"
  }'
```

**Collaborator Token** (limited to shared files):

```bash
curl -X POST http://localhost:8001/generate-token \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "123e4567-e89b-12d3-a456-426614174000",
    "workspace_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "workspace_role": "collaborator",
    "shared_file_ids": [
      "f47ac10b-58cc-4372-a567-0e02b2c3d479",
      "9c93d5a5-5d7d-4a9d-9b9e-9e5e9e5e9e5e"
    ]
  }'
```

### Integration with Main Service

1. **Get the public key:**

   ```bash
   docker compose exec auth-stub cat /app/keys/public.pem
   ```

2. **Add to `.env`:**

   ```bash
   # Convert newlines to \n and add to .env
   JWT_PUBLIC_KEY=-----BEGIN PUBLIC KEY-----\nMIIBIjAN...\n-----END PUBLIC KEY-----
   ```

3. **Start the main service:**

   ```bash
   docker compose up upload-service
   ```

4. **Test authentication:**

   The main service will now validate tokens signed by the stub auth service.

## Docker Configuration

### Service Definition (docker-compose.yml)

```yaml
auth-stub:
  build:
    context: ./auth-stub
    dockerfile: Dockerfile
  container_name: rag-uploader-auth-stub
  ports:
    - "8001:8001"
  volumes:
    - auth_stub_keys:/app/keys
  healthcheck:
    test: ["CMD", "wget", "--spider", "-q", "http://localhost:8001/health"]
    interval: 10s
    timeout: 5s
    retries: 3
    start_period: 5s
  networks:
    - rag-uploader-network
  restart: unless-stopped
```

### Key Persistence

RSA keys are stored in a Docker volume to persist across container restarts:

```yaml
volumes:
  auth_stub_keys:
    name: rag-uploader-auth-stub-keys
```

This ensures:
- Keys remain consistent across service restarts
- No need to reconfigure JWT_PUBLIC_KEY in main service
- Faster startup (no key generation on every restart)

## Security Considerations

### Development Only

This service is **NOT SECURE FOR PRODUCTION** because:

1. **No Authentication**: Anyone can generate tokens (no API key required)
2. **No Rate Limiting**: Unlimited token generation allowed
3. **No Token Revocation**: Once issued, tokens are valid until expiry
4. **Stored Keys**: Private key stored in Docker volume (not HSM)
5. **No Audit Logging**: Limited logging of token generation

### Why These Limitations Are Acceptable

- Service runs only in local development environment
- No exposure to internet (localhost only)
- Simplifies development workflow
- Real auth service replaces it in production

### Production Migration

When moving to production:

1. **Remove stub auth service** from docker-compose
2. **Update JWT_PUBLIC_KEY** to production auth service public key
3. **No code changes required** in upload service (RS256 validation remains identical)

The upload service is designed to work with any RS256 JWT provider, making the transition seamless.

## Troubleshooting

### Token Validation Fails

**Problem**: Main service rejects tokens with "Invalid JWT token" error.

**Solutions**:
1. Verify JWT_PUBLIC_KEY in `.env` matches stub service public key
2. Check token hasn't expired (1 hour lifetime)
3. Ensure auth-stub service is running and healthy

**Verify public key:**

```bash
# Get public key from auth-stub
docker compose exec auth-stub cat /app/keys/public.pem

# Compare with .env
grep JWT_PUBLIC_KEY .env
```

### Keys Not Persisting

**Problem**: New keys generated on every restart, requiring .env updates.

**Solutions**:
1. Check Docker volume is correctly mounted
2. Verify `/app/keys` directory has write permissions

**Verify volume:**

```bash
docker volume inspect rag-uploader-auth-stub-keys
```

### Token Generation Returns 500

**Problem**: POST /generate-token returns 500 Internal Server Error.

**Solutions**:
1. Check stub auth service logs
2. Verify key manager initialized correctly

**View logs:**

```bash
docker compose logs auth-stub
```

### Service Won't Start

**Problem**: auth-stub container exits immediately or restarts continuously.

**Solutions**:
1. Check Docker build logs
2. Verify all dependencies are installed
3. Check for port conflicts (8001)

**Debug:**

```bash
docker compose logs auth-stub
docker compose build auth-stub --no-cache
```

## Development

### Running Tests

```bash
# Run all stub auth tests
pytest tests/unit/auth_stub/ -v

# Run specific test file
pytest tests/unit/auth_stub/test_keys.py -v
pytest tests/unit/auth_stub/test_main.py -v

# Run with coverage
pytest tests/unit/auth_stub/ --cov=docker.auth_stub --cov-report=html
```

### Project Structure

```
docker/auth-stub/
├── __init__.py          # Package marker
├── main.py              # FastAPI app and endpoints
├── models.py            # Pydantic request/response models
├── keys.py              # RSA key generation and management
├── Dockerfile           # Container image
├── requirements.txt     # Python dependencies
├── .dockerignore        # Docker build exclusions
└── README.md            # This file

tests/unit/auth_stub/
├── __init__.py          # Test package marker
├── test_keys.py         # RSA key generation tests
└── test_main.py         # API endpoint tests
```

### Dependencies

- **FastAPI**: Web framework for API endpoints
- **uvicorn**: ASGI server for running FastAPI
- **PyJWT**: JWT encoding/decoding with RS256 support
- **cryptography**: RSA key generation and management
- **Pydantic**: Request/response validation
- **structlog**: Structured logging

### Code Quality

```bash
# Lint code
ruff check docker/auth-stub/

# Format code
ruff format docker/auth-stub/

# Type checking
mypy docker/auth-stub/ --strict
```

## References

### Related Documentation

- [Story 2.6](../../artifacts/implementation-artifacts/2-6-create-stub-auth-service-for-development.md) - Complete story specification
- [Architecture Document](../../artifacts/planning-artifacts/architecture.md#authentication--security) - JWT validation strategy
- [Story 2.2](../../artifacts/implementation-artifacts/2-2-implement-jwt-validation-middleware.md) - JWT validation implementation

### External Standards

- [RFC 7519 - JSON Web Token (JWT)](https://datatracker.ietf.org/doc/html/rfc7519)
- [RFC 7517 - JSON Web Key (JWK)](https://datatracker.ietf.org/doc/html/rfc7517)
- [PyJWT Documentation](https://pyjwt.readthedocs.io/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

## License

Same as parent project - see root LICENSE file.

#!/bin/bash
# Setup script for development JWT authentication
# This script fetches the public key from the stub auth service and configures .env

set -e

echo "🔐 Setting up JWT authentication for local development"
echo "================================================"

# Check if docker compose is available
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not installed or not in PATH"
    exit 1
fi

# Check if stub auth service is running
echo "1️⃣  Checking auth-stub service status..."
if ! docker compose ps auth-stub | grep -q "running"; then
    echo "⚠️  Stub auth service is not running. Starting it now..."
    docker compose up -d auth-stub
    
    # Wait for service to be healthy
    echo "⏳ Waiting for auth-stub to be healthy..."
    timeout=30
    elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if docker compose ps auth-stub | grep -q "healthy"; then
            echo "✅ Auth-stub service is healthy"
            break
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    
    if [ $elapsed -ge $timeout ]; then
        echo "❌ Error: Auth-stub service did not become healthy within ${timeout}s"
        echo "   Check logs: docker compose logs auth-stub"
        exit 1
    fi
else
    echo "✅ Auth-stub service is running"
fi

# Fetch public key from stub auth service
echo "2️⃣  Fetching public key from auth-stub..."
PUBLIC_KEY=$(docker compose exec -T auth-stub cat /app/keys/public.pem)

if [ -z "$PUBLIC_KEY" ]; then
    echo "❌ Error: Could not fetch public key from auth-stub"
    exit 1
fi

echo "✅ Public key fetched successfully"

# Convert multi-line PEM to single line with \n
FORMATTED_KEY=$(echo "$PUBLIC_KEY" | awk '{printf "%s\\n", $0}' | sed 's/\\n$//')

# Check if .env file exists
if [ ! -f .env ]; then
    echo "3️⃣  Creating .env from .env.example..."
    cp .env.example .env
    echo "✅ Created .env file"
else
    echo "3️⃣  .env file already exists"
fi

# Update JWT_PUBLIC_KEY in .env
echo "4️⃣  Updating JWT_PUBLIC_KEY in .env..."

# Check if JWT_PUBLIC_KEY line exists
if grep -q "^JWT_PUBLIC_KEY=" .env; then
    # Update existing line
    sed -i.bak "s|^JWT_PUBLIC_KEY=.*|JWT_PUBLIC_KEY=${FORMATTED_KEY}|" .env
    rm .env.bak
    echo "✅ Updated JWT_PUBLIC_KEY in .env"
else
    # Add JWT_PUBLIC_KEY line
    echo "JWT_PUBLIC_KEY=${FORMATTED_KEY}" >> .env
    echo "✅ Added JWT_PUBLIC_KEY to .env"
fi

echo ""
echo "✅ JWT authentication setup complete!"
echo ""
echo "📋 Next steps:"
echo "   1. Verify .env has JWT_PUBLIC_KEY set"
echo "   2. Start the upload service: docker compose up upload-service"
echo "   3. Generate test tokens:"
echo ""
echo "      # Owner token:"
echo "      curl -X POST http://localhost:8001/generate-token \\"
echo "        -H 'Content-Type: application/json' \\"
echo "        -d '{\"user_id\": \"550e8400-e29b-41d4-a716-446655440000\","
echo "             \"workspace_id\": \"7c9e6679-7425-40de-944b-e07fc1f90ae7\","
echo "             \"workspace_role\": \"owner\"}'"
echo ""
echo "      # Collaborator token:"
echo "      curl -X POST http://localhost:8001/generate-token \\"
echo "        -H 'Content-Type: application/json' \\"
echo "        -d '{\"user_id\": \"123e4567-e89b-12d3-a456-426614174000\","
echo "             \"workspace_id\": \"7c9e6679-7425-40de-944b-e07fc1f90ae7\","
echo "             \"workspace_role\": \"collaborator\","
echo "             \"shared_file_ids\": [\"f47ac10b-58cc-4372-a567-0e02b2c3d479\"]}'"
echo ""
echo "   4. Use token to authenticate API requests:"
echo "      export TOKEN=\"<your_token_here>\""
echo "      curl -H \"Authorization: Bearer \$TOKEN\" http://localhost:8000/v1/uploads"
echo ""

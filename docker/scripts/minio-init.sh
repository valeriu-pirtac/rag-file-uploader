#!/bin/sh
# MinIO initialization script
# Configures lifecycle policy to clean up incomplete multipart uploads after 7 days
# This prevents orphaned upload parts from consuming storage indefinitely

set -e

echo "Waiting for MinIO to be ready..."
until mc alias set local http://minio:9000 "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"; do
    echo "MinIO not ready, waiting 2 seconds..."
    sleep 2
done

echo "MinIO is ready. Configuring lifecycle policy..."

# Create bucket if it doesn't exist
if ! mc ls local/rag-uploads >/dev/null 2>&1; then
    echo "Creating rag-uploads bucket..."
    mc mb local/rag-uploads
else
    echo "Bucket rag-uploads already exists"
fi

# Create lifecycle policy for incomplete multipart uploads
# This will delete incomplete uploads after 7 days
cat > /tmp/lifecycle.json <<'EOF'
{
    "Rules": [
        {
            "ID": "DeleteIncompleteMultipartUploads",
            "Status": "Enabled",
            "Filter": {
                "Prefix": ""
            },
            "AbortIncompleteMultipartUpload": {
                "DaysAfterInitiation": 7
            }
        }
    ]
}
EOF

echo "Applying lifecycle policy to rag-uploads bucket..."
mc ilm import local/rag-uploads < /tmp/lifecycle.json

echo "Lifecycle policy configured successfully:"
mc ilm ls local/rag-uploads

rm /tmp/lifecycle.json
echo "MinIO initialization complete"

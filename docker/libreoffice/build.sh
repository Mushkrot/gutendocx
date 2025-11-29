#!/bin/bash
# Build custom LibreOffice Docker image with fonts

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

IMAGE_NAME="gutendocx/libreoffice:latest"

echo "Building LibreOffice image with fonts..."
echo "Image name: $IMAGE_NAME"

# Build the image
docker build -t "$IMAGE_NAME" .

echo ""
echo "Done! Image built: $IMAGE_NAME"
echo ""
echo "To use this image, update config.yaml:"
echo "  toc:"
echo "    libreoffice:"
echo "      docker_image: $IMAGE_NAME"
echo ""
echo "Or update gutendocx/core/libreoffice_toc.py to use this image."

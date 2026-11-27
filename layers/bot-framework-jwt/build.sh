#!/bin/bash
set -e

# Build the Lambda Layer
cd "$(dirname "$0")"

# Create a temporary directory for dependencies
rm -rf python
mkdir -p python

# Install dependencies into the python directory
pip install \
    --target python \
    --requirement python/requirements.txt \
    --no-cache-dir

# Create the layer zip
rm -f ../bot_framework_jwt.zip
cd python
zip -r ../bot_framework_jwt.zip . -x "*.pyc" "__pycache__/*"
cd ..

echo "Layer created: layers/bot_framework_jwt.zip"

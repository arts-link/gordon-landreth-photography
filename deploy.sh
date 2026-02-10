#!/bin/bash

SITE_NAME=gordon-landreth-photography.arts-link.com

echo "🏗️  Building site..."
rm -rf public
hugo --minify --gc

echo "🚀 Deploying to S3 and invalidating CloudFront..."
AWS_PROFILE=arts-link hugo deploy --invalidateCDN

echo "✅ Site $SITE_NAME deployed successfully!"

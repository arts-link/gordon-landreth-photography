#!/bin/bash

SITE_NAME=gordon-landreth-photography.arts-link.com
BASE_DIR=~/dev/gordon-landreth-photography
CLOUDFRONT_ID=EPSVMGZTAOYO2
AWS_CREDENTIALS_FILE=~/.aws/credentials
PROFILE=arts-link  # Change this to 'benstraw' if needed

# Function to save the original default profile credentials
save_default_credentials() {
    # Extract the original aws_access_key_id and aws_secret_access_key from the default profile
    ORIGINAL_AWS_ACCESS_KEY_ID=$(awk '/^\[default\]/ {flag=1; next} /^\[/ {flag=0} flag && /aws_access_key_id/ {print $3}' "$AWS_CREDENTIALS_FILE")
    ORIGINAL_AWS_SECRET_ACCESS_KEY=$(awk '/^\[default\]/ {flag=1; next} /^\[/ {flag=0} flag && /aws_secret_access_key/ {print $3}' "$AWS_CREDENTIALS_FILE")
    
    if [ -z "$ORIGINAL_AWS_ACCESS_KEY_ID" ] || [ -z "$ORIGINAL_AWS_SECRET_ACCESS_KEY" ]; then
        echo "Could not extract original AWS credentials from the default profile."
        exit 1
    fi
}

# Function to restore the original default profile credentials
restore_default_credentials() {
    if [ -n "$ORIGINAL_AWS_ACCESS_KEY_ID" ] && [ -n "$ORIGINAL_AWS_SECRET_ACCESS_KEY" ]; then
        sed -i.bak -e "/^\[default\]/,/^\[/ s/aws_access_key_id = .*/aws_access_key_id = $ORIGINAL_AWS_ACCESS_KEY_ID/" \
                   -e "/^\[default\]/,/^\[/ s/aws_secret_access_key = .*/aws_secret_access_key = $ORIGINAL_AWS_SECRET_ACCESS_KEY/" \
                   "$AWS_CREDENTIALS_FILE"
        echo "AWS credentials for 'default' profile restored to original settings."
    fi
}

# Function to copy credentials from selected profile to default
copy_aws_credentials() {
    # Check if the profile exists in the credentials file
    if ! grep -q "^\[$PROFILE\]" "$AWS_CREDENTIALS_FILE"; then
        echo "Profile '$PROFILE' not found."
        exit 1
    fi
    
    # Extract the aws_access_key_id and aws_secret_access_key from the selected profile
    AWS_ACCESS_KEY_ID=$(awk "/^\[$PROFILE\]/ {flag=1; next} /^\[/ {flag=0} flag && /aws_access_key_id/ {print \$3}" "$AWS_CREDENTIALS_FILE")
    AWS_SECRET_ACCESS_KEY=$(awk "/^\[$PROFILE\]/ {flag=1; next} /^\[/ {flag=0} flag && /aws_secret_access_key/ {print \$3}" "$AWS_CREDENTIALS_FILE")
    
    # If variables are empty, exit with an error message
    if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
        echo "Could not extract AWS credentials from profile '$PROFILE'."
        exit 1
    fi

    # Update default profile safely with correct credentials
    if grep -q "^\[default\]" "$AWS_CREDENTIALS_FILE"; then
        # Modify the existing default profile in place
        sed -i.bak -e "/^\[default\]/,/^\[/ s/aws_access_key_id = .*/aws_access_key_id = $AWS_ACCESS_KEY_ID/" \
                   -e "/^\[default\]/,/^\[/ s/aws_secret_access_key = .*/aws_secret_access_key = $AWS_SECRET_ACCESS_KEY/" \
                   "$AWS_CREDENTIALS_FILE"
    else
        # If default profile doesn't exist, add it to the end of the file
        echo -e "\n[default]\naws_access_key_id = $AWS_ACCESS_KEY_ID\naws_secret_access_key = $AWS_SECRET_ACCESS_KEY" >> "$AWS_CREDENTIALS_FILE"
    fi

    echo "AWS credentials for '$PROFILE' copied to 'default' profile."
}

# Save the original default credentials
save_default_credentials

# Copy the AWS credentials to default
copy_aws_credentials

# Deploy the Hugo site
rm -rf "$BASE_DIR/public"
hugo --minify --gc
hugo deploy --invalidateCDN
# echo "Invalidating CloudFront cache..."
# aws cloudfront create-invalidation --distribution-id $CLOUDFRONT_ID --paths "/*" > /dev/null
echo "Site $SITE_NAME deployed successfully!"

# Restore the original default credentials
restore_default_credentials

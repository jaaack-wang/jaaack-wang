#!/bin/bash
# Script to trigger GitHub Pages deployment by making an empty commit

set -e

echo "================================================"
echo "GitHub Pages Deployment Trigger"
echo "================================================"
echo ""

# Check if we're in a git repository
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "Error: Not in a git repository"
    exit 1
fi

# Fetch latest from origin
echo "Fetching latest changes..."
git fetch origin

# Get current branch
CURRENT_BRANCH=$(git branch --show-current)
echo "Current branch: $CURRENT_BRANCH"
echo ""

# Check if we're on main or need to switch
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "Not on main branch. Do you want to switch to main? (y/n)"
    read -r response
    if [ "$response" = "y" ] || [ "$response" = "Y" ]; then
        echo "Switching to main branch..."
        git checkout main
        git pull origin main
    else
        echo "Staying on current branch: $CURRENT_BRANCH"
        echo "Note: This will trigger deployment of the current branch if it's configured for Pages."
        echo ""
    fi
fi

# Get the latest commit info
LATEST_SHA=$(git rev-parse HEAD)
LATEST_MSG=$(git log -1 --pretty=format:"%s")
echo "Latest commit on current branch:"
echo "  SHA: $LATEST_SHA"
echo "  Message: $LATEST_MSG"
echo ""

# Confirm with user
echo "This will create an empty commit to trigger GitHub Pages deployment."
echo "Do you want to proceed? (y/n)"
read -r proceed

if [ "$proceed" != "y" ] && [ "$proceed" != "Y" ]; then
    echo "Deployment trigger cancelled."
    exit 0
fi

# Create empty commit
echo ""
echo "Creating empty commit..."
git commit --allow-empty -m "Trigger Pages deployment for commit $LATEST_SHA"

# Push to origin
echo ""
echo "Pushing to origin..."
git push origin $(git branch --show-current)

echo ""
echo "================================================"
echo "✓ Deployment trigger committed and pushed!"
echo "================================================"
echo ""
echo "Next steps:"
echo "1. Visit: https://github.com/jaaack-wang/jaaack-wang/actions"
echo "2. Look for a new 'pages-build-deployment' workflow run"
echo "3. Wait for it to complete (usually 1-2 minutes)"
echo "4. Check your site: https://www.zhengxiang-wang.me"
echo ""
echo "Run ./check-deployment.sh to verify deployment status"
echo ""

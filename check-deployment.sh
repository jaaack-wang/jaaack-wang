#!/bin/bash
# Script to check if the latest commit on main has been deployed to GitHub Pages

echo "================================================"
echo "GitHub Pages Deployment Status Checker"
echo "================================================"
echo ""

# Fetch latest from origin
git fetch origin 2>/dev/null

# Get the latest commit on main branch from remote
MAIN_SHA=$(git ls-remote origin main 2>/dev/null | awk '{print $1}')

if [ -z "$MAIN_SHA" ]; then
    echo "Error: Unable to fetch main branch SHA"
    exit 1
fi

# Try to get commit details if we have the commit locally
MAIN_MSG=$(git log -1 --pretty=format:"%s" "$MAIN_SHA" 2>/dev/null || echo "Commit message not available locally")
MAIN_DATE=$(git log -1 --pretty=format:"%ci" "$MAIN_SHA" 2>/dev/null || echo "Commit date not available locally")

echo "Latest commit on main branch:"
echo "  SHA: $MAIN_SHA"
echo "  Message: $MAIN_MSG"
echo "  Date: $MAIN_DATE"
echo ""

# Get the latest deployment from GitHub API
# Note: This requires gh CLI or curl with authentication
echo "To check deployment status, visit:"
echo "  https://github.com/jaaack-wang/jaaack-wang/actions/workflows/pages/pages-build-deployment"
echo ""
echo "Or use GitHub CLI:"
echo "  gh run list --workflow=pages-build-deployment --limit=1"
echo ""
echo "To view the deployed site:"
echo "  https://www.zhengxiang-wang.me"
echo ""
echo "================================================"

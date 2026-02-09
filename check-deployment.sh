#!/bin/bash
# Script to check if the latest commit on main has been deployed to GitHub Pages

echo "================================================"
echo "GitHub Pages Deployment Status Checker"
echo "================================================"
echo ""

# Get the latest commit on main branch
MAIN_SHA=$(git rev-parse origin/main 2>/dev/null || git rev-parse main)
MAIN_MSG=$(git log -1 --pretty=format:"%s" "$MAIN_SHA")
MAIN_DATE=$(git log -1 --pretty=format:"%ci" "$MAIN_SHA")

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
echo "================================================"

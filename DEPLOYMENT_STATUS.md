# Deployment Status Report

**Date:** February 9, 2026 at 20:23 UTC

## Question: Has my new commit been deployed?

### Answer: ❌ NO - Your new commit has NOT been deployed yet

---

## Details

### Latest Commit on Main Branch
- **SHA:** `e71dbd16e4a3074ddd48f1ac02c48515c4bc7846`
- **Message:** "Update ACL paper assets and links"
- **Time:** February 9, 2026 at 14:05:04 EST (19:05:04 UTC)

### Last Deployed Commit
- **SHA:** `9c6238ed0ab42a6e0abd489ebd6ee735b5d85f59`
- **Message:** "Update ACL paper website"
- **Time:** February 9, 2026 at 05:42:59 UTC
- **Deployment:** [Workflow Run #122](https://github.com/jaaack-wang/jaaack-wang/actions/runs/21813809061)

### Status
- Your commit is **1 commit ahead** of the deployed version
- Time since last deployment: **~14.5 hours**
- No workflow run found for commit `e71dbd1`

---

## Why Hasn't It Been Deployed?

GitHub Pages deployments are typically triggered automatically when you push to the main branch. Possible reasons the deployment hasn't occurred:

1. **Workflow not triggered yet** - Sometimes there can be a delay
2. **Manual trigger required** - Check if the workflow needs manual approval
3. **Workflow configuration** - The pages-build-deployment workflow might not be set up to auto-trigger

---

## How to Check Deployment Status

### Option 1: GitHub Actions UI
Visit: [Actions > pages-build-deployment](https://github.com/jaaack-wang/jaaack-wang/actions/workflows/pages/pages-build-deployment)

### Option 2: Using GitHub CLI
```bash
gh run list --workflow=pages-build-deployment --limit=5
```

### Option 3: Check the deployed site
Visit your site at: https://www.zhengxiang-wang.me

Compare the content with what you expect from commit `e71dbd1`

### Option 4: Use the check-deployment.sh script
```bash
chmod +x check-deployment.sh
./check-deployment.sh
```

---

## Recommendations

1. **Trigger a manual deployment** if needed through GitHub Actions
2. **Check for any errors** in the Actions tab
3. **Verify GitHub Pages settings** in repository settings
4. **Wait a bit longer** - sometimes deployments take time to process

---

## GitHub Pages Configuration

This repository is set up as a GitHub Pages site:
- **Domain:** www.zhengxiang-wang.me (via CNAME)
- **Framework:** Jekyll
- **Deployment:** Automatic via GitHub Actions (pages-build-deployment workflow)
- **Base URL:** https://www.zhengxiang-wang.me

The workflow ID is: `17033936`

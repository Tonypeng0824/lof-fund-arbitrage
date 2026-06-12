#!/bin/bash
# auto-push.sh — 绕过全局gitconfig的insteadOf，通过SSH推送到GitHub
# 用法: bash auto-push.sh
set -e
REPO="/c/Users/Administrator/WorkBuddy/2026-06-01-14-52-49/arbitrage-tracker/github-pages"
TMPHOME=$(mktemp -d /tmp/gittmp.XXXXXX)
mkdir -p "$TMPHOME/.ssh"
cp ~/.ssh/github_arbitrage "$TMPHOME/.ssh/id_ed25519" 2>/dev/null
cp ~/.ssh/github_arbitrage.pub "$TMPHOME/.ssh/id_ed25519.pub" 2>/dev/null
printf '[user]\n\tname = Tonypeng0824\n\temail = 4070134@qq.com\n' > "$TMPHOME/.gitconfig"
cd "$REPO"
HOME="$TMPHOME" GIT_SSH_COMMAND="ssh -i $TMPHOME/.ssh/id_ed25519 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15" git push git@github.com:Tonypeng0824/arbitrage-tracker.git main
rm -rf "$TMPHOME"
echo "✅ 推送完成"

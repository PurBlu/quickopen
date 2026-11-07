#!/bin/bash
# One-command publish to your own GitHub account.
#
#   ./push.sh                       # repository named quickopen
#   REPO=my-name ./push.sh          # custom repository name
#   VISIBILITY=private ./push.sh    # create as private instead of public
#
# First-time setup (only once):
#   brew install gh
#   gh auth login          # choose GitHub.com -> HTTPS -> Login with a web browser
set -euo pipefail

cd "$(dirname "$0")" || exit 1
REPO="${REPO:-quickopen}"
VISIBILITY="${VISIBILITY:-public}"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI is not installed."
  echo "  Install it with:  brew install gh"
  echo "  Then run:         gh auth login"
  echo "  Then re-run:      ./push.sh"
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "You are not signed in to GitHub yet."
  echo "  Run:  gh auth login"
  echo "  Then: ./push.sh"
  exit 1
fi

LOGIN="$(gh api user --jq .login)"

# The email endpoint needs the user:email scope and may return an error object.
# Only accept a value that actually looks like an email address.
EMAIL="$(gh api user/emails --jq '.[] | select(.primary and .verified) | .email' 2>/dev/null | head -1 || true)"
if ! printf '%s' "$EMAIL" | grep -qE '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'; then
  EMAIL="${LOGIN}@users.noreply.github.com"
fi

git config user.name "$LOGIN"
git config user.email "$EMAIL"
echo "Signed in as: $LOGIN <$EMAIL>"

git add -A
if ! git diff --cached --quiet; then
  git commit -m "Update QuickOpen source and documentation"
fi

# Replace the local bootstrap author exactly once before the first push.
if [ "$(git log -1 --format=%ae)" = "quickopen@localhost" ]; then
  git commit --amend --reset-author --no-edit >/dev/null
fi

if git remote get-url origin >/dev/null 2>&1; then
  echo "Existing remote found, pushing..."
  git push -u origin HEAD
else
  echo "Creating $VISIBILITY repository '$REPO' and pushing..."
  gh repo create "$REPO" --"$VISIBILITY" --source=. --remote=origin --push
fi

echo
echo "=========================================================="
echo "  Pushed: https://github.com/$LOGIN/$REPO"
echo "  Remote: $(git remote get-url origin)"
echo "  Branch: $(git branch --show-current)"
echo "  Commit: $(git log -1 --format='%h %s')"
echo "=========================================================="

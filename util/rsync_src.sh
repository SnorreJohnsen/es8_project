#!/bin/sh
set -eu

# Ensure we are inside a git repo, and move to repo root
repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

# Load env vars from .env
if [ -f .env ]; then
	set -a
	. ./.env
	set +a
fi

: "${USER1:?USER1 is not set}"
: "${IP1:?IP1 is not set}"
: "${USER2:?USER2 is not set}"
: "${IP2:?IP2 is not set}"

dest="/home/$USER2/meshsim/repo"
remote="$USER2@$IP2"

# Make sure destination exists
ssh -J "$USER1@$IP1" "$remote" "mkdir -p '$dest'"

# Sync exactly the git-tracked, non-ignored files
git ls-files -z --cached --recurse-submodules |
	rsync -av --delete \
		--from0 --files-from=- \
		-e "ssh -J $USER1@$IP1" \
		./ "$remote:$dest/"

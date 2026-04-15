#!/bin/sh
set -eu

usage() {
	echo "Usage: $0 DEST_DIR [PATH_IN_SRC ...]" >&2
	echo "Example: $0 ./out logs run1.txt subdir/foo" >&2
	exit 2
}

[ "$#" -ge 1 ] || usage

dest=$1
shift

# Ensure we are inside a git repo, and locate .env
repo_root=$(git rev-parse --show-toplevel)
env="$repo_root/.env"

# Load env vars from .env
if [ -f "$env" ]; then
	set -a
	. "$env"
	set +a
fi

: "${USER1:?USER1 is not set}"
: "${IP1:?IP1 is not set}"
: "${USER2:?USER2 is not set}"
: "${IP2:?IP2 is not set}"

src="/home/$USER2/meshsim/output"
remote="$USER2@$IP2"
ssh_cmd="ssh -J $USER1@$IP1"

mkdir -p "$dest"

if [ "$#" -eq 0 ]; then
	# No extra paths supplied: sync everything from $src
	rsync -av --delete \
		-e "$ssh_cmd" \
		"$remote:$src/" "$dest/"
else
	# Extra paths supplied: sync only those paths from inside $src
	# Each arg is interpreted as $src/<arg>
	for p; do
		case "$p" in
		/*)
			echo "Error: paths must be relative to \$src, got absolute path: $p" >&2
			exit 1
			;;
		../* | */../* | ..)
			echo "Error: paths must not escape \$src: $p" >&2
			exit 1
			;;
		esac
	done

	{
		for p; do
			printf '%s\n' "$p"
		done
	} | rsync -av -r \
		--files-from=- \
		--relative \
		-e "$ssh_cmd" \
		"$remote:$src/" "$dest/"
fi

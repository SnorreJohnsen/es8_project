#!/bin/sh
set -eu

# Must be run from repo root
if [ ! -f .gitignore ] || [ ! -f .gitmodules ] || [ ! -f README.md ]; then
	echo "Setup must be run from repo root."
	echo "Failed finding .gitignore, .gitmodules and README.md."
	echo "$PWD does not look like the repo root."
	exit
fi

sudo apt update
sudo apt install -y \
	build-essential pkg-config libnl-3-dev libnl-genl-3-dev \
	python3 python3-venv \
	golang pigz batctl iperf3 tshark

echo "[*] Creating venv"
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

echo "[*] Building patched batman kernel module"
cd batman-patch/batman-adv
make -j "$(nproc)"
sudo make install

echo "[*] Building battpctl"
cd ../battpctl
make
cd ../..
ln -s ../../batman-patch/battpctl/battpctl .venv/bin/battpctl # put battpctl in PATH; an ugly hack but works for our use case

echo "[*] Building nsperf"
cd nsperf
go build -o ../.venv/bin/nsperf ./cmd/nsperf
cd ..

echo "[*] Done"

#!/usr/bin/env bash
# 在 macOS(GitHub Actions macos-15,arm64)上组装交付包并冒烟测试
set -euo pipefail

PY_TAG="20261003"   # 若下载 404:去 python-build-standalone releases 页换最新 tag(版本号 PBS_VER 也要跟着改)
PBS_VER="3.13.16+20261003"
ASSET="cpython-${PBS_VER}-aarch64-apple-darwin-install_only.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_TAG}/${ASSET}"

rm -rf dist
mkdir -p dist/xiaozhao
curl -fsSL "$URL" -o pbs.tar.gz
tar -xzf pbs.tar.gz -C dist/xiaozhao          # 解出 python/ 目录

./dist/xiaozhao/python/bin/python3 -m pip install --upgrade pip
./dist/xiaozhao/python/bin/python3 -m pip install -r requirements.txt

cp -R app requirements.txt start.command dist/xiaozhao/
chmod +x dist/xiaozhao/start.command dist/xiaozhao/python/bin/python3

# 冒烟 1:能 import;冒烟 2:服务能起来、/api/status 有回应
(cd dist/xiaozhao \
  && ./python/bin/python3 -c "import app, flask, requests; print('import ok')" \
  && ./python/bin/python3 -m app.main --self-test)

tar -czf xiaozhao-macos-arm64.tar.gz -C dist xiaozhao
echo "--- 确认权限位(start.command 与 python3 应为 rwxr-xr-x)---"
tar -tvzf xiaozhao-macos-arm64.tar.gz | grep -E "start.command|bin/python3$" || true
ls -lh xiaozhao-macos-arm64.tar.gz

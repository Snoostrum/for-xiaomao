#!/bin/bash
# 小灶 · Mac 启动器(双击运行)
cd "$(dirname "$0")" || exit 1
PY=./python/bin/python3
[ -x "$PY" ] || PY=$(command -v python3 || command -v python || command -v py)
if [ -z "$PY" ]; then
  echo "没找到 Python——请把整个文件夹按说明重新解压一次。"
  read -n 1 -s -r -p "按任意键关闭…"
  exit 1
fi
"$PY" -m app.main "$@"
echo
read -n 1 -s -r -p "小灶已退出。按任意键关闭此窗口…"

#!/bin/bash
# 小灶 · Mac 自检(把生成的 txt 发回即可)
# 双击不行的话:打开「终端」,输入 bash 空格,把本文件拖进去,回车。
cd "$(dirname "$0")" || exit 1
OUT="Mac自检-输出.txt"
{
  echo "== 小灶 Mac 自检 =="
  echo "时间: $(date 2>/dev/null || true)"
  echo "-- 芯片架构 --"; uname -m 2>/dev/null || echo "(uname 不可用)"
  echo "-- 系统版本 --"; sw_vers 2>/dev/null || echo "(非 macOS 或 sw_vers 不可用)"
  echo "-- CPU 型号 --"; sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "(不可用)"
  echo "-- 本脚本自身的权限位与扩展属性 --"; ls -l@ "$0" 2>/dev/null || true
  echo "-- 是否已存在 python 目录(正常应显示:没有) --"; ls -ld python 2>/dev/null || echo "(没有,正常)"
} 2>&1 | tee "$OUT"
echo
echo "已保存到:$OUT —— 把这个文件发回来就行。"
read -n 1 -s -r -p "按任意键关闭此窗口…"

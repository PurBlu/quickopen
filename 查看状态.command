#!/bin/bash
cd "$(dirname "$0")" || exit 1
./status.sh
echo
echo "网页控制面板： http://127.0.0.1:${QO_PORT:-8787}"
echo "（本窗口可直接关闭，不影响后台服务）"

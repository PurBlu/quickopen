#!/bin/bash
# 双击运行：判断官方哪一段协议还能用（用假数据，不会发短信 / 登录 / 开门）
cd "$(dirname "$0")" || exit 1
/usr/bin/python3 diagnose.py
echo
echo "（本窗口可直接关闭，不影响后台服务）"

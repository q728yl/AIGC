#!/bin/bash

# 检查是否存在 venv 目录
if [ ! -d "venv" ]; then
    echo "正在创建虚拟环境..."
    python3 -m venv venv
    echo "正在安装依赖..."
    ./venv/bin/pip install -r requirements.txt
fi

# 运行脚本
echo "启动 GPT 助手..."
./venv/bin/python call_gpt.py

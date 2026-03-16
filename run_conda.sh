#!/bin/bash

# 定义环境名称
ENV_NAME="seedance"

# 尝试自动查找 conda 路径 (支持 brew 安装的默认路径)
CONDA_PATHS=(
    "/opt/homebrew/anaconda3"
    "/opt/homebrew/Caskroom/miniconda/base"
    "/usr/local/Caskroom/miniconda/base"
    "$HOME/miniconda3"
    "$HOME/opt/miniconda3"
    "$(conda info --base 2>/dev/null)" # 尝试从现有PATH获取
)

CONDA_EXE=""

for path in "${CONDA_PATHS[@]}"; do
    if [ -f "$path/bin/conda" ]; then
        CONDA_EXE="$path/bin/conda"
        # 获取 conda.sh 脚本路径以便 source
        CONDA_SH="$path/etc/profile.d/conda.sh"
        break
    fi
done

if [ -z "$CONDA_EXE" ]; then
    echo "❌ 错误: 未找到 conda。请确保已安装 Miniconda。"
    exit 1
fi

# 加载 conda环境配置
if [ -f "$CONDA_SH" ]; then
    source "$CONDA_SH"
else
    # 备选方案：直接 eval
    eval "$($CONDA_EXE shell.bash hook)"
fi

# 检查环境是否存在
if ! conda env list | grep -q "^$ENV_NAME "; then
    echo "⚠️  环境 '$ENV_NAME' 未找到。正在尝试自动创建..."
    ./setup_conda_env.sh
fi

# 激活环境并运行
echo "🚀 在 '$ENV_NAME' 环境中启动 Seedance Agent..."
conda activate "$ENV_NAME"

# 确保使用环境内的 python
PYTHON_EXEC="$(which python3)"
echo "🐍 使用 Python: $PYTHON_EXEC"

# 自动补全依赖 (防止环境不一致导致的 ModuleNotFound)
echo "📦 检查核心依赖..."
"$PYTHON_EXEC" -m pip install requests python-dotenv openai rembg > /dev/null

"$PYTHON_EXEC" seedance_project/director_agent.py

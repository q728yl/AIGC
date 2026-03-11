import os
from openai import OpenAI
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("错误：请先在 .env 文件中设置 OPENAI_API_KEY")
    exit(1)

client = OpenAI(api_key=api_key)

print("正在获取可用模型列表...")

try:
    models = client.models.list()
    # 过滤出 GPT 系列模型并按 ID 排序
    gpt_models = [m.id for m in models.data if "gpt" in m.id or "o1" in m.id or "o3" in m.id]
    gpt_models.sort()
    
    print(f"\n✅ 成功获取！您当前可用的 GPT/O1 模型如下 ({len(gpt_models)} 个):")
    print("-" * 50)
    for model_id in gpt_models:
        print(f"• {model_id}")
    print("-" * 50)
    
    # 推荐逻辑
    print("\n🏆 推荐选择：")
    if "gpt-4o" in gpt_models:
        print("- 首选：'gpt-4o' (目前最强、最快、多模态能力最好)")
    elif "gpt-4-turbo" in gpt_models:
        print("- 次选：'gpt-4-turbo'")
    elif "o1-preview" in gpt_models:
        print("- 推理增强：'o1-preview' (适合极度复杂的逻辑推理，但速度较慢)")
    else:
        print("- 基础：'gpt-3.5-turbo'")

except Exception as e:
    print(f"❌ 获取模型列表失败: {e}")

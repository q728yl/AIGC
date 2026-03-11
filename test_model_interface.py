import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

models_to_test = [
    "gpt-5.4-pro-2026-03-05",
    "gpt-5.4-pro",
    "gpt-5.4",
    "gpt-5"
]

print("🔍 开始模型接口探测...\n")

for model in models_to_test:
    print(f"--- 测试模型: {model} ---")
    
    # 1. 测试 Chat 接口
    print(f"1. 尝试 Chat 接口...")
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=10
        )
        print(f"✅ Chat 接口成功! 回复: {response.choices[0].message.content}")
        print(f"🚀 结论: {model} 支持 Chat 接口")
        continue # 如果 Chat 成功，跳过后续测试
    except Exception as e:
        print(f"❌ Chat 接口失败: {e}")

    # 2. 测试 Completion 接口
    print(f"2. 尝试 Completion 接口...")
    try:
        response = client.completions.create(
            model=model,
            prompt="Hello",
            max_tokens=10
        )
        print(f"✅ Completion 接口成功! 回复: {response.choices[0].text}")
        print(f"🚀 结论: {model} 支持 Completion 接口")
    except Exception as e:
        print(f"❌ Completion 接口失败: {e}")
    
    print("\n")

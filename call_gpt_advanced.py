import os
import sys
from openai import OpenAI
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 获取配置
api_key = os.getenv("OPENAI_API_KEY")
model_name = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo") # 默认使用 gpt-3.5-turbo

if not api_key:
    api_key = input("请输入您的 OpenAI API Key: ")

client = OpenAI(api_key=api_key)

def chat_stream(messages):
    """流式对话函数"""
    try:
        stream = client.chat.completions.create(
            model=model_name,
            messages=messages,
            stream=True, # 开启流式输出
        )
        
        print("\nGPT: ", end="", flush=True)
        full_response = ""
        
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                content = chunk.choices[0].delta.content
                print(content, end="", flush=True)
                full_response += content
        print() # 换行
        return full_response
        
    except Exception as e:
        print(f"\n发生错误: {e}")
        return None

def main():
    print(f"OpenAI GPT 助手 (当前模型: {model_name})")
    print("输入 'quit', 'exit' 或 'q' 退出程序")
    print("输入 'clear' 清空对话历史")
    
    # 初始化对话历史
    messages = [
        {"role": "system", "content": "你是一个有用的助手。"}
    ]
    
    while True:
        try:
            user_input = input("\n你: ").strip()
        except EOFError:
            break
            
        if not user_input:
            continue
            
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("再见！")
            break
            
        if user_input.lower() == 'clear':
            messages = [{"role": "system", "content": "你是一个有用的助手。"}]
            print("对话历史已清空。")
            continue
            
        # 将用户输入加入历史
        messages.append({"role": "user", "content": user_input})
        
        # 获取回复并打印
        assistant_response = chat_stream(messages)
        
        # 将助手回复加入历史
        if assistant_response:
            messages.append({"role": "assistant", "content": assistant_response})

if __name__ == "__main__":
    main()

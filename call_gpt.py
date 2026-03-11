import os
from openai import OpenAI
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# 从环境变量获取 API Key，如果没有则提示用户输入
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    api_key = input("请输入您的 OpenAI API Key: ")

client = OpenAI(
    api_key=api_key,
    # 如果您使用的是中转服务，可能需要设置 base_url
    # base_url="https://api.openai.com/v1" 
)

def chat_with_gpt(prompt):
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # 或者 "gpt-4"
            messages=[
                {"role": "system", "content": "你是一个有用的助手。"},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"发生错误: {e}"

if __name__ == "__main__":
    print("OpenAI GPT 调用脚本")
    print("输入 'quit' 或 'exit' 退出程序")
    
    while True:
        user_input = input("\n请输入您的问题: ")
        if user_input.lower() in ['quit', 'exit']:
            break
            
        print("正在思考...")
        response = chat_with_gpt(user_input)
        print("\nGPT 回复:")
        print(response)

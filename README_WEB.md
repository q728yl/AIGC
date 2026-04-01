# Seedance AI Director Web

这是一个基于 Web 的 AI 游戏视频导演工具。

## 目录结构

- `app.py`: Flask Web 服务器
- `director_agent.py`: 核心 AI 逻辑 (Director & Artist Agents)
- `seedance_project/`
    - `games/`: 游戏数据存储目录 (支持多游戏)
        - `xundaodaqian/`: 默认游戏 (寻道大千)
            - `assets/`: 生成的素材
            - `references/`: 参考图
            - `output/`: 生成的方案 (Markdown)
            - `docs/`: 游戏上下文文档
    - `static/`: 前端静态文件 (HTML/JS/CSS)

## 快速开始

1. **安装依赖**
   确保已安装 Python 依赖 (Flask, OpenAI, python-dotenv, requests):
   ```bash
   pip install flask openai python-dotenv requests
   ```

2. **启动服务器**
   ```bash
   python app.py
   ```

3. **访问 Web 界面**
   打开浏览器访问: [http://localhost:5000](http://localhost:5000)

## 功能说明

1. **选择游戏**: 在下拉菜单中选择游戏上下文 (目前支持 `xundaodaqian`)。
   - 如需添加新游戏，只需在 `seedance_project/games/` 下新建文件夹即可。
2. **上传参考图**: 可选。上传一张图片作为视觉参考。
3. **输入指令**: 描述你想要的视频内容 (例如："生成一段战斗视频...")。
4. **生成**: 点击生成按钮，AI 将分析需求、生成素材并输出 Markdown 剧本。

## 扩展性

- **添加新游戏**:
  1. 在 `seedance_project/games/` 下创建新文件夹 (例如 `my_new_game`)。
  2. 在其中创建 `assets`, `references`, `output`, `docs` 文件夹。
  3. 在 `docs/game_context.txt` 中写入该游戏的背景设定。
  4. 重启服务器或刷新页面，新游戏将自动出现在下拉列表中。

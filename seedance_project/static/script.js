// UI Control for toggling video input based on mode
function toggleVideoInput() {
    const pipelineMode = document.querySelector('input[name="pipelineMode"]:checked').value;
    const videoGroup = document.getElementById('videoUploadGroup');
    if (pipelineMode === 'image_only') {
        videoGroup.style.display = 'none';
    } else {
        videoGroup.style.display = 'block';
    }
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadGames();
    toggleVideoInput();
    
    // 图片上传预览
    const imageInput = document.getElementById('imageInput');
    const previewImage = document.getElementById('previewImage');
    const fileLabel = document.getElementById('fileLabel');

    imageInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = (e) => {
                previewImage.src = e.target.result;
                previewImage.style.display = 'block';
                fileLabel.textContent = `已选择: ${file.name}`;
            }
            reader.readAsDataURL(file);
        }
    });

    // 视频上传预览
    const videoInput = document.getElementById('videoInput');
    const previewVideo = document.getElementById('previewVideo');
    const videoFileLabel = document.getElementById('videoFileLabel');

    videoInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
            const url = URL.createObjectURL(file);
            previewVideo.src = url;
            previewVideo.style.display = 'block';
            videoFileLabel.textContent = `已选择视频: ${file.name}`;
        }
    });
});

async function loadGames() {
    try {
        const response = await fetch('/api/games');
        const data = await response.json();
        const select = document.getElementById('gameSelect');
        
        // 清空现有选项，保留默认
        select.innerHTML = '';
        
        data.games.forEach(game => {
            const option = document.createElement('option');
            option.value = game;
            option.textContent = game;
            if (game === 'xundaodaqian') option.selected = true;
            select.appendChild(option);
        });
    } catch (error) {
        console.error('Failed to load games:', error);
    }
}

async function runPipeline() {
    const instruction = document.getElementById('instructionInput').value;
    const gameName = document.getElementById('gameSelect').value;
    const imageFile = document.getElementById('imageInput').files[0];
    const videoFile = document.getElementById('videoInput').files[0];
    const pipelineMode = document.querySelector('input[name="pipelineMode"]:checked').value;
    const generateBtn = document.getElementById('generateBtn');
    const logsDiv = document.getElementById('logs');
    const resultDiv = document.getElementById('resultContent');
    const galleryDiv = document.getElementById('assetGallery');

    if (!instruction) {
        alert('请输入创意指令！');
        return;
    }

    // UI 状态更新
    generateBtn.disabled = true;
    generateBtn.textContent = '⏳ 生成中... (Running Director)';
    
    if (pipelineMode === 'image_only') {
        logsDiv.textContent = '🚀 正在启动 Director Agent (Plan A - 纯图生图模式)...\n';
    } else {
        logsDiv.textContent = '🚀 正在启动 Director Agent (Plan C - 视频参考混合模式)...\n';
    }
    
    resultDiv.innerHTML = '';
    galleryDiv.innerHTML = '';
    const videoGalleryDiv = document.getElementById('videoGallery');
    if (videoGalleryDiv) videoGalleryDiv.innerHTML = '';

    const formData = new FormData();
    formData.append('instruction', instruction);
    formData.append('game_name', gameName);
    formData.append('pipeline_mode', pipelineMode);
    if (imageFile) {
        formData.append('image', imageFile);
    }
    if (pipelineMode === 'full_hybrid' && videoFile) {
        formData.append('video', videoFile);
    }

    try {
        const response = await fetch('/api/generate', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (result.status === 'success') {
            logsDiv.textContent = result.logs.join('\n');
            
            // 显示 Markdown 结果
            if (result.plan_content) {
                let mdContent = `### 🎬 ${result.plan_content.thought}\n\n`;
                mdContent += `**English Prompt:**\n\`\`\`\n${result.plan_content.prompt_en}\n\`\`\`\n\n`;
                mdContent += `**Chinese Prompt:**\n> ${result.plan_content.prompt_zh}`;
                resultDiv.innerHTML = marked.parse(mdContent);
            }

            // 显示视频排版（参考视频与生成结果同排）
            if (videoGalleryDiv) {
                let refHtml = '';
                
                if (pipelineMode === 'image_only') {
                    refHtml = `
                        <div class="video-card-container">
                            <div class="placeholder">纯图生图模式<br>无需参考视频</div>
                            <p>🎥 参考视频</p>
                        </div>
                    `;
                } else if (result.best_video_filename) {
                    refHtml = `
                        <div class="video-card-container">
                            <video src="/api/view/${gameName}/${encodeURIComponent(result.best_video_filename)}" controls></video>
                            <p>🎥 参考视频</p>
                        </div>
                    `;
                } else {
                    refHtml = `
                        <div class="video-card-container">
                            <div class="placeholder">未提供/未找到参考视频</div>
                            <p>🎥 参考视频</p>
                        </div>
                    `;
                }

                let genHtml = '';
                if (result.draft_submission) {
                    genHtml = `
                        <div class="video-card-container">
                            <div class="placeholder" style="color: #f39c12;">
                                ✍️ 等待确认 Prompt<br><br>
                                <span style="font-size: 0.85rem; color: #888;">请在上方编辑并确认后提交</span>
                            </div>
                            <p>🎬 生成结果</p>
                        </div>
                    `;
                    
                    // Show the edit prompt card
                    const editCard = document.getElementById('editPromptCard');
                    const editInput = document.getElementById('editPromptInput');
                    if (editCard && editInput) {
                        editCard.style.display = 'block';
                        // Keep a global reference to the draft
                        window.currentDraft = result.draft_submission;
                        editInput.value = result.draft_submission.prompt_text;
                    }
                    
                } else {
                    genHtml = `
                        <div class="video-card-container">
                            <div class="placeholder">未提交生成任务</div>
                            <p>🎬 生成结果</p>
                        </div>
                    `;
                }

                videoGalleryDiv.innerHTML = refHtml + genHtml;
            }

            // 显示图片素材
            if (result.new_assets && result.new_assets.length > 0) {
                result.new_assets.forEach(filename => {
                    const card = document.createElement('div');
                    const img = document.createElement('img');
                    const caption = document.createElement('p');

                    card.className = 'asset-card';
                    img.src = `/api/view/${gameName}/${encodeURIComponent(filename)}`;
                    img.alt = filename;
                    img.title = filename;
                    img.loading = 'lazy';
                    caption.textContent = filename;

                    card.appendChild(img);
                    card.appendChild(caption);
                    galleryDiv.appendChild(card);
                });
            } else {
                galleryDiv.innerHTML = '<p>没有生成新的图片素材。</p>';
            }

            if (result.draft_submission) {
                logsDiv.textContent += `\n\n✍️ 请在上方“编辑与确认 Prompt”卡片中检查 Prompt。确认无误后点击绿色按钮提交给 Seedance API。`;
            }

        } else {
            logsDiv.textContent += `\n❌ 错误: ${result.message || result.error}`;
        }
    } catch (error) {
        logsDiv.textContent += `\n❌ 网络错误: ${error.message}`;
    } finally {
        generateBtn.disabled = false;
        generateBtn.textContent = '🚀 开始生成 (Run Director)';
    }
}

async function submitToSeedance() {
    const editCard = document.getElementById('editPromptCard');
    const editInput = document.getElementById('editPromptInput');
    const submitBtn = document.getElementById('submitSeedanceBtn');
    const logsDiv = document.getElementById('logs');
    const gameName = document.getElementById('gameSelect').value;
    
    if (!window.currentDraft) {
        alert("没有可提交的草稿");
        return;
    }
    
    // Update the draft with user's edited prompt
    const draft = window.currentDraft;
    draft.prompt_text = editInput.value;
    
    submitBtn.disabled = true;
    submitBtn.textContent = '提交中...';
    
    try {
        const response = await fetch('/api/submit_task', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(draft)
        });
        
        const result = await response.json();
        
        if (result.status === 'success') {
            const taskId = result.task_id;
            logsDiv.textContent += `\n\n🎉 任务已成功提交至 Seedance 2.0 API！Task ID: ${taskId}\n正在后台轮询生成结果，请稍候...`;
            
            // Hide the edit card
            editCard.style.display = 'none';
            
            // Update the UI
            const videoGalleryDiv = document.getElementById('videoGallery');
            if (videoGalleryDiv) {
                const genCards = videoGalleryDiv.querySelectorAll('.video-card-container');
                if (genCards.length > 1) {
                    genCards[1].innerHTML = `
                        <div class="placeholder" style="color: #4a90e2;">
                            🚀 任务已提交，视频生成中<br><br>
                            Task ID:<br>${taskId}<br><br>
                            <span style="font-size: 0.85rem; color: #888;">请耐心等待，页面将自动更新</span>
                        </div>
                        <p>🎬 生成结果</p>
                    `;
                }
            }
            
            // Start polling
            pollTaskStatus(gameName, taskId, logsDiv);
            
        } else {
            logsDiv.textContent += `\n❌ 提交失败: ${result.message || result.error}`;
            alert(`提交失败: ${result.message || result.error}`);
        }
    } catch (error) {
        logsDiv.textContent += `\n❌ 网络错误: ${error.message}`;
        alert(`网络错误: ${error.message}`);
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = '✈️ 确认并提交给 Seedance API';
    }
}

async function pollTaskStatus(gameName, taskId, logsDiv) {
    const videoGalleryDiv = document.getElementById('videoGallery');
    let attempts = 0;
    const maxAttempts = 60; // 约 10 分钟 (60 * 10秒)
    
    const intervalId = setInterval(async () => {
        try {
            attempts++;
            const response = await fetch(`/api/check_task/${gameName}/${taskId}`);
            const data = await response.json();
            
            if (data.status === 'succeeded') {
                clearInterval(intervalId);
                logsDiv.textContent += `\n\n✅ 视频生成成功！已保存至本地。`;
                
                // 更新UI展示生成的视频
                if (videoGalleryDiv) {
                    const genCards = videoGalleryDiv.querySelectorAll('.video-card-container');
                    if (genCards.length > 1) {
                        const targetCard = genCards[1];
                        targetCard.innerHTML = `
                            <video src="/api/view/${gameName}/${encodeURIComponent(data.local_filename)}" controls autoplay loop></video>
                            <p>🎬 最终生成视频</p>
                            <a href="/api/view/${gameName}/${encodeURIComponent(data.local_filename)}" download="${data.local_filename}" style="margin-top: 10px; font-size: 0.9rem; color: #4a90e2; text-decoration: none;">⬇️ 点击下载</a>
                        `;
                    }
                }
            } else if (data.status === 'failed' || data.status === 'error') {
                clearInterval(intervalId);
                logsDiv.textContent += `\n\n❌ 视频生成失败: ${data.error || data.message}`;
                
                if (videoGalleryDiv) {
                    const genCards = videoGalleryDiv.querySelectorAll('.video-card-container');
                    if (genCards.length > 1) {
                        genCards[1].innerHTML = `
                            <div class="placeholder" style="color: #e74c3c;">生成失败，请查看日志</div>
                            <p>🎬 生成结果</p>
                        `;
                    }
                }
            } else {
                // 继续等待
                if (attempts >= maxAttempts) {
                    clearInterval(intervalId);
                    logsDiv.textContent += `\n\n⚠️ 轮询超时，视频可能仍在生成中。`;
                }
            }
        } catch (error) {
            console.error("Polling error:", error);
        }
    }, 10000); // 每 10 秒轮询一次
}

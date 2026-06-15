/**
 * PracticeManager - 卡片式练习模式管理器
 * 管理题目导航、答案提交、状态更新
 */

class PracticeManager {
    constructor(options) {
        this.sessionId = options.sessionId;
        this.totalQuestions = options.totalQuestions;
        this.questions = options.questions;
        this.currentQuestionId = null;
        this.draftManagers = {};
        this.timerManagers = {};
        this.activeTimerId = null;  // 当前正在计时的题目ID
    }

    init() {
        // 初始化第一个未答题目
        const firstUnanswered = this.questions.find(q => !q.user_answer && q.status !== 'skipped');
        if (firstUnanswered) {
            this.navigateTo(firstUnanswered.id);
        } else if (this.questions.length > 0) {
            this.navigateTo(this.questions[0].id);
        }

        // 初始化草稿和计时器（传入已有用时）
        this.questions.forEach(q => {
            if (!q.user_answer) {
                this.draftManagers[q.id] = new DraftManager(this.sessionId, q.id);
                const existingTime = (q.time_spent && q.time_spent > 0) ? q.time_spent : 0;
                this.timerManagers[q.id] = new TimerManager(this.sessionId, q.id, existingTime);

                // 设置计时器 tick 回调，更新卡片头部计时徽章
                this.timerManagers[q.id].onTick((formatted) => {
                    this._updateTimerBadge(q.id, formatted);
                });

                const input = document.getElementById(`input-${q.id}`);
                if (input) {
                    input.addEventListener('input', () => {
                        this.draftManagers[q.id].autoSave(input.value);
                    });
                }
            }
        });

        this.updateProgress();
        this._initBookmarkStates();
    }

    /** 初始化收藏按钮的 data-bookmarked 属性 */
    _initBookmarkStates() {
        this.questions.forEach(q => {
            const card = document.getElementById(`card-${q.id}`);
            if (!card) return;
            const btn = card.querySelector('.btn-icon[onclick*="toggleBookmark"]');
            if (btn) {
                btn.setAttribute('data-bookmarked', q.is_bookmarked ? 'true' : 'false');
            }
        });
    }

    navigateTo(questionId) {
        // 暂停当前正在计时的计时器
        if (this.activeTimerId && this.activeTimerId !== questionId && this.timerManagers[this.activeTimerId]) {
            this.timerManagers[this.activeTimerId].pause();
        }

        // 隐藏所有卡片
        document.querySelectorAll('.question-card').forEach(card => {
            card.classList.remove('active');
        });

        // 显示目标卡片
        const targetCard = document.getElementById(`card-${questionId}`);
        if (targetCard) {
            targetCard.classList.add('active');
            this.currentQuestionId = questionId;

            // 更新导航状态
            document.querySelectorAll('.nav-item').forEach(item => {
                item.classList.remove('active');
            });
            const navItem = document.querySelector(`.nav-item[data-question-id="${questionId}"]`);
            if (navItem) {
                navItem.classList.add('active');
                // 展开父级追问组
                const parentGroup = navItem.closest('.followup-group');
                if (parentGroup) {
                    parentGroup.classList.add('expanded');
                }
            }

            // 启动计时器
            if (this.timerManagers[questionId]) {
                if (this.timerManagers[questionId].isPaused) {
                    this.timerManagers[questionId].resume();
                } else {
                    this.timerManagers[questionId].start();
                }
                this.activeTimerId = questionId;

                // 立即更新计时徽章显示
                const elapsed = this.timerManagers[questionId].getElapsedSeconds();
                const formatted = this.timerManagers[questionId].formatTime(elapsed);
                this._updateTimerBadge(questionId, formatted);
            } else {
                this.activeTimerId = null;
            }

            // 恢复草稿
            const input = document.getElementById(`input-${questionId}`);
            if (input && this.draftManagers[questionId]) {
                const draft = this.draftManagers[questionId].restoreDraft();
                if (draft) {
                    input.value = draft;
                }
            }
        }
    }

    /** 解析 SSE 流，支持跨 chunk 缓冲 */
    _parseSSEStream(reader, onToken, onDone, onError) {
        const decoder = new TextDecoder();
        let buffer = '';

        const processEvent = (eventBlock) => {
            const eventMatch = eventBlock.match(/event:\s*(\w+)\s*\ndata:\s*(.+)/s);
            if (!eventMatch) return;

            const [, event, data] = eventMatch;
            try {
                const parsed = JSON.parse(data);
                if (event === 'token') {
                    onToken(parsed.content);
                } else if (event === 'done') {
                    onDone(parsed);
                } else if (event === 'error') {
                    onError(parsed.content);
                }
            } catch (e) {
                console.error('SSE parse error:', e, data);
            }
        };

        return new Promise((resolve, reject) => {
            const pump = () => {
                reader.read().then(({ done, value }) => {
                    if (done) {
                        // 处理缓冲区中剩余的数据
                        if (buffer.trim()) {
                            const events = buffer.split('\n\n');
                            events.forEach(processEvent);
                        }
                        resolve();
                        return;
                    }

                    buffer += decoder.decode(value, { stream: true });
                    const parts = buffer.split('\n\n');
                    // 最后一个可能不完整，保留到下次
                    buffer = parts.pop() || '';

                    parts.forEach(processEvent);
                    pump();
                }).catch(reject);
            };
            pump();
        });
    }

    async submitAnswer(questionId) {
        const input = document.getElementById(`input-${questionId}`);
        if (!input || !input.value.trim()) {
            alert('请输入答案');
            return;
        }

        const answer = input.value.trim();
        const submitBtn = input.parentElement.querySelector('.btn-submit');
        const skipBtn = input.parentElement.querySelector('.btn-skip');
        submitBtn.disabled = true;
        submitBtn.textContent = '提交中...';
        if (skipBtn) skipBtn.disabled = true;

        try {
            // 停止计时器
            if (this.timerManagers[questionId]) {
                this.timerManagers[questionId].stop();
            }

            // 清除活跃计时器标记
            if (this.activeTimerId === questionId) {
                this.activeTimerId = null;
            }

            // 使用友好格式的用时信息
            const timeSpent = this.timerManagers[questionId]
                ? this.timerManagers[questionId].getElapsedSeconds()
                : 0;
            const friendlyTime = TimerManager.formatTimeFriendly(timeSpent);

            const response = await fetch(`/api/sessions/${this.sessionId}/answer/stream`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_answer: answer })
            });

            if (!response.ok) throw new Error('提交失败');

            // 先更新卡片为"答案 + 流式反馈"状态
            this._showStreamingCard(questionId, answer);

            const reader = response.body.getReader();
            let feedbackText = '';
            let score = null;
            let doneData = null;
            let errorContent = null;

            const feedbackEl = document.getElementById(`feedback-text-${questionId}`);
            const streamIndicator = document.getElementById(`stream-indicator-${questionId}`);

            await this._parseSSEStream(
                reader,
                // onToken - 实时更新反馈文本
                (content) => {
                    feedbackText += content;
                    if (feedbackEl) {
                        feedbackEl.textContent = feedbackText;
                        // 自动滚动到底部
                        feedbackEl.scrollTop = feedbackEl.scrollHeight;
                    }
                },
                // onDone
                (parsed) => {
                    doneData = parsed;
                    feedbackText = parsed.content;
                    score = parsed.score;
                },
                // onError
                (content) => {
                    errorContent = content;
                }
            );

            // 移除流式指示器
            if (streamIndicator) streamIndicator.remove();

            if (errorContent && !feedbackText) {
                throw new Error(errorContent);
            }

            // 最终更新卡片
            this._finalizeCard(questionId, answer, feedbackText, score, doneData);

            // 更新内部状态
            const q = this.questions.find(q => q.id === questionId);
            if (q) {
                q.user_answer = answer;
                q.ai_feedback = feedbackText;
                q.score = score;
            }

            // 清除草稿
            if (this.draftManagers[questionId]) {
                this.draftManagers[questionId].clearDraft();
            }

            // 更新进度
            this.updateProgress();

            // 检查是否有追问
            if (doneData && doneData.followup) {
                this._handleFollowup(questionId, doneData.followup);
            }

            // 显示"下一题"按钮
            this._showNextButton(questionId);

        } catch (error) {
            console.error('Submit error:', error);
            alert('提交失败，请重试');
            // 恢复输入状态
            this._restoreInputCard(questionId, answer);
            submitBtn.disabled = false;
            submitBtn.textContent = '提交答案';
            if (skipBtn) skipBtn.disabled = false;
        }
    }

    /** 显示流式反馈的卡片状态 */
    _showStreamingCard(questionId, answer) {
        const card = document.getElementById(`card-${questionId}`);
        if (!card) return;

        // 获取提交时的用时（已 stop）
        const timeSpent = this.timerManagers[questionId]
            ? this.timerManagers[questionId].getElapsedSeconds()
            : 0;
        const friendlyTime = TimerManager.formatTimeFriendly(timeSpent);

        // 隐藏计时徽章（已停止计时）
        this._hideTimerBadge(questionId);

        const cardSection = card.querySelector('.card-section');
        cardSection.innerHTML = `
            <div class="section-header">
                <h3 class="section-title">我的答案</h3>
                ${friendlyTime ? `<span class="time-badge-static">⏱ ${friendlyTime}</span>` : ''}
            </div>
            <p class="answer-text" id="answer-${questionId}">${this.escapeHtml(answer)}</p>
        `;

        // 添加流式反馈区域
        const feedbackSection = document.createElement('div');
        feedbackSection.className = 'card-section feedback-section';
        feedbackSection.innerHTML = `
            <h3 class="section-title">AI 反馈 <span id="stream-indicator-${questionId}" class="stream-indicator">●●●</span></h3>
            <p class="feedback-text" id="feedback-text-${questionId}" style="max-height: 300px; overflow-y: auto;"></p>
        `;
        cardSection.parentElement.appendChild(feedbackSection);
    }

    /** 流式完成后最终更新卡片 */
    _finalizeCard(questionId, answer, feedback, score, doneData) {
        const card = document.getElementById(`card-${questionId}`);
        if (!card) return;

        // 获取最终用时
        const timeSpent = this.timerManagers[questionId]
            ? this.timerManagers[questionId].getElapsedSeconds()
            : 0;
        const friendlyTime = TimerManager.formatTimeFriendly(timeSpent);

        // 移除计时徽章
        this._hideTimerBadge(questionId);

        // 更新答案区域，添加编辑按钮，以及用时信息
        const cardSection = card.querySelector('.card-section');
        cardSection.innerHTML = `
            <div class="section-header">
                <h3 class="section-title">我的答案</h3>
                <button class="btn-edit" onclick="practiceManager.editAnswer(${questionId})">
                    <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/></svg>
                    编辑
                </button>
            </div>
            <p class="answer-text" id="answer-${questionId}">${this.escapeHtml(answer)}</p>
            ${friendlyTime ? `<p class="time-info">⏱️ 用时 ${friendlyTime}</p>` : ''}
        `;

        // 更新反馈文本
        const feedbackEl = document.getElementById(`feedback-text-${questionId}`);
        if (feedbackEl && feedback) {
            feedbackEl.textContent = feedback;
        }

        // 更新分数
        if (score !== null && score !== undefined) {
            const headerLeft = card.querySelector('.card-header-left');
            let scoreBadge = headerLeft.querySelector('.score-badge');
            if (!scoreBadge) {
                scoreBadge = document.createElement('span');
                scoreBadge.className = 'score-badge';
                headerLeft.appendChild(scoreBadge);
            }
            scoreBadge.textContent = `${score}分`;
            // 根据分数设置颜色
            if (score >= 80) {
                scoreBadge.style.background = '#d1fae5';
                scoreBadge.style.color = '#065f46';
            } else if (score >= 60) {
                scoreBadge.style.background = '#fef3c7';
                scoreBadge.style.color = '#92400e';
            } else {
                scoreBadge.style.background = '#fee2e2';
                scoreBadge.style.color = '#991b1b';
            }
        }

        // 更新导航状态
        const navItem = document.querySelector(`.nav-item[data-question-id="${questionId}"]`);
        if (navItem) {
            navItem.classList.remove('unanswered');
            navItem.classList.add('answered');
            navItem.querySelector('.nav-status').textContent = '✓';
        }

        // Remove any previous next-question-bar to avoid duplicates on edit
        const existingNext = card.querySelector('.next-question-bar');
        if (existingNext) existingNext.remove();
    }

    /** 显示"下一题"按钮，让用户有时间阅读反馈 */
    _showNextButton(questionId) {
        const card = document.getElementById(`card-${questionId}`);
        if (!card) return;

        // Check if there's a next unanswered question
        const currentIndex = this.questions.findIndex(q => q.id === questionId);
        let hasNext = false;
        for (let i = currentIndex + 1; i < this.questions.length; i++) {
            if (!this.questions[i].user_answer && this.questions[i].status !== 'skipped') {
                hasNext = true;
                break;
            }
        }

        if (!hasNext) {
            // All questions answered - show completion button
            const nextBtn = document.createElement('div');
            nextBtn.className = 'next-question-bar';
            nextBtn.innerHTML = `
                <button class="btn-next-question" onclick="practiceManager.completeSession()">
                    所有题目已完成 — 结束面试
                </button>
            `;
            const cardSection = card.querySelector('.card-section');
            if (cardSection) {
                cardSection.parentElement.insertBefore(nextBtn, cardSection.nextSibling);
            }
            return;
        }

        const nextBtn = document.createElement('div');
        nextBtn.className = 'next-question-bar';
        nextBtn.innerHTML = `
            <button class="btn-next-question" onclick="practiceManager.navigateNext(); this.closest('.next-question-bar').remove();">
                下一题 ▶
            </button>
        `;
        const cardSection = card.querySelector('.card-section:last-child');
        if (cardSection) {
            cardSection.parentElement.appendChild(nextBtn);
        } else {
            card.appendChild(nextBtn);
        }
    }

    /** 提交失败时恢复输入状态 */
    _restoreInputCard(questionId, answer) {
        const card = document.getElementById(`card-${questionId}`);
        if (!card) return;

        // 移除可能存在的反馈区域
        const feedbackSection = card.querySelector('.feedback-section');
        if (feedbackSection) feedbackSection.remove();

        // 恢复输入区域
        const cardSection = card.querySelector('.card-section');
        cardSection.innerHTML = `
            <h3 class="section-title">我的答案</h3>
            <textarea class="answer-input" id="input-${questionId}" placeholder="请输入您的答案..." rows="6">${this.escapeHtml(answer)}</textarea>
            <div class="input-actions">
                <button class="btn-submit" onclick="practiceManager.submitAnswer(${questionId})">提交答案</button>
                <button class="btn-skip" onclick="practiceManager.skipQuestion(${questionId})">跳过</button>
            </div>
        `;
    }

    /** 处理追问：添加到侧边栏和卡片 */
    _handleFollowup(parentQuestionId, followup) {
        const followupId = followup.id || `followup-${Date.now()}`;

        // 更新侧边栏：在父题目后添加追问项
        const parentNavItem = document.querySelector(`.nav-item[data-question-id="${parentQuestionId}"]`);
        if (parentNavItem) {
            // 确保父级有追问组容器
            let followupGroup = parentNavItem.nextElementSibling;
            if (!followupGroup || !followupGroup.classList.contains('followup-group')) {
                followupGroup = document.createElement('div');
                followupGroup.className = 'followup-group';
                parentNavItem.parentNode.insertBefore(followupGroup, parentNavItem.nextSibling);
            }

            const followupNavItem = document.createElement('button');
            followupNavItem.className = 'nav-item followup-nav-item unanswered';
            followupNavItem.setAttribute('data-question-id', followupId);
            followupNavItem.setAttribute('data-is-followup', 'true');
            followupNavItem.onclick = () => this.navigateTo(followupId);
            followupNavItem.innerHTML = `
                <span class="nav-number">↳ 追问</span>
                <span class="nav-status">•</span>
            `;
            followupGroup.appendChild(followupNavItem);
            followupGroup.classList.add('expanded');
        }

        // 添加追问卡片
        const cardsContainer = document.getElementById('cards-container');
        if (cardsContainer) {
            const followupCard = document.createElement('div');
            followupCard.className = 'question-card';
            followupCard.id = `card-${followupId}`;
            followupCard.setAttribute('data-question-id', followupId);
            followupCard.innerHTML = `
                <div class="card-header">
                    <div class="card-header-left">
                        <span class="question-number">追问</span>
                    </div>
                </div>
                <div class="card-section">
                    <h3 class="section-title">题目</h3>
                    <p class="question-text">${this.escapeHtml(followup.question_text)}</p>
                </div>
                <div class="card-section">
                    <h3 class="section-title">我的答案</h3>
                    <textarea class="answer-input" id="input-${followupId}" placeholder="请输入您的答案..." rows="6"></textarea>
                    <div class="input-actions">
                        <button class="btn-submit" onclick="practiceManager.submitAnswer(${followupId})">提交答案</button>
                        <button class="btn-skip" onclick="practiceManager.skipQuestion(${followupId})">跳过</button>
                    </div>
                </div>
            `;
            cardsContainer.appendChild(followupCard);

            // 更新内部状态
            this.questions.push({
                id: followupId,
                question_text: followup.question_text,
                user_answer: null,
                status: 'unanswered',
                is_followup: true,
                parent_question_id: parentQuestionId
            });

            // 初始化草稿和计时器
            this.draftManagers[followupId] = new DraftManager(this.sessionId, followupId);
            this.timerManagers[followupId] = new TimerManager(this.sessionId, followupId);

            // 设置计时器回调
            this.timerManagers[followupId].onTick((formatted) => {
                this._updateTimerBadge(followupId, formatted);
            });

            const input = document.getElementById(`input-${followupId}`);
            if (input) {
                input.addEventListener('input', () => {
                    this.draftManagers[followupId].autoSave(input.value);
                });
            }

            this.totalQuestions++;
            this.updateProgress();
        }
    }

    async skipQuestion(questionId) {
        if (!confirm('确定跳过此题？')) return;

        try {
            const response = await fetch(`/api/sessions/${this.sessionId}/skip`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });

            if (!response.ok) throw new Error('跳过失败');

            // 更新导航状态
            const navItem = document.querySelector(`.nav-item[data-question-id="${questionId}"]`);
            if (navItem) {
                navItem.classList.remove('unanswered');
                navItem.classList.add('skipped');
                navItem.querySelector('.nav-status').textContent = '⊗';
            }

            // 清除草稿和计时器
            if (this.draftManagers[questionId]) {
                this.draftManagers[questionId].clearDraft();
            }
            if (this.timerManagers[questionId]) {
                this.timerManagers[questionId].stop();
            }

            // 清除活跃计时器标记和计时徽章
            if (this.activeTimerId === questionId) {
                this.activeTimerId = null;
            }
            this._hideTimerBadge(questionId);

            this.updateProgress();
            this.navigateNext();

        } catch (error) {
            console.error('Skip error:', error);
            alert('跳过失败，请重试');
        }
    }

    async editAnswer(questionId) {
        const answerEl = document.getElementById(`answer-${questionId}`);
        if (!answerEl) return;

        const currentAnswer = answerEl.textContent;
        const newAnswer = prompt('编辑答案：', currentAnswer);

        if (!newAnswer || newAnswer === currentAnswer) return;

        try {
            const response = await fetch(`/api/sessions/${this.sessionId}/questions/${questionId}/answer`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_answer: newAnswer })
            });

            if (!response.ok) throw new Error('更新失败');

            // 处理SSE流
            const reader = response.body.getReader();
            let feedbackText = '';
            let score = null;
            let previousScore = null;
            let editCount = null;
            let doneData = null;

            // 更新反馈区域为流式状态
            const card = document.getElementById(`card-${questionId}`);
            const feedbackSection = card.querySelector('.feedback-section .feedback-text');
            if (feedbackSection) {
                feedbackSection.textContent = '';
            }

            const streamIndicator = document.createElement('span');
            streamIndicator.className = 'stream-indicator';
            streamIndicator.textContent = '●●●';
            const sectionTitle = card.querySelector('.feedback-section .section-title');
            if (sectionTitle) sectionTitle.appendChild(streamIndicator);

            await this._parseSSEStream(
                reader,
                (content) => {
                    feedbackText += content;
                    if (feedbackSection) {
                        feedbackSection.textContent = feedbackText;
                    }
                },
                (parsed) => {
                    doneData = parsed;
                    feedbackText = parsed.content;
                    score = parsed.score;
                    if (parsed.previous_score !== undefined) previousScore = parsed.previous_score;
                    if (parsed.edit_count !== undefined) editCount = parsed.edit_count;
                },
                (content) => {
                    console.error('Edit stream error:', content);
                }
            );

            // 移除流式指示器
            streamIndicator.remove();

            // 更新答案显示
            answerEl.textContent = newAnswer;

            // 更新反馈
            if (feedbackSection && feedbackText) {
                feedbackSection.textContent = feedbackText;
            }

            // 更新分数
            if (score !== null) {
                const scoreBadge = card.querySelector('.score-badge');
                if (scoreBadge) {
                    scoreBadge.textContent = `${score}分`;
                    if (score >= 80) {
                        scoreBadge.style.background = '#d1fae5';
                        scoreBadge.style.color = '#065f46';
                    } else if (score >= 60) {
                        scoreBadge.style.background = '#fef3c7';
                        scoreBadge.style.color = '#92400e';
                    } else {
                        scoreBadge.style.background = '#fee2e2';
                        scoreBadge.style.color = '#991b1b';
                    }
                }

                // 更新或添加编辑信息
                let editInfo = card.querySelector('.edit-info');
                if (!editInfo) {
                    editInfo = document.createElement('p');
                    editInfo.className = 'edit-info';
                    answerEl.parentElement.appendChild(editInfo);
                }

                const editCountText = editCount ? `已修改 ${editCount} 次` : '已修改 1 次';
                const scoreChange = (previousScore !== null && previousScore !== undefined)
                    ? ` | ${previousScore}→${score}`
                    : '';
                editInfo.textContent = `📝 ${editCountText}${scoreChange}`;
            }

        } catch (error) {
            console.error('Edit error:', error);
            alert('更新失败，请重试');
        }
    }

    async toggleBookmark(questionId) {
        try {
            const card = document.getElementById(`card-${questionId}`);
            const btn = card.querySelector('.btn-icon[onclick*="toggleBookmark"]');
            if (!btn) {
                console.error('Bookmark button not found for question:', questionId);
                return;
            }
            const svg = btn.querySelector('svg');

            // 使用 data-bookmarked 属性判断状态，更可靠
            const isCurrentlyBookmarked = btn.getAttribute('data-bookmarked') === 'true';
            const newState = !isCurrentlyBookmarked;

            const response = await fetch(`/api/sessions/${this.sessionId}/questions/${questionId}/bookmark`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bookmarked: newState })
            });

            if (!response.ok) throw new Error('操作失败');

            const result = await response.json();

            // 更新UI - 使用 data 属性跟踪状态
            // API 返回的是 is_bookmarked 字段
            const isNowBookmarked = result.is_bookmarked === true || result.is_bookmarked === 1;
            btn.setAttribute('data-bookmarked', isNowBookmarked ? 'true' : 'false');

            // Keep internal state in sync
            const q = this.questions.find(q => q.id === questionId);
            if (q) {
                q.is_bookmarked = isNowBookmarked;
            }

            if (isNowBookmarked) {
                btn.classList.add('active');
                btn.title = '取消收藏';
                // 使用完整的 SVG 替换以确保属性一致
                svg.innerHTML = '<path d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/>';
                svg.setAttribute('fill', 'currentColor');
                svg.removeAttribute('stroke');
                // 确保 path 上也没有 stroke 属性
                const path = svg.querySelector('path');
                if (path) {
                    path.removeAttribute('stroke');
                    path.removeAttribute('stroke-width');
                    path.removeAttribute('stroke-linecap');
                    path.removeAttribute('stroke-linejoin');
                }
            } else {
                btn.classList.remove('active');
                btn.title = '收藏';
                svg.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/>';
                svg.setAttribute('fill', 'none');
                svg.setAttribute('stroke', 'currentColor');
            }

        } catch (error) {
            console.error('Bookmark error:', error);
        }
    }

    navigateNext() {
        const currentIndex = this.questions.findIndex(q => q.id === this.currentQuestionId);
        if (currentIndex < 0) return;

        // 找到下一个未答题
        for (let i = currentIndex + 1; i < this.questions.length; i++) {
            const q = this.questions[i];
            if (!q.user_answer && q.status !== 'skipped') {
                this.navigateTo(q.id);
                return;
            }
        }

        // 如果没有未答题，检查是否全部完成
        const allAnswered = this.questions.every(q => q.user_answer || q.status === 'skipped');
        if (allAnswered) {
            if (confirm('所有题目已完成，是否结束面试？')) {
                this.completeSession();
            }
        }
    }

    async completeSession() {
        if (!confirm('确定结束面试？')) return;

        try {
            const response = await fetch(`/api/sessions/${this.sessionId}/complete`, {
                method: 'POST'
            });

            if (!response.ok) throw new Error('结束失败');

            window.location.href = `/sessions/${this.sessionId}/review`;

        } catch (error) {
            console.error('Complete error:', error);
            alert('结束失败，请重试');
        }
    }

    updateProgress() {
        const answered = this.questions.filter(q => q.user_answer).length;
        const percentage = Math.round((answered / this.totalQuestions) * 100);

        const progressBar = document.getElementById('sidebar-progress');
        const progressText = document.getElementById('sidebar-progress-text');

        if (progressBar) progressBar.style.width = `${percentage}%`;
        if (progressText) progressText.textContent = `${answered} / ${this.totalQuestions}`;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /** 更新卡片头部的计时徽章 */
    _updateTimerBadge(questionId, formatted) {
        const card = document.getElementById(`card-${questionId}`);
        if (!card) return;

        // 优先使用模板中预创建的 timer-badge 元素
        let badge = card.querySelector(`#timer-badge-${questionId}`) || card.querySelector('.timer-badge');
        if (!badge) {
            // 追问卡片等动态创建的情况：创建计时徽章并插入到卡片头部
            const headerLeft = card.querySelector('.card-header-left');
            if (!headerLeft) return;
            badge = document.createElement('span');
            badge.className = 'timer-badge';
            headerLeft.appendChild(badge);
        }

        // 更新显示
        badge.textContent = `⏱ ${formatted}`;
        badge.style.display = 'inline-flex';
    }

    /** 隐藏计时徽章（答题完成后） */
    _hideTimerBadge(questionId) {
        const card = document.getElementById(`card-${questionId}`);
        if (!card) return;
        const badge = card.querySelector('.timer-badge');
        if (badge) {
            badge.remove();
        }
    }
}

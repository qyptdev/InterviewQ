/**
 * DraftManager - 草稿自动保存管理器
 *
 * 功能：
 * - 自动保存草稿（防抖 3 秒）
 * - LocalStorage 本地持久化
 * - 页面加载时恢复草稿
 * - 网络中断时缓存到本地
 * - 提交成功后清空草稿
 */

class DraftManager {
  constructor(sessionId, questionId) {
    this.sessionId = sessionId;
    this.questionId = questionId;
    this.saveTimer = null;
    this.SAVE_DELAY = 3000; // 3秒防抖
    this.localStorageKey = `draft_${sessionId}_${questionId}`;
    this.lastSavedContent = '';
    this.statusCallback = null; // 状态回调函数
  }

  /**
   * 设置状态更新回调
   */
  onStatusChange(callback) {
    this.statusCallback = callback;
  }

  /**
   * 更新状态显示
   */
  updateStatus(message, type = 'info') {
    if (this.statusCallback) {
      this.statusCallback(message, type);
    }
  }

  /**
   * 自动保存（防抖）
   */
  autoSave(content) {
    // 内容未变化，不需要保存
    if (content === this.lastSavedContent) {
      return;
    }

    // 清除之前的定时器
    if (this.saveTimer) {
      clearTimeout(this.saveTimer);
    }

    // 设置新的定时器
    this.saveTimer = setTimeout(() => {
      this.saveDraft(content);
    }, this.SAVE_DELAY);

    // 显示"正在编辑"状态
    this.updateStatus('正在编辑...', 'editing');
  }

  /**
   * 保存草稿到服务器和本地
   */
  async saveDraft(content) {
    // 1. 立即保存到 LocalStorage（即使网络失败也能保留）
    this.saveToLocal(content);
    this.lastSavedContent = content;

    // 2. 尝试保存到服务器
    try {
      const response = await fetch(
        `/api/sessions/${this.sessionId}/questions/${this.questionId}/draft`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ draft_text: content }),
        }
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      this.updateStatus('草稿已保存', 'success');

      // 3秒后隐藏状态
      setTimeout(() => {
        this.updateStatus('', 'hidden');
      }, 3000);
    } catch (err) {
      console.log('Draft saved locally, will sync when online:', err);
      this.updateStatus('离线保存（待同步）', 'offline');
    }
  }

  /**
   * 保存到 LocalStorage
   */
  saveToLocal(content) {
    try {
      const draftData = {
        content: content,
        timestamp: Date.now(),
        sessionId: this.sessionId,
        questionId: this.questionId,
      };
      localStorage.setItem(this.localStorageKey, JSON.stringify(draftData));
    } catch (err) {
      console.error('Failed to save to localStorage:', err);
    }
  }

  /**
   * 从 LocalStorage 恢复草稿
   */
  restoreDraft() {
    try {
      const draftDataStr = localStorage.getItem(this.localStorageKey);
      if (!draftDataStr) {
        return null;
      }

      const draftData = JSON.parse(draftDataStr);

      // 检查草稿是否过期（24小时）
      const ageMs = Date.now() - draftData.timestamp;
      const MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24小时

      if (ageMs > MAX_AGE_MS) {
        this.clearDraft();
        return null;
      }

      this.lastSavedContent = draftData.content;
      return draftData.content;
    } catch (err) {
      console.error('Failed to restore draft:', err);
      return null;
    }
  }

  /**
   * 清空草稿
   */
  clearDraft() {
    try {
      localStorage.removeItem(this.localStorageKey);
      this.lastSavedContent = '';
      this.updateStatus('', 'hidden');
    } catch (err) {
      console.error('Failed to clear draft:', err);
    }
  }

  /**
   * 取消自动保存定时器
   */
  cancelAutoSave() {
    if (this.saveTimer) {
      clearTimeout(this.saveTimer);
      this.saveTimer = null;
    }
  }

  /**
   * 立即强制保存
   */
  forceSave(content) {
    this.cancelAutoSave();
    return this.saveDraft(content);
  }

  /**
   * 获取所有草稿列表（用于跨会话管理）
   */
  static getAllDrafts() {
    const drafts = [];
    const prefix = 'draft_';

    try {
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && key.startsWith(prefix)) {
          const draftData = JSON.parse(localStorage.getItem(key));
          drafts.push({
            key: key,
            ...draftData,
          });
        }
      }
    } catch (err) {
      console.error('Failed to get all drafts:', err);
    }

    return drafts;
  }

  /**
   * 清理过期草稿（可定期调用）
   */
  static cleanupExpiredDrafts() {
    const drafts = DraftManager.getAllDrafts();
    const MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24小时
    const now = Date.now();

    drafts.forEach(draft => {
      const ageMs = now - draft.timestamp;
      if (ageMs > MAX_AGE_MS) {
        localStorage.removeItem(draft.key);
        console.log(`Cleaned up expired draft: ${draft.key}`);
      }
    });
  }
}

// 导出到全局（兼容无模块化环境）
if (typeof window !== 'undefined') {
  window.DraftManager = DraftManager;
}

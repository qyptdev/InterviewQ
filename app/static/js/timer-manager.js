/**
 * TimerManager - 答题计时器管理器
 *
 * 功能：
 * - 题目计时（精确计时）
 * - 暂停/恢复计时
 * - 自动上报用时
 * - 格式化显示
 */

class TimerManager {
  constructor(sessionId, questionId, initialSeconds = 0) {
    this.sessionId = sessionId;
    this.questionId = questionId;
    this.startTime = null;
    this.pausedTime = null;
    this.elapsedSeconds = initialSeconds;
    this.isRunning = false;
    this.isPaused = false;
    this.timerInterval = null;
    this.displayCallback = null;
    this.autoReportInterval = 30000; // 每30秒自动上报一次
    this.lastReportTime = 0;
  }

  /**
   * 设置显示回调函数
   */
  onTick(callback) {
    this.displayCallback = callback;
  }

  /**
   * 开始计时
   */
  start() {
    if (this.isRunning) {
      return;
    }

    this.isRunning = true;
    this.isPaused = false;
    this.startTime = performance.now() - (this.elapsedSeconds * 1000);

    // 启动定时器（每秒更新）
    this.timerInterval = setInterval(() => {
      this.tick();
    }, 1000);

    console.log('Timer started');
  }

  /**
   * 暂停计时
   */
  pause() {
    if (!this.isRunning || this.isPaused) {
      return;
    }

    this.isPaused = true;
    this.pausedTime = performance.now();

    // 清除定时器
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
      this.timerInterval = null;
    }

    // 计算已经过的时间
    this.elapsedSeconds = Math.floor((this.pausedTime - this.startTime) / 1000);

    console.log('Timer paused at', this.elapsedSeconds, 'seconds');
  }

  /**
   * 恢复计时
   */
  resume() {
    if (!this.isRunning || !this.isPaused) {
      return;
    }

    this.isPaused = false;
    this.startTime = performance.now() - (this.elapsedSeconds * 1000);
    this.pausedTime = null;

    // 重新启动定时器
    this.timerInterval = setInterval(() => {
      this.tick();
    }, 1000);

    console.log('Timer resumed from', this.elapsedSeconds, 'seconds');
  }

  /**
   * 停止计时
   */
  stop() {
    if (!this.isRunning) {
      return;
    }

    this.isRunning = false;
    this.isPaused = false;

    // 清除定时器
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
      this.timerInterval = null;
    }

    // 计算最终时间
    if (this.pausedTime) {
      this.elapsedSeconds = Math.floor((this.pausedTime - this.startTime) / 1000);
    } else {
      const now = performance.now();
      this.elapsedSeconds = Math.floor((now - this.startTime) / 1000);
    }

    console.log('Timer stopped at', this.elapsedSeconds, 'seconds');

    // 最终上报
    this.reportTime();
  }

  /**
   * 重置计时器
   */
  reset() {
    this.stop();
    this.elapsedSeconds = 0;
    this.startTime = null;
    this.pausedTime = null;

    if (this.displayCallback) {
      this.displayCallback(this.formatTime(0));
    }

    console.log('Timer reset');
  }

  /**
   * 计时器 tick（每秒调用）
   */
  tick() {
    if (this.isPaused) {
      return;
    }

    const now = performance.now();
    this.elapsedSeconds = Math.floor((now - this.startTime) / 1000);

    // 更新显示
    if (this.displayCallback) {
      this.displayCallback(this.formatTime(this.elapsedSeconds));
    }

    // 定期自动上报
    const timeSinceLastReport = now - this.lastReportTime;
    if (timeSinceLastReport >= this.autoReportInterval) {
      this.reportTime();
      this.lastReportTime = now;
    }
  }

  /**
   * 格式化时间显示（HH:MM:SS 或 MM:SS）
   */
  formatTime(seconds) {
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    if (hrs > 0) {
      return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    } else {
      return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    }
  }

  /**
   * 格式化时间为友好阅读格式（如 "2m 30s", "1h 5m 0s"）
   * 用于已答题目的用时展示（非实时计时）
   */
  static formatTimeFriendly(seconds) {
    if (!seconds || seconds <= 0) return '';
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    if (hrs > 0) {
      return `${hrs}h ${mins}m ${secs}s`;
    } else if (mins > 0) {
      return `${mins}m ${secs}s`;
    } else {
      return `${secs}s`;
    }
  }

  /**
   * 获取当前已用时间（秒）
   */
  getElapsedSeconds() {
    if (!this.isRunning) {
      return this.elapsedSeconds;
    }

    if (this.isPaused) {
      return Math.floor((this.pausedTime - this.startTime) / 1000);
    }

    const now = performance.now();
    return Math.floor((now - this.startTime) / 1000);
  }

  /**
   * 上报时间到服务器
   */
  async reportTime() {
    if (!this.sessionId || !this.questionId) {
      return;
    }

    const timeSpent = this.getElapsedSeconds();

    try {
      const response = await fetch(
        `/api/sessions/${this.sessionId}/questions/${this.questionId}/time`,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ time_spent: timeSpent }),
        }
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      console.log(`Time reported: ${timeSpent} seconds`);
    } catch (err) {
      console.error('Failed to report time:', err);
    }
  }

  /**
   * 获取状态
   */
  getStatus() {
    return {
      isRunning: this.isRunning,
      isPaused: this.isPaused,
      elapsedSeconds: this.getElapsedSeconds(),
      formatted: this.formatTime(this.getElapsedSeconds()),
    };
  }

  /**
   * 手动强制上报
   */
  forceReport() {
    return this.reportTime();
  }
}

// 导出到全局
if (typeof window !== 'undefined') {
  window.TimerManager = TimerManager;
}

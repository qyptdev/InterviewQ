/**
 * NetworkManager - 网络状态管理器
 *
 * 功能：
 * - 监测网络状态
 * - 断线重连机制（指数退避）
 * - 离线队列管理
 * - 网络状态 UI 提示
 */

class NetworkManager {
  constructor() {
    this.isOnline = navigator.onLine;
    this.retryQueue = [];
    this.maxRetries = 3;
    this.listeners = [];
    this.toastContainer = null;

    // 监听网络状态
    window.addEventListener('online', () => this.handleOnline());
    window.addEventListener('offline', () => this.handleOffline());

    // 初始化 Toast 容器
    this.initToastContainer();
  }

  /**
   * 初始化 Toast 通知容器
   */
  initToastContainer() {
    // Wait for DOM to be ready
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => this._createToastContainer());
    } else {
      this._createToastContainer();
    }
  }

  _createToastContainer() {
    if (!document.getElementById('toast-container')) {
      const container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'fixed bottom-4 right-4 z-50 space-y-2';
      if (document.body) {
        document.body.appendChild(container);
        this.toastContainer = container;
      }
    } else {
      this.toastContainer = document.getElementById('toast-container');
    }
  }

  /**
   * 添加网络状态监听器
   */
  addListener(callback) {
    this.listeners.push(callback);
  }

  /**
   * 移除网络状态监听器
   */
  removeListener(callback) {
    this.listeners = this.listeners.filter(cb => cb !== callback);
  }

  /**
   * 通知所有监听器
   */
  notifyListeners(status) {
    this.listeners.forEach(callback => {
      try {
        callback(status);
      } catch (err) {
        console.error('Error in network listener:', err);
      }
    });
  }

  /**
   * 显示 Toast 通知
   */
  showToast(message, type = 'info', duration = 3000) {
    const toast = document.createElement('div');
    toast.className = `
      px-4 py-3 rounded-lg shadow-lg text-sm font-medium
      transform transition-all duration-300 ease-out
      ${type === 'success' ? 'bg-green-600 text-white' : ''}
      ${type === 'error' ? 'bg-red-600 text-white' : ''}
      ${type === 'warning' ? 'bg-yellow-500 text-gray-900' : ''}
      ${type === 'info' ? 'bg-blue-600 text-white' : ''}
    `;
    toast.textContent = message;

    this.toastContainer.appendChild(toast);

    // 淡入动画
    setTimeout(() => {
      toast.style.opacity = '1';
      toast.style.transform = 'translateX(0)';
    }, 10);

    // 自动移除
    if (duration > 0) {
      setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(400px)';
        setTimeout(() => {
          if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
          }
        }, 300);
      }, duration);
    }

    return toast;
  }

  /**
   * 显示离线提示
   */
  showOfflineToast() {
    this.showToast('网络已断开，数据将在恢复后同步', 'warning', 0);
  }

  /**
   * 显示在线提示
   */
  showOnlineToast() {
    // 先移除所有 toast
    while (this.toastContainer.firstChild) {
      this.toastContainer.removeChild(this.toastContainer.firstChild);
    }
    this.showToast('网络已恢复，正在同步数据...', 'success', 3000);
  }

  /**
   * 睡眠函数（用于重试延迟）
   */
  sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * 带重试的 fetch
   */
  async fetchWithRetry(url, options = {}, retries = 0) {
    try {
      const response = await fetch(url, options);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      return response;
    } catch (err) {
      // 如果是网络错误且未达到最大重试次数
      if (retries < this.maxRetries) {
        const delay = Math.pow(2, retries) * 1000; // 指数退避：1s, 2s, 4s
        console.log(`Request failed, retrying in ${delay}ms... (attempt ${retries + 1}/${this.maxRetries})`);

        await this.sleep(delay);
        return this.fetchWithRetry(url, options, retries + 1);
      }

      // 达到最大重试次数，抛出错误
      throw err;
    }
  }

  /**
   * 离线时加入队列
   */
  queueRequest(url, options) {
    this.retryQueue.push({ url, options, timestamp: Date.now() });
    console.log(`Request queued (offline): ${url}`);

    if (this.retryQueue.length === 1) {
      this.showOfflineToast();
    }
  }

  /**
   * 智能 fetch（自动处理离线和重试）
   */
  async smartFetch(url, options = {}) {
    // 如果离线，加入队列
    if (!this.isOnline) {
      this.queueRequest(url, options);
      throw new Error('Network offline, request queued');
    }

    // 在线，尝试请求（带重试）
    try {
      return await this.fetchWithRetry(url, options);
    } catch (err) {
      // 如果重试失败，加入队列
      this.queueRequest(url, options);
      throw err;
    }
  }

  /**
   * 处理离线事件
   */
  handleOffline() {
    console.log('Network went offline');
    this.isOnline = false;
    this.notifyListeners({ online: false });
    this.showOfflineToast();
  }

  /**
   * 处理在线事件
   */
  async handleOnline() {
    console.log('Network back online');
    this.isOnline = true;
    this.notifyListeners({ online: true });
    this.showOnlineToast();

    // 处理队列中的请求
    await this.processQueue();
  }

  /**
   * 处理离线队列
   */
  async processQueue() {
    if (this.retryQueue.length === 0) {
      return;
    }

    console.log(`Processing ${this.retryQueue.length} queued requests...`);

    const queue = [...this.retryQueue];
    this.retryQueue = [];

    for (const { url, options } of queue) {
      try {
        await this.fetchWithRetry(url, options);
        console.log(`Successfully synced: ${url}`);
      } catch (err) {
        console.error(`Failed to sync: ${url}`, err);
        // 同步失败，重新加入队列
        this.retryQueue.push({ url, options, timestamp: Date.now() });
      }
    }

    if (this.retryQueue.length > 0) {
      this.showToast(`${this.retryQueue.length} 个请求同步失败，将稍后重试`, 'warning', 5000);
    } else {
      this.showToast('所有数据已同步', 'success', 3000);
    }
  }

  /**
   * 清理过期队列（超过1小时的请求）
   */
  cleanupQueue() {
    const MAX_AGE_MS = 60 * 60 * 1000; // 1小时
    const now = Date.now();

    this.retryQueue = this.retryQueue.filter(item => {
      return (now - item.timestamp) < MAX_AGE_MS;
    });
  }

  /**
   * 获取队列状态
   */
  getQueueStatus() {
    return {
      isOnline: this.isOnline,
      queueLength: this.retryQueue.length,
      oldestTimestamp: this.retryQueue.length > 0
        ? Math.min(...this.retryQueue.map(item => item.timestamp))
        : null
    };
  }

  /**
   * 手动重试队列
   */
  async retryQueue() {
    if (!this.isOnline) {
      this.showToast('网络未连接，无法重试', 'error', 3000);
      return;
    }
    await this.processQueue();
  }
}

// 创建全局单例
if (typeof window !== 'undefined') {
  window.NetworkManager = NetworkManager;
  window.networkManager = new NetworkManager();
}

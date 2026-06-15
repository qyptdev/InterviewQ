/**
 * ChartComponents - 图表可视化组件（基于 Chart.js）
 *
 * 功能：
 * - 初始化 Chart.js
 * - 创建分数趋势图（折线图）
 * - 创建分类表现雷达图
 * - 创建分数分布饼图
 * - 创建环形进度图
 * - 响应式配置
 */

class ChartComponents {
  constructor() {
    this.charts = {};
    this.defaultColors = {
      primary: 'rgb(34, 197, 94)',      // green-500
      secondary: 'rgb(59, 130, 246)',   // blue-500
      warning: 'rgb(245, 158, 11)',     // amber-500
      danger: 'rgb(239, 68, 68)',       // red-500
      info: 'rgb(14, 165, 233)',        // sky-500
      purple: 'rgb(168, 85, 247)',      // purple-500
    };
  }

  /**
   * 检查 Chart.js 是否已加载
   */
  checkChartJS() {
    if (typeof Chart === 'undefined') {
      console.error('Chart.js is not loaded. Please include Chart.js before using ChartComponents.');
      return false;
    }
    return true;
  }

  /**
   * 销毁现有图表（避免内存泄漏）
   */
  destroyChart(chartId) {
    if (this.charts[chartId]) {
      this.charts[chartId].destroy();
      delete this.charts[chartId];
    }
  }

  /**
   * 创建折线图 - 分数趋势
   * @param {string} canvasId - Canvas 元素 ID
   * @param {object} data - 数据对象 {labels: [], scores: []}
   * @param {object} options - 可选配置
   */
  createTrendChart(canvasId, data, options = {}) {
    if (!this.checkChartJS()) return null;

    const canvas = document.getElementById(canvasId);
    if (!canvas) {
      console.error(`Canvas element #${canvasId} not found`);
      return null;
    }

    this.destroyChart(canvasId);

    const ctx = canvas.getContext('2d');
    this.charts[canvasId] = new Chart(ctx, {
      type: 'line',
      data: {
        labels: data.labels || [],
        datasets: [{
          label: options.label || '答题分数',
          data: data.scores || [],
          borderColor: this.defaultColors.primary,
          backgroundColor: 'rgba(34, 197, 94, 0.1)',
          borderWidth: 2,
          tension: 0.4,
          fill: true,
          pointRadius: 4,
          pointHoverRadius: 6,
          pointBackgroundColor: this.defaultColors.primary,
          pointBorderColor: '#fff',
          pointBorderWidth: 2,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: options.showLegend !== false,
            position: 'top',
          },
          tooltip: {
            mode: 'index',
            intersect: false,
            callbacks: {
              label: function(context) {
                return `分数: ${context.parsed.y}`;
              }
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            max: 100,
            ticks: {
              callback: function(value) {
                return value;
              }
            },
            grid: {
              color: 'rgba(0, 0, 0, 0.05)',
            }
          },
          x: {
            grid: {
              display: false,
            }
          }
        },
        interaction: {
          mode: 'nearest',
          axis: 'x',
          intersect: false
        }
      }
    });

    return this.charts[canvasId];
  }

  /**
   * 创建雷达图 - 分类表现
   * @param {string} canvasId - Canvas 元素 ID
   * @param {object} data - 数据对象 {categories: [], avgScores: []}
   * @param {object} options - 可选配置
   */
  createRadarChart(canvasId, data, options = {}) {
    if (!this.checkChartJS()) return null;

    const canvas = document.getElementById(canvasId);
    if (!canvas) {
      console.error(`Canvas element #${canvasId} not found`);
      return null;
    }

    this.destroyChart(canvasId);

    const ctx = canvas.getContext('2d');
    this.charts[canvasId] = new Chart(ctx, {
      type: 'radar',
      data: {
        labels: data.categories || [],
        datasets: [{
          label: options.label || '平均分',
          data: data.avgScores || [],
          borderColor: this.defaultColors.secondary,
          backgroundColor: 'rgba(59, 130, 246, 0.2)',
          borderWidth: 2,
          pointRadius: 3,
          pointHoverRadius: 5,
          pointBackgroundColor: this.defaultColors.secondary,
          pointBorderColor: '#fff',
          pointBorderWidth: 2,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: options.showLegend !== false,
            position: 'top',
          },
          tooltip: {
            callbacks: {
              label: function(context) {
                return `${context.label}: ${context.parsed.r}`;
              }
            }
          }
        },
        scales: {
          r: {
            beginAtZero: true,
            max: 100,
            ticks: {
              stepSize: 20,
              callback: function(value) {
                return value;
              }
            },
            grid: {
              color: 'rgba(0, 0, 0, 0.1)',
            },
            angleLines: {
              color: 'rgba(0, 0, 0, 0.1)',
            }
          }
        }
      }
    });

    return this.charts[canvasId];
  }

  /**
   * 创建饼图 - 分数分布
   * @param {string} canvasId - Canvas 元素 ID
   * @param {object} data - 数据对象 {labels: [], values: []}
   * @param {object} options - 可选配置
   */
  createPieChart(canvasId, data, options = {}) {
    if (!this.checkChartJS()) return null;

    const canvas = document.getElementById(canvasId);
    if (!canvas) {
      console.error(`Canvas element #${canvasId} not found`);
      return null;
    }

    this.destroyChart(canvasId);

    const colors = [
      this.defaultColors.primary,
      this.defaultColors.secondary,
      this.defaultColors.warning,
      this.defaultColors.danger,
      this.defaultColors.info,
      this.defaultColors.purple,
    ];

    const ctx = canvas.getContext('2d');
    this.charts[canvasId] = new Chart(ctx, {
      type: 'pie',
      data: {
        labels: data.labels || [],
        datasets: [{
          data: data.values || [],
          backgroundColor: colors,
          borderColor: '#fff',
          borderWidth: 2,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: options.showLegend !== false,
            position: 'right',
          },
          tooltip: {
            callbacks: {
              label: function(context) {
                const label = context.label || '';
                const value = context.parsed || 0;
                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                const percentage = ((value / total) * 100).toFixed(1);
                return `${label}: ${value} (${percentage}%)`;
              }
            }
          }
        }
      }
    });

    return this.charts[canvasId];
  }

  /**
   * 创建环形图 - 进度显示
   * @param {string} canvasId - Canvas 元素 ID
   * @param {number} percentage - 进度百分比 (0-100)
   * @param {object} options - 可选配置
   */
  createDoughnutChart(canvasId, percentage, options = {}) {
    if (!this.checkChartJS()) return null;

    const canvas = document.getElementById(canvasId);
    if (!canvas) {
      console.error(`Canvas element #${canvasId} not found`);
      return null;
    }

    this.destroyChart(canvasId);

    const remaining = 100 - percentage;
    const color = options.color || this.defaultColors.primary;

    const ctx = canvas.getContext('2d');
    this.charts[canvasId] = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: ['已完成', '未完成'],
        datasets: [{
          data: [percentage, remaining],
          backgroundColor: [color, 'rgba(0, 0, 0, 0.05)'],
          borderWidth: 0,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '75%',
        plugins: {
          legend: {
            display: false,
          },
          tooltip: {
            enabled: options.showTooltip !== false,
            callbacks: {
              label: function(context) {
                return `${context.label}: ${context.parsed}%`;
              }
            }
          }
        }
      }
    });

    return this.charts[canvasId];
  }

  /**
   * 创建柱状图 - 时间分布
   * @param {string} canvasId - Canvas 元素 ID
   * @param {object} data - 数据对象 {labels: [], times: []}
   * @param {object} options - 可选配置
   */
  createBarChart(canvasId, data, options = {}) {
    if (!this.checkChartJS()) return null;

    const canvas = document.getElementById(canvasId);
    if (!canvas) {
      console.error(`Canvas element #${canvasId} not found`);
      return null;
    }

    this.destroyChart(canvasId);

    const ctx = canvas.getContext('2d');
    this.charts[canvasId] = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.labels || [],
        datasets: [{
          label: options.label || '答题用时（秒）',
          data: data.times || [],
          backgroundColor: this.defaultColors.info,
          borderColor: this.defaultColors.info,
          borderWidth: 1,
          borderRadius: 4,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: options.showLegend !== false,
            position: 'top',
          },
          tooltip: {
            callbacks: {
              label: function(context) {
                const seconds = context.parsed.y;
                const minutes = Math.floor(seconds / 60);
                const secs = seconds % 60;
                return `用时: ${minutes}分${secs}秒`;
              }
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              callback: function(value) {
                return value + 's';
              }
            },
            grid: {
              color: 'rgba(0, 0, 0, 0.05)',
            }
          },
          x: {
            grid: {
              display: false,
            }
          }
        }
      }
    });

    return this.charts[canvasId];
  }

  /**
   * 更新图表数据
   * @param {string} chartId - 图表 ID
   * @param {object} newData - 新数据
   */
  updateChart(chartId, newData) {
    const chart = this.charts[chartId];
    if (!chart) {
      console.error(`Chart #${chartId} not found`);
      return;
    }

    // 更新数据
    if (newData.labels) {
      chart.data.labels = newData.labels;
    }
    if (newData.datasets) {
      chart.data.datasets = newData.datasets;
    } else if (newData.data) {
      chart.data.datasets[0].data = newData.data;
    }

    chart.update();
  }

  /**
   * 销毁所有图表
   */
  destroyAll() {
    Object.keys(this.charts).forEach(chartId => {
      this.destroyChart(chartId);
    });
  }

  /**
   * 获取图表实例
   */
  getChart(chartId) {
    return this.charts[chartId];
  }
}

// 导出到全局
if (typeof window !== 'undefined') {
  window.ChartComponents = ChartComponents;
}

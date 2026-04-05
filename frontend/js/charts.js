/**
 * charts.js — Chart.js setup helpers + shared API fetch for AI 투자 시뮬레이터
 */

// Shared API helper — 15초 타임아웃 포함
async function apiFetch(path, opts = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const r = await fetch(path, { signal: controller.signal, ...opts });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

// ── Shared chart defaults ──────────────────────────────────────
const CHART_DEFAULTS = {
    color: '#94a3b8',
    gridColor: 'rgba(255,255,255,.05)',
    font: { family: 'Inter, sans-serif', size: 11 },
};

// Apply global defaults once Chart.js is ready
function applyChartDefaults() {
    if (typeof Chart === 'undefined') return;
    Chart.defaults.color = CHART_DEFAULTS.color;
    Chart.defaults.font.family = CHART_DEFAULTS.font.family;
    Chart.defaults.font.size = CHART_DEFAULTS.font.size;
}

// ── Agent colors / names ───────────────────────────────────────
const AGENT_COLORS = {
    macro:       '#7c6aff',
    strategist:  '#3b82f6',
    surfer:      '#f59e0b',
    explorer:    '#ec4899',
    bear:        '#ef4444',
};

const AGENT_NAMES_KR = {
    macro:       '매크로',
    strategist:  '전략가',
    surfer:      '서퍼',
    explorer:    '미래탐색자',
    bear:        '베어',
};

// Registry of active Chart instances (to destroy before re-creating)
const _charts = {};

function destroyChart(id) {
    if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
}

// ── Performance line chart ─────────────────────────────────────
/**
 * Render cumulative-return line chart for all agents.
 * @param {string} canvasId
 * @param {Object[]} datasets  [{agentId, snapshots:[{snapshot_date, total_value_krw}]}]
 */
function renderPerformanceChart(canvasId, datasets) {
    applyChartDefaults();
    destroyChart(canvasId);

    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    // Build unified label array (union of all dates)
    const dateSet = new Set();
    datasets.forEach(d => d.snapshots.forEach(s => dateSet.add(s.snapshot_date)));
    const labels = Array.from(dateSet).sort();

    const chartDatasets = datasets.map(d => {
        // Build date → value map
        const map = {};
        d.snapshots.forEach(s => { map[s.snapshot_date] = s.total_value_krw; });
        const data = labels.map(lbl => {
            const v = map[lbl];
            return v != null ? +parseFloat(v).toFixed(2) : null;
        });
        const color = AGENT_COLORS[d.agentId] || '#888';
        return {
            label: AGENT_NAMES_KR[d.agentId] || d.agentId,
            data,
            borderColor: color,
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 4,
            tension: 0.35,
            spanGaps: true,
        };
    });

    _charts[canvasId] = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { labels, datasets: chartDatasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    labels: {
                        color: '#94a3b8',
                        usePointStyle: true,
                        pointStyle: 'circle',
                        boxWidth: 8,
                        padding: 14,
                    },
                },
                tooltip: {
                    backgroundColor: '#1a1d27',
                    borderColor: '#2a2d3a',
                    borderWidth: 1,
                    titleColor: '#e2e8f0',
                    bodyColor: '#94a3b8',
                    callbacks: {
                        label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y != null ? (ctx.parsed.y > 0 ? '+' : '') + ctx.parsed.y + '%' : '-'}`,
                    },
                },
            },
            scales: {
                x: {
                    ticks: { color: '#4b5563', maxTicksLimit: 10, maxRotation: 0 },
                    grid:  { color: CHART_DEFAULTS.gridColor },
                },
                y: {
                    ticks: {
                        color: '#4b5563',
                        callback: v => (v > 0 ? '+' : '') + v + '%',
                    },
                    grid: { color: CHART_DEFAULTS.gridColor },
                    position: 'left',
                },
            },
        },
    });
}

// ── Agent single-line performance chart ───────────────────────
function renderAgentChart(canvasId, agentId, snapshots) {
    applyChartDefaults();
    destroyChart(canvasId);

    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const labels = snapshots.map(s => s.snapshot_date);
    const data   = snapshots.map(s => +parseFloat(s.total_value_krw || 0).toFixed(2));
    const color  = AGENT_COLORS[agentId] || '#7c6aff';

    _charts[canvasId] = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: AGENT_NAMES_KR[agentId] || agentId,
                data,
                borderColor: color,
                backgroundColor: color + '18',
                fill: true,
                borderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 4,
                tension: 0.35,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#1a1d27',
                    borderColor: '#2a2d3a',
                    borderWidth: 1,
                    titleColor: '#e2e8f0',
                    bodyColor: '#94a3b8',
                    callbacks: {
                        label: ctx => ` ${(ctx.parsed.y > 0 ? '+' : '') + ctx.parsed.y}%`,
                    },
                },
            },
            scales: {
                x: {
                    ticks: { color: '#4b5563', maxTicksLimit: 8, maxRotation: 0 },
                    grid:  { color: CHART_DEFAULTS.gridColor },
                },
                y: {
                    ticks: {
                        color: '#4b5563',
                        callback: v => (v > 0 ? '+' : '') + v + '%',
                    },
                    grid: { color: CHART_DEFAULTS.gridColor },
                },
            },
        },
    });
}

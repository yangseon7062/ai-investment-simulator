const API = '';
let performanceChart = null;

// ── 페이지 전환 ──────────────────────────────────────────────────

function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  event.target.classList.add('active');

  if (name === 'main') loadMain();
  if (name === 'agents') loadAgentsPage();
  if (name === 'logs') loadLogs();
  if (name === 'debate') loadDebate();
  if (name === 'roundtable') loadRoundtable();
  if (name === 'data') loadDataStatus();
}

// ── 메인 ─────────────────────────────────────────────────────────

async function loadMain() {
  const data = await fetch(`${API}/api/dashboard/summary`).then(r => r.json()).catch(() => ({}));

  // 한 줄 요약
  const snap = data.snapshot || {};
  document.getElementById('daily-summary').textContent = snap.daily_summary || '오늘 데이터 없음';

  // 국면 배지
  const regimeMap = { '상승장': 'up', '하락장': 'down', '횡보': 'side', '변동성급등': 'vol' };
  const labelMap  = { '상승장': '📈 상승장', '하락장': '📉 하락장', '횡보': '➡️ 횡보', '변동성급등': '⚡ 변동성급등' };
  const badgesEl = document.getElementById('regime-badges');
  badgesEl.innerHTML = [
    { label: 'KR ' + (snap.regime_kr || '-'), regime: snap.regime_kr },
    { label: 'US ' + (snap.regime_us || '-'), regime: snap.regime_us },
  ].map(b => `<span class="badge badge-${regimeMap[b.regime] || 'side'}">${b.label}</span>`).join('');

  // 내러티브
  const narrative = [snap.narrative_kr, snap.narrative_us].filter(Boolean).join('<br><br>');
  document.getElementById('narrative-box').innerHTML = narrative || '시장 내러티브 없음';

  // 에이전트 카드
  renderAgentCards(data.agents || []);

  // 성과 차트
  await loadPerformanceChart();

  // 통합 포트폴리오
  const portfolio = await fetch(`${API}/api/dashboard/portfolio`).then(r => r.json()).catch(() => []);
  renderUnifiedPortfolio(portfolio);

  // 충돌
  const conflicts = await fetch(`${API}/api/dashboard/conflicts`).then(r => r.json()).catch(() => []);
  renderConflicts(conflicts);

  // 최근 로그
  const logs = await fetch(`${API}/api/logs/?limit=10`).then(r => r.json()).catch(() => []);
  document.getElementById('recent-logs').innerHTML = logs.map(renderLogCard).join('');

  // API 비용
  const cost = data.api_cost || {};
  document.getElementById('api-cost').innerHTML = `
    <div style="background:#1a1d27;border:1px solid #2a2d3a;border-radius:10px;padding:16px">
      <div style="font-size:24px;font-weight:700;color:#7c6aff">$${(cost.total_cost || 0).toFixed(3)}</div>
      <div style="color:#666;font-size:12px;margin-top:4px">이번 달 누적 / ${cost.call_count || 0}회 호출</div>
    </div>`;
}

function renderAgentCards(agents) {
  const NAMES = { macro: '매크로', strategist: '전략가', analyst: '심사역', surfer: '서퍼', explorer: '미래탐색자', contrarian: '컨트라리안', bear: '베어' };
  const STYLES = { macro: '거시테마', strategist: '퀄리티', analyst: '가치', surfer: '모멘텀', explorer: '성장', contrarian: '역발상', bear: '하락베팅' };

  document.getElementById('agent-cards').innerHTML = agents.map(a => {
    const ret = a.total_return || 0;
    const cls = ret > 0 ? 'return-pos' : ret < 0 ? 'return-neg' : 'return-zero';
    const sign = ret > 0 ? '+' : '';
    return `<div class="agent-card" onclick="openAgentDetail('${a.agent_id}')">
      <div class="agent-name">${NAMES[a.agent_id] || a.agent_id}</div>
      <div class="agent-style">${STYLES[a.agent_id] || ''}</div>
      <div class="agent-return ${cls}">${sign}${ret.toFixed(2)}%</div>
      <div class="agent-meta">보유 ${a.open_positions}종목 · 일간 ${a.daily_return ? (a.daily_return > 0 ? '+' : '') + a.daily_return.toFixed(2) + '%' : '-'}</div>
    </div>`;
  }).join('');
}

async function loadPerformanceChart() {
  const agents = ['macro', 'strategist', 'analyst', 'surfer', 'explorer', 'contrarian', 'bear'];
  const NAMES  = { macro: '매크로', strategist: '전략가', analyst: '심사역', surfer: '서퍼', explorer: '미래탐색자', contrarian: '컨트라리안', bear: '베어' };
  const COLORS = ['#7c6aff','#4caf50','#42a5f5','#ffc107','#ef5350','#ab47bc','#26c6da'];

  const datasets = [];
  let labels = [];

  for (let i = 0; i < agents.length; i++) {
    const perf = await fetch(`${API}/api/agents/${agents[i]}/performance`).then(r => r.json()).catch(() => ({ snapshots: [] }));
    const snaps = perf.snapshots || [];
    if (snaps.length > labels.length) labels = snaps.map(s => s.snapshot_date);
    datasets.push({
      label: NAMES[agents[i]],
      data: snaps.map(s => ((s.total_value_krw - 100_000_000) / 100_000_000 * 100).toFixed(2)),
      borderColor: COLORS[i],
      backgroundColor: 'transparent',
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.4,
    });
  }

  const ctx = document.getElementById('performance-chart').getContext('2d');
  if (performanceChart) performanceChart.destroy();
  performanceChart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#888', font: { size: 11 } } } },
      scales: {
        x: { ticks: { color: '#555', maxTicksLimit: 10 }, grid: { color: '#1e2130' } },
        y: { ticks: { color: '#555', callback: v => v + '%' }, grid: { color: '#1e2130' } },
      },
    },
  });
}

function renderUnifiedPortfolio(portfolio) {
  document.getElementById('unified-portfolio').innerHTML = `
    <table class="portfolio-table">
      <thead><tr><th>종목</th><th>시장</th><th>섹터</th><th>동의</th></tr></thead>
      <tbody>
        ${portfolio.slice(0, 10).map(p => `
          <tr>
            <td><strong>${p.name || p.ticker}</strong><br><span style="color:#555;font-size:11px">${p.ticker}</span></td>
            <td>${p.market}</td>
            <td style="color:#666">${p.sector || '-'}</td>
            <td style="color:${p.agent_count >= 3 ? '#7c6aff' : '#aaa'};font-weight:700">${p.agent_count}명</td>
          </tr>`).join('')}
      </tbody>
    </table>`;
}

function renderConflicts(conflicts) {
  document.getElementById('conflicts-list').innerHTML = conflicts.length
    ? conflicts.slice(0, 5).map(c => `
        <div class="log-card" onclick="openReport(${c.id})">
          <div class="log-header">
            <span class="log-type type-debate">토론</span>
            <span>${c.tickers}</span>
            <span class="log-time">${formatTime(c.created_at)}</span>
          </div>
        </div>`).join('')
    : '<div style="color:#555;padding:12px">충돌 없음</div>';
}

// ── 로그 ─────────────────────────────────────────────────────────

async function loadLogs() {
  const agentFilter = document.getElementById('log-agent-filter')?.value || '';
  const typeFilter  = document.getElementById('log-type-filter')?.value || '';

  let url = `${API}/api/logs/?limit=50`;
  if (agentFilter) url += `&agent_id=${agentFilter}`;
  if (typeFilter)  url += `&log_type=${typeFilter}`;

  const logs = await fetch(url).then(r => r.json()).catch(() => []);
  document.getElementById('logs-list').innerHTML = logs.map(renderLogCard).join('');

  // 에이전트 필터 옵션 채우기
  const sel = document.getElementById('log-agent-filter');
  if (sel && sel.options.length <= 1) {
    const agents = ['macro','strategist','analyst','surfer','explorer','contrarian','bear'];
    const NAMES = { macro:'매크로', strategist:'전략가', analyst:'심사역', surfer:'서퍼', explorer:'미래탐색자', contrarian:'컨트라리안', bear:'베어' };
    agents.forEach(a => {
      const opt = document.createElement('option');
      opt.value = a; opt.textContent = NAMES[a];
      sel.appendChild(opt);
    });
  }
}

function renderLogCard(log) {
  const typeLabel = { buy:'매수', sell:'매도', monitor:'모니터링', pass:'관망', postmortem:'사후검증', debate:'토론', roundtable:'라운드테이블', research:'조사' };
  const NAMES = { macro:'매크로', strategist:'전략가', analyst:'심사역', surfer:'서퍼', explorer:'미래탐색자', contrarian:'컨트라리안', bear:'베어', system:'시스템' };

  const summary = (log.thesis || log.report_md || '').slice(0, 120).replace(/#+/g, '').replace(/\n/g, ' ');
  return `<div class="log-card" onclick="openReport(${log.id})">
    <div class="log-header">
      <span class="log-agent">${NAMES[log.agent_id] || log.agent_id}</span>
      <span class="log-type type-${log.log_type}">${typeLabel[log.log_type] || log.log_type}</span>
      ${log.tickers ? `<span style="color:#7c6aff;font-size:12px">${log.tickers}</span>` : ''}
      <span class="log-time">${formatTime(log.created_at)}</span>
    </div>
    <div class="log-summary">${summary}...</div>
  </div>`;
}

async function openReport(logId) {
  const log = await fetch(`${API}/api/logs/${logId}`).then(r => r.json()).catch(() => ({}));
  const html = markdownToHtml(log.report_md || '내용 없음');
  const modal = document.createElement('div');
  modal.className = 'report-modal';
  modal.innerHTML = `
    <div class="report-content">
      <button class="close-btn" onclick="this.closest('.report-modal').remove()">✕</button>
      ${html}
    </div>`;
  document.body.appendChild(modal);
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
}

// ── 에이전트 상세 ─────────────────────────────────────────────────

async function loadAgentsPage() {
  const agents = await fetch(`${API}/api/agents/`).then(r => r.json()).catch(() => []);
  const NAMES  = { macro:'매크로', strategist:'전략가', analyst:'심사역', surfer:'서퍼', explorer:'미래탐색자', contrarian:'컨트라리안', bear:'베어' };

  document.getElementById('agent-selector').innerHTML = agents.map(a =>
    `<button class="agent-btn" onclick="openAgentDetail('${a.agent_id}')">${NAMES[a.agent_id] || a.agent_id}</button>`
  ).join('');
}

async function openAgentDetail(agentId) {
  document.querySelectorAll('.agent-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.agent-btn').forEach(b => {
    if (b.textContent.includes(agentId) || b.onclick?.toString().includes(agentId)) b.classList.add('active');
  });

  showPage('agents');

  const [positions, perf] = await Promise.all([
    fetch(`${API}/api/agents/${agentId}/positions`).then(r => r.json()).catch(() => []),
    fetch(`${API}/api/agents/${agentId}/performance`).then(r => r.json()).catch(() => ({})),
  ]);

  const NAMES = { macro:'매크로', strategist:'전략가', analyst:'심사역', surfer:'서퍼', explorer:'미래탐색자', contrarian:'컨트라리안', bear:'베어' };

  document.getElementById('agent-detail').innerHTML = `
    <h2>${NAMES[agentId]} 보유 포지션</h2>
    <table class="portfolio-table">
      <thead><tr><th>종목</th><th>시장</th><th>매수가</th><th>상태</th><th>섹터</th></tr></thead>
      <tbody>
        ${positions.map(p => `
          <tr>
            <td><strong>${p.name || p.ticker}</strong><br><span style="color:#555;font-size:11px">${p.ticker}</span></td>
            <td>${p.market}</td>
            <td>${(p.price || 0).toLocaleString()}</td>
            <td class="status-${p.status}">${{buy:'매수',hold:'보유',watch:'경계',closed:'종료'}[p.status] || p.status}</td>
            <td style="color:#666">${p.sector || '-'}</td>
          </tr>`).join('')}
      </tbody>
    </table>
    <br>
    <div style="color:#666;font-size:13px">승률: ${perf.win_rate != null ? perf.win_rate + '%' : '-'}</div>`;
}

// ── 토론 ─────────────────────────────────────────────────────────

async function loadDebate() {
  const debates = await fetch(`${API}/api/logs/?log_type=debate&limit=20`).then(r => r.json()).catch(() => []);
  document.getElementById('debate-list').innerHTML = debates.length
    ? debates.map(renderLogCard).join('')
    : '<div style="color:#555;padding:20px">충돌 토론 없음</div>';
}

// ── 라운드테이블 ──────────────────────────────────────────────────

async function loadRoundtable() {
  const log = await fetch(`${API}/api/logs/roundtable/latest`).then(r => r.json()).catch(() => ({}));
  document.getElementById('roundtable-content').innerHTML = log.report_md
    ? markdownToHtml(log.report_md)
    : '<div style="color:#555;padding:20px">라운드테이블 데이터 없음</div>';
}

// ── 종목 매트릭스 ─────────────────────────────────────────────────

async function searchStock() {
  const ticker = document.getElementById('stock-search').value.trim().toUpperCase();
  if (!ticker) return;

  const matrix = await fetch(`${API}/api/agents/stock/${ticker}/matrix`).then(r => r.json()).catch(() => []);

  if (!matrix.length) {
    document.getElementById('stock-matrix').innerHTML = '<div style="color:#555;padding:20px">종목 없음</div>';
    return;
  }

  const statusLabel = { buy:'매수', hold:'보유', watch:'경계', 미보유:'미보유', closed:'종료' };

  document.getElementById('stock-matrix').innerHTML = `
    <h2>${ticker} — 에이전트 시각 비교</h2>
    <table class="matrix-table">
      <thead><tr><th>에이전트</th><th>스탠스</th><th>매수가</th><th>투자 테제</th><th>최종 업데이트</th></tr></thead>
      <tbody>
        ${matrix.map(r => `
          <tr>
            <td><strong>${r.name_kr}</strong></td>
            <td class="status-${r.status === '미보유' ? 'none' : r.status}">${statusLabel[r.status] || r.status}</td>
            <td>${r.price ? r.price.toLocaleString() : '-'}</td>
            <td style="color:#aaa;font-size:12px">${r.thesis || '-'}</td>
            <td style="color:#555;font-size:11px">${r.last_updated ? formatTime(r.last_updated) : '-'}</td>
          </tr>`).join('')}
      </tbody>
    </table>`;
}

// ── 데이터 현황 ───────────────────────────────────────────────────

async function loadDataStatus() {
  const stats = await Promise.all([
    fetch(`${API}/api/logs/?limit=1`).then(r => r.json()).catch(() => []),
    fetch(`${API}/api/agents/`).then(r => r.json()).catch(() => []),
  ]);

  document.getElementById('data-status').innerHTML = `
    <div style="background:#1a1d27;border:1px solid #2a2d3a;border-radius:10px;padding:20px;line-height:2">
      <div>수집 시작일: 시스템 최초 실행일 기준</div>
      <div style="color:#666;font-size:13px">백테스팅은 6개월 이상 운영 후 실 데이터로 구현 예정</div>
      <br>
      <div>에이전트: 7명 활성</div>
    </div>`;
}

// ── 유틸 ─────────────────────────────────────────────────────────

function formatTime(str) {
  if (!str) return '';
  return str.slice(0, 16).replace('T', ' ');
}

function markdownToHtml(md) {
  return md
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/^(?!<[hul])/gm, '<p>')
    .replace(/(?<![>])$/gm, '</p>');
}

// ── 초기 로드 ─────────────────────────────────────────────────────
loadMain();

// ── Constants ──────────────────────────────────────────────────
const AGENTS = [
  { id:'macro',      name:'매크로',    icon:'public',        color:'#7c6aff', style:'거시테마형' },
  { id:'strategist', name:'전략가',    icon:'analytics',     color:'#3b82f6', style:'퀄리티형' },
  { id:'analyst',    name:'심사역',    icon:'manage_search', color:'#10b981', style:'가치형' },
  { id:'surfer',     name:'서퍼',      icon:'trending_up',   color:'#f59e0b', style:'모멘텀형' },
  { id:'explorer',   name:'미래탐색자',icon:'rocket_launch', color:'#ec4899', style:'성장형' },
  { id:'contrarian', name:'컨트라리안',icon:'swap_horiz',    color:'#8b5cf6', style:'역발상형' },
  { id:'bear',       name:'베어',      icon:'trending_down', color:'#ef4444', style:'하락베팅형' },
];

const PAGE_TITLES = {
  main:'메인', agents:'에이전트', logs:'로그',
  stocks:'종목뷰', debate:'토론', roundtable:'라운드테이블', data:'데이터현황',
};

let logsOffset = 0;
const LOGS_LIMIT = 30;

// ── Modal ──────────────────────────────────────────────────────
function showModal(html) {
  document.getElementById('modal-body').innerHTML = html;
  document.getElementById('modal-backdrop').classList.remove('hidden');
}
function updateModal(html) {
  document.getElementById('modal-body').innerHTML = html;
}
function closeModal() {
  document.getElementById('modal-backdrop').classList.add('hidden');
}

// ── Navigation ─────────────────────────────────────────────────
function showPage(pageId) {
  document.querySelectorAll('.page').forEach(p => {
    p.classList.add('hidden');
    p.classList.remove('block');
  });
  const page = document.getElementById('page-' + pageId);
  if (page) { page.classList.remove('hidden'); page.classList.add('block'); }

  document.querySelectorAll('.nav-link').forEach(n => {
    n.classList.remove('text-primary','bg-primary/10','font-semibold');
    n.classList.add('text-gray-500');
  });
  const active = document.querySelector(`.nav-link[data-page="${pageId}"]`);
  if (active) {
    active.classList.add('text-primary','bg-primary/10','font-semibold');
    active.classList.remove('text-gray-500');
  }

  const title = document.getElementById('page-title');
  if (title) title.textContent = PAGE_TITLES[pageId] || pageId;

  currentPage = pageId;
  loadPageData(pageId);
}

function loadPageData(pageId) {
  if (pageId === 'main')        loadMain();
  if (pageId === 'agents')      loadAgentsPage();
  if (pageId === 'logs')        { logsOffset = 0; loadLogs(); }
  if (pageId === 'debate')      loadDebate();
  if (pageId === 'roundtable')  loadRoundtable();
  if (pageId === 'data')        loadDataStatus();
}

// ── Page: 메인 ─────────────────────────────────────────────────
async function loadMain() {
  const [summary, portfolio, conflicts] = await Promise.all([
    apiFetch('/api/dashboard/summary').catch(() => ({})),
    apiFetch('/api/dashboard/portfolio').catch(() => []),
    apiFetch('/api/dashboard/conflicts').catch(() => []),
  ]);

  const snap = summary.snapshot || {};

  // Daily summary text
  document.getElementById('daily-summary-text').textContent =
    snap.daily_summary || '오늘 시장 요약 없음';

  // Last updated
  const lu = document.getElementById('last-updated');
  if (lu && snap.snapshot_date) lu.textContent = snap.snapshot_date + ' 기준';

  // Regime badges
  renderRegimeBadges(snap);

  // Agent cards
  renderAgentCards(summary.agents || []);

  // Performance chart
  await loadPerformanceChart();

  // Conflicts
  renderConflicts(conflicts);

  // Portfolio table
  renderUnifiedPortfolio(portfolio);

  // Recent logs
  const logs = await apiFetch('/api/logs/?limit=8').catch(() => []);
  const el = document.getElementById('recent-logs');
  renderLogList(el, logs);

  // Sidebar cost
  const cost = summary.api_cost || {};
  document.getElementById('sidebar-cost').textContent = '$' + (cost.total_cost || 0).toFixed(3);
  document.getElementById('sidebar-cost-meta').textContent = (cost.call_count || 0) + '회 호출';
}

function renderRegimeBadges(snap) {
  const el = document.getElementById('regime-badges');
  if (!el) return;
  const regimeClass = r => {
    if (r === '상승장') return 'regime-up';
    if (r === '하락장') return 'regime-down';
    if (r === '변동성급등') return 'regime-vol';
    return 'regime-side';
  };
  const badges = [];
  if (snap.regime_kr) badges.push(`<span class="text-[10px] font-bold px-2 py-0.5 rounded-full ${regimeClass(snap.regime_kr)}">KR ${snap.regime_kr}</span>`);
  if (snap.regime_us) badges.push(`<span class="text-[10px] font-bold px-2 py-0.5 rounded-full ${regimeClass(snap.regime_us)}">US ${snap.regime_us}</span>`);
  el.innerHTML = badges.join('');
}

function renderAgentCards(agents) {
  const el = document.getElementById('agent-cards');
  if (!el) return;

  if (!agents.length) {
    el.innerHTML = AGENTS.map(a => agentCardSkeleton(a)).join('');
    return;
  }

  const map = {};
  agents.forEach(a => { map[a.agent_id] = a; });

  el.innerHTML = AGENTS.map(agent => {
    const a = map[agent.id] || {};
    const ret = a.total_return || 0;
    const sign = ret >= 0 ? '+' : '';
    const retColor = ret > 0 ? 'text-success' : ret < 0 ? 'text-danger' : 'text-gray-400';
    return `
    <div class="bg-card border border-gray-800/60 rounded-xl p-3.5 cursor-pointer agent-card-hover transition-all"
         onclick="openAgentDetail('${agent.id}')">
      <div class="flex items-center justify-between mb-3">
        <div class="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
             style="background:${agent.color}22">
          <span class="material-symbols-outlined text-sm" style="color:${agent.color}">${agent.icon}</span>
        </div>
        <span class="${retColor} text-xs font-bold">${sign}${ret.toFixed(2)}%</span>
      </div>
      <p class="text-xs font-bold text-white truncate">${agent.name}</p>
      <p class="text-[10px] text-gray-600 mt-0.5">${agent.style}</p>
      <div class="mt-2 flex items-center justify-between">
        <span class="text-[10px] text-gray-600">${(a.open_positions || 0)}종목</span>
        <span class="text-[10px] text-gray-600">${a.cash_balance_krw != null ? (a.cash_balance_krw/1e8).toFixed(2)+'억' : '-'}</span>
      </div>
    </div>`;
  }).join('');
}

function agentCardSkeleton(agent) {
  return `
  <div class="bg-card border border-gray-800/60 rounded-xl p-3.5">
    <div class="flex items-center justify-between mb-3">
      <div class="w-7 h-7 rounded-lg skeleton"></div>
      <div class="w-10 h-3 rounded skeleton"></div>
    </div>
    <div class="w-16 h-3 rounded skeleton mb-1.5"></div>
    <div class="w-12 h-2.5 rounded skeleton"></div>
  </div>`;
}

async function loadPerformanceChart() {
  const datasets = [];
  for (const agent of AGENTS) {
    const perf = await apiFetch(`/api/agents/${agent.id}/performance`).catch(() => ({ snapshots: [] }));
    datasets.push({ agentId: agent.id, snapshots: perf.snapshots || [] });
  }
  renderPerformanceChart('performance-chart', datasets);
}

function renderConflicts(conflicts) {
  const el = document.getElementById('conflicts-list');
  if (!el) return;
  if (!conflicts.length) {
    el.innerHTML = '<p class="text-xs text-gray-600 py-2">충돌 없음</p>';
    return;
  }
  el.innerHTML = conflicts.slice(0, 6).map(c => `
    <div class="p-3 rounded-lg border cursor-pointer hover:opacity-90 transition-opacity ${c.is_conflict ? 'bg-danger/5 border-danger/20' : 'bg-success/5 border-success/20'}"
         onclick="openReportModal(${c.id})">
      <div class="flex items-center gap-1.5 mb-1">
        <span class="text-[10px] font-bold ${c.is_conflict ? 'text-danger' : 'text-success'}">${c.is_conflict ? '충돌' : '동의'}</span>
        <span class="text-[10px] font-mono text-primary/80">${c.tickers || ''}</span>
      </div>
      <p class="text-[10px] text-gray-500 truncate">${(c.summary || '').slice(0, 60)}</p>
    </div>`).join('');
}

function renderUnifiedPortfolio(portfolio) {
  const el = document.getElementById('unified-portfolio');
  if (!el) return;
  if (!portfolio.length) {
    el.innerHTML = '<tr><td colspan="4" class="px-5 py-8 text-center text-gray-600 text-xs">포트폴리오 없음</td></tr>';
    return;
  }
  el.innerHTML = portfolio.slice(0, 10).map(p => {
    const agentColor = p.agent_count >= 4 ? 'text-primary font-bold' : p.agent_count >= 2 ? 'text-gray-300' : 'text-gray-600';
    return `
    <tr class="hover:bg-white/[.025] transition-colors cursor-pointer" onclick="goToStock('${p.ticker}')">
      <td class="px-5 py-3">
        <span class="font-semibold text-white text-xs">${p.name || p.ticker}</span>
        <span class="text-[10px] text-gray-600 ml-1">${p.ticker}</span>
      </td>
      <td class="px-5 py-3 text-[10px] text-gray-500">${p.market}</td>
      <td class="px-5 py-3 text-[10px] text-gray-600">${p.sector || '-'}</td>
      <td class="px-5 py-3 text-xs ${agentColor}">${p.agent_count}명</td>
    </tr>`;
  }).join('');
}

// ── Page: 에이전트 ─────────────────────────────────────────────
async function loadAgentsPage() {
  const el = document.getElementById('agent-selector');
  el.innerHTML = AGENTS.map(a => `
    <button onclick="openAgentDetail('${a.id}')"
            class="agent-btn px-4 py-2 rounded-lg text-xs font-medium border transition-all hover:border-primary/60"
            style="border-color:${a.color}44; color:${a.color}; background:${a.color}11"
            data-agent="${a.id}">
      ${a.name}
    </button>`).join('');
}

async function openAgentDetail(agentId) {
  // Navigate to agents page if not already there
  if (currentPage !== 'agents') {
    showPage('agents');
    // showPage calls loadAgentsPage which renders the buttons; now fall through to show detail
  }

  // Wait a tick for DOM to settle if we just switched pages
  await new Promise(r => setTimeout(r, 10));

  document.querySelectorAll('.agent-btn').forEach(b => {
    const agent = AGENTS.find(a => a.id === b.dataset.agent);
    if (!agent) return;
    if (b.dataset.agent === agentId) {
      b.style.background = agent.color + '33';
      b.style.borderColor = agent.color;
    } else {
      b.style.background = agent.color + '11';
      b.style.borderColor = agent.color + '44';
    }
  });

  const detail = document.getElementById('agent-detail');
  detail.innerHTML = '<div class="flex items-center gap-2 py-6 text-gray-600 text-sm"><span class="material-symbols-outlined animate-spin">progress_activity</span>로딩 중…</div>';

  const agent = AGENTS.find(a => a.id === agentId) || { name: agentId, color: '#7c6aff', icon: 'smart_toy' };

  const [positions, perf] = await Promise.all([
    apiFetch(`/api/agents/${agentId}/positions`).catch(() => []),
    apiFetch(`/api/agents/${agentId}/performance`).catch(() => ({})),
  ]);

  const snapshots = perf.snapshots || [];
  const totalReturn = snapshots.length
    ? ((snapshots[snapshots.length-1].total_value_krw - 1e8) / 1e8 * 100).toFixed(2)
    : '0.00';

  detail.innerHTML = `
    <div class="space-y-5">
      <!-- Agent header -->
      <div class="bg-card border border-gray-800/60 rounded-2xl p-5 flex items-center gap-4">
        <div class="w-12 h-12 rounded-xl flex items-center justify-center" style="background:${agent.color}22">
          <span class="material-symbols-outlined text-xl" style="color:${agent.color}">${agent.icon}</span>
        </div>
        <div>
          <h3 class="text-base font-bold text-white">${agent.name}</h3>
          <p class="text-xs text-gray-600">${agent.style}</p>
        </div>
        <div class="ml-auto text-right">
          <div class="text-xl font-bold ${+totalReturn >= 0 ? 'text-success' : 'text-danger'}">${+totalReturn >= 0 ? '+' : ''}${totalReturn}%</div>
          <div class="text-xs text-gray-600">누적 수익률</div>
        </div>
        <div class="ml-6 text-right">
          <div class="text-base font-bold text-white">${perf.win_rate != null ? perf.win_rate + '%' : '-'}</div>
          <div class="text-xs text-gray-600">승률</div>
        </div>
      </div>

      <!-- Mini chart -->
      ${snapshots.length ? `
      <div class="bg-card border border-gray-800/60 rounded-2xl p-5">
        <h4 class="text-xs font-bold text-gray-400 uppercase mb-3">수익률 추이</h4>
        <div class="h-32"><canvas id="agent-chart-${agentId}"></canvas></div>
      </div>` : ''}

      <!-- Positions table -->
      <div class="bg-card border border-gray-800/60 rounded-2xl overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-800/60">
          <h4 class="text-xs font-bold text-gray-400 uppercase">보유 포지션 (${positions.length})</h4>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-xs text-left data-table">
            <thead class="bg-[#0f1117] text-gray-600 uppercase tracking-wider">
              <tr>
                <th class="px-5 py-3">종목</th>
                <th class="px-5 py-3">시장</th>
                <th class="px-5 py-3">매수가</th>
                <th class="px-5 py-3">상태</th>
                <th class="px-5 py-3">섹터</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-800/40">
              ${positions.map(p => `
              <tr class="hover:bg-white/[.025]">
                <td class="px-5 py-3">
                  <span class="font-semibold text-white">${p.name || p.ticker}</span>
                  <span class="text-gray-600 ml-1">${p.ticker}</span>
                </td>
                <td class="px-5 py-3 text-gray-500">${p.market}</td>
                <td class="px-5 py-3 text-gray-400">${(p.price || 0).toLocaleString()}</td>
                <td class="px-5 py-3 status-${p.status}">${{buy:'매수',hold:'보유',watch:'경계',closed:'종료'}[p.status] || p.status}</td>
                <td class="px-5 py-3 text-gray-600">${p.sector || '-'}</td>
              </tr>`).join('') || '<tr><td colspan="5" class="px-5 py-8 text-center text-gray-600">포지션 없음</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </div>`;

  if (snapshots.length) {
    setTimeout(() => renderAgentChart(`agent-chart-${agentId}`, agentId, snapshots), 50);
  }
}

// ── Page: 로그 ─────────────────────────────────────────────────
async function loadLogs() {
  logsOffset = 0;
  const list = document.getElementById('logs-list');
  list.innerHTML = '<div class="flex items-center gap-2 py-6 text-gray-600 text-xs"><span class="material-symbols-outlined animate-spin text-base">progress_activity</span>로딩 중…</div>';

  const agent = document.getElementById('log-agent-filter')?.value || '';
  const type  = document.getElementById('log-type-filter')?.value  || '';

  let url = `/api/logs/?limit=${LOGS_LIMIT}&offset=0`;
  if (agent) url += `&agent_id=${agent}`;
  if (type)  url += `&log_type=${type}`;

  const logs = await apiFetch(url).catch(() => []);
  renderLogList(list, logs);
  logsOffset = logs.length;

  const btn = document.getElementById('load-more-logs');
  if (btn) btn.classList.toggle('hidden', logs.length < LOGS_LIMIT);
}

async function loadMoreLogs() {
  const agent = document.getElementById('log-agent-filter')?.value || '';
  const type  = document.getElementById('log-type-filter')?.value  || '';
  let url = `/api/logs/?limit=${LOGS_LIMIT}&offset=${logsOffset}`;
  if (agent) url += `&agent_id=${agent}`;
  if (type)  url += `&log_type=${type}`;

  const logs = await apiFetch(url).catch(() => []);
  const list = document.getElementById('logs-list');
  if (list) list.insertAdjacentHTML('beforeend', logs.map((l, i) => renderLogCard(l, logsOffset + i)).join(''));
  logsOffset += logs.length;

  const btn = document.getElementById('load-more-logs');
  if (btn) btn.classList.toggle('hidden', logs.length < LOGS_LIMIT);
}

// ── Page: 토론 ─────────────────────────────────────────────────
async function loadDebate() {
  const list = document.getElementById('debate-list');
  const debates = await apiFetch('/api/logs/?log_type=debate&limit=20').catch(() => []);
  renderLogList(list, debates);
}

// ── Page: 라운드테이블 ─────────────────────────────────────────
async function loadRoundtable() {
  const list = document.getElementById('roundtable-list');
  const rounds = await apiFetch('/api/logs/?log_type=roundtable&limit=10').catch(() => []);
  renderLogList(list, rounds);
}

// ── Page: 종목뷰 ───────────────────────────────────────────────
async function searchStock() {
  const ticker = document.getElementById('stock-search').value.trim().toUpperCase();
  if (!ticker) return;

  const el = document.getElementById('stock-matrix');
  el.innerHTML = '<div class="flex items-center gap-2 text-gray-600 text-xs py-4"><span class="material-symbols-outlined animate-spin text-base">progress_activity</span>조회 중…</div>';

  const matrix = await apiFetch(`/api/agents/stock/${ticker}/matrix`).catch(() => []);

  if (!matrix.length) {
    el.innerHTML = '<div class="text-gray-600 text-sm py-8 text-center">해당 종목 데이터 없음</div>';
    return;
  }

  el.innerHTML = `
    <div class="bg-card border border-gray-800/60 rounded-2xl overflow-hidden">
      <div class="px-5 py-4 border-b border-gray-800/60">
        <h4 class="text-sm font-bold text-white">${ticker} — 에이전트 시각 비교</h4>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-xs text-left data-table">
          <thead class="bg-[#0f1117] text-gray-600 uppercase tracking-wider">
            <tr>
              <th class="px-5 py-3">에이전트</th>
              <th class="px-5 py-3">스탠스</th>
              <th class="px-5 py-3">매수가</th>
              <th class="px-5 py-3">투자 테제</th>
              <th class="px-5 py-3">최종 업데이트</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-800/40">
            ${matrix.map(r => {
              const agent = AGENTS.find(a => a.id === r.agent_id) || {};
              return `
              <tr class="hover:bg-white/[.025]">
                <td class="px-5 py-3">
                  <div class="flex items-center gap-2">
                    ${agent.icon ? `<span class="material-symbols-outlined text-sm" style="color:${agent.color}">${agent.icon}</span>` : ''}
                    <span class="font-medium text-white">${r.name_kr || agent.name || r.agent_id}</span>
                  </div>
                </td>
                <td class="px-5 py-3 status-${r.status === '미보유' ? 'none' : r.status}">
                  ${{ buy:'매수', hold:'보유', watch:'경계', 미보유:'미보유', closed:'종료' }[r.status] || r.status}
                </td>
                <td class="px-5 py-3 text-gray-400">${r.price ? r.price.toLocaleString() : '-'}</td>
                <td class="px-5 py-3 text-gray-500 max-w-xs truncate">${r.thesis || '-'}</td>
                <td class="px-5 py-3 text-gray-600">${r.last_updated ? formatTs(r.last_updated) : '-'}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>`;
}

function goToStock(ticker) {
  showPage('stocks');
  document.getElementById('stock-search').value = ticker;
  searchStock();
}

// ── Page: 데이터현황 ───────────────────────────────────────────
async function loadDataStatus() {
  const summary = await apiFetch('/api/dashboard/summary').catch(() => ({}));
  const cost = summary.api_cost || {};

  const grid = document.getElementById('data-status-grid');
  grid.innerHTML = [
    { label: '에이전트', value: '7명 활성', icon: 'smart_toy', color: '#7c6aff' },
    { label: '이번달 API 비용', value: '$' + (cost.total_cost || 0).toFixed(4), icon: 'payments', color: '#22c55e' },
    { label: 'API 호출 횟수', value: (cost.call_count || 0) + '회', icon: 'api', color: '#3b82f6' },
    { label: '백테스팅', value: '운영 6개월 후', icon: 'history', color: '#f59e0b' },
  ].map(s => `
    <div class="bg-card border border-gray-800/60 rounded-2xl p-5">
      <span class="material-symbols-outlined text-2xl mb-2 block" style="color:${s.color}">${s.icon}</span>
      <div class="text-base font-bold text-white">${s.value}</div>
      <div class="text-xs text-gray-600 mt-1">${s.label}</div>
    </div>`).join('');

  const table = document.getElementById('api-usage-table');
  table.innerHTML = `
    <div class="text-xs text-gray-600 text-center py-6">
      API 상세 사용 내역은 누적 후 표시됩니다
    </div>`;
}

// ── Init ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Sidebar nav click handlers
  document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', () => showPage(link.dataset.page));
  });

  // Refresh button
  document.getElementById('refresh-btn')?.addEventListener('click', () => {
    loadPageData(currentPage || 'main');
  });

  // Global search (Enter → stock lookup)
  document.getElementById('global-search')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      const v = e.target.value.trim();
      if (v) { goToStock(v.toUpperCase()); e.target.value = ''; }
    }
  });

  // Show first page
  showPage('main');
});

let currentPage = 'main';

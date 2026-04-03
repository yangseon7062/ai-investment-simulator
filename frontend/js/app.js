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

let logsLimit = 30;
const LOGS_STEP = 30;

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
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const page = document.getElementById('page-' + pageId);
  if (page) page.classList.add('active');

  document.querySelectorAll('.nav-link').forEach(n => {
    n.setAttribute('style', 'color:#9ca3af');
  });
  const active = document.querySelector(`.nav-link[data-page="${pageId}"]`);
  if (active) {
    active.setAttribute('style',
      'color:#7c6aff; background:rgba(124,106,255,.15); border-right:2px solid #7c6aff; font-weight:600;'
    );
  }

  const title = document.getElementById('page-title');
  if (title) title.textContent = PAGE_TITLES[pageId] || pageId;

  currentPage = pageId;
  loadPageData(pageId);
}

function loadPageData(pageId) {
  if (pageId === 'main')        loadMain();
  if (pageId === 'agents')      loadAgentsPage();
  if (pageId === 'logs')        { logsLimit = LOGS_STEP; loadLogs(); }
  if (pageId === 'debate')      loadDebate();
  if (pageId === 'roundtable')  loadRoundtable();
  if (pageId === 'data')        loadDataStatus();
}

// ── Page: 메인 ─────────────────────────────────────────────────
async function loadMain() {
  // 로딩 스피너 표시
  document.getElementById('banner-title').innerHTML =
    '<span class="inline-flex items-center gap-2"><span class="material-symbols-outlined animate-spin text-lg align-middle">progress_activity</span>서버 응답 대기 중…</span>';
  document.getElementById('banner-body').textContent = '(첫 로드 시 최대 30초 소요될 수 있습니다)';

  const [summary, portfolio, conflicts] = await Promise.all([
    apiFetch('/api/dashboard/summary').catch(() => ({})),
    apiFetch('/api/dashboard/portfolio').catch(() => []),
    apiFetch('/api/dashboard/conflicts').catch(() => []),
  ]);

  const snap = summary.snapshot || {};

  // 배너 업데이트
  document.getElementById('banner-title').textContent =
    snap.daily_summary || '오늘 시장 요약 없음 (데이터 수집 전)';
  const narrative = [snap.narrative_kr, snap.narrative_us].filter(Boolean).join(' | ');
  document.getElementById('banner-body').textContent = narrative || '';

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

  // Stitch 원본 카드 스타일 그대로
  el.innerHTML = AGENTS.map(agent => {
    const a = map[agent.id] || {};
    const ret = a.total_return || 0;
    const sign = ret >= 0 ? '+' : '';
    const retColor = ret > 0 ? 'text-success' : ret < 0 ? 'text-danger' : 'text-warning';
    return `
    <div class="bg-card p-4 rounded-xl border border-[#2a2f3e] hover:border-primary/50 transition-all group cursor-pointer"
         onclick="openAgentDetail('${agent.id}')">
      <div class="flex items-center justify-between mb-4">
        <div class="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 group-hover:bg-primary transition-colors"
             style="background:${agent.color}33">
          <span class="material-symbols-outlined text-sm" style="color:${agent.color}">${agent.icon}</span>
        </div>
        <span class="${retColor} text-xs font-bold">${sign}${ret.toFixed(2)}%</span>
      </div>
      <p class="text-xs font-bold text-white">${agent.name}</p>
      <p class="text-[10px] text-gray-500 uppercase tracking-tighter">${agent.style}</p>
      <div class="mt-2 pt-2 border-t border-[#2a2f3e] flex justify-between text-[10px] text-gray-600">
        <span>${(a.open_positions || 0)}종목</span>
        <span>${a.total_value_krw != null ? (a.total_value_krw/1e8).toFixed(1)+'억' : '—'}</span>
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
  // conflicts = debate 타입 로그 (실제 필드: id, agent_id, tickers, thesis, report_md, created_at)
  el.innerHTML = conflicts.slice(0, 4).map(c => {
    const summary = c.thesis || (c.report_md || '').replace(/[#*`\n]/g,'').slice(0, 80);
    return `
    <div class="p-4 rounded-xl border bg-danger/5 border-danger/20 cursor-pointer hover:opacity-90 transition-opacity"
         onclick="openReportModal(${c.id})">
      <div class="flex items-center justify-between mb-2">
        <span class="text-[10px] font-bold uppercase text-danger">의견 대립</span>
        <span class="text-[10px] font-mono text-primary/70">${c.tickers || ''}</span>
      </div>
      <p class="text-sm font-bold text-white mb-1 truncate">${summary.slice(0,40) || '—'}</p>
      <p class="text-xs text-gray-400 truncate">${summary.slice(40,100)}</p>
    </div>`;
  }).join('');
}

function renderUnifiedPortfolio(portfolio) {
  const el = document.getElementById('unified-portfolio');
  if (!el) return;
  if (!portfolio.length) {
    el.innerHTML = '<tr><td colspan="4" class="px-5 py-8 text-center text-gray-600 text-xs">포트폴리오 없음</td></tr>';
    return;
  }
  // Stitch 원본 포트폴리오 row 스타일
  el.innerHTML = portfolio.slice(0, 10).map(p => {
    const agentCount = p.agent_count || 0;
    const countColor = agentCount >= 4 ? 'text-primary font-bold' : agentCount >= 2 ? 'text-gray-300' : 'text-gray-500';
    const statusBg = agentCount >= 3 ? 'bg-success/10 text-success' : 'bg-gray-800 text-gray-400';
    return `
    <tr class="hover:bg-white/5 transition-colors cursor-pointer" onclick="goToStock('${p.ticker}')">
      <td class="px-6 py-4">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 bg-[#2a2f3e] rounded flex items-center justify-center text-[10px] font-bold text-white">${(p.ticker||'').slice(0,4)}</div>
          <div>
            <p class="text-sm font-bold text-white">${p.name || p.ticker}</p>
            <p class="text-[10px] text-gray-500">${p.market}</p>
          </div>
        </div>
      </td>
      <td class="px-6 py-4 text-sm text-gray-400">${p.market}</td>
      <td class="px-6 py-4 text-sm text-gray-500">${p.sector || '—'}</td>
      <td class="px-6 py-4 text-sm ${countColor}">${agentCount}명 보유</td>
      <td class="px-6 py-4 text-right">
        <span class="px-2 py-1 text-[10px] font-bold rounded ${statusBg}">${agentCount >= 3 ? 'HOT' : 'HOLD'}</span>
      </td>
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
  logsLimit = LOGS_STEP;
  await _fetchAndRenderLogs();
}

async function loadMoreLogs() {
  logsLimit += LOGS_STEP;
  await _fetchAndRenderLogs();
}

async function _fetchAndRenderLogs() {
  const list = document.getElementById('logs-list');
  list.innerHTML = '<div class="flex items-center gap-2 py-6 text-gray-600 text-xs"><span class="material-symbols-outlined animate-spin text-base">progress_activity</span>로딩 중…</div>';

  const agent = document.getElementById('log-agent-filter')?.value || '';
  const type  = document.getElementById('log-type-filter')?.value  || '';

  let url = `/api/logs/?limit=${logsLimit}`;
  if (agent) url += `&agent_id=${agent}`;
  if (type)  url += `&log_type=${type}`;

  const logs = await apiFetch(url).catch(() => []);
  renderLogList(list, logs);

  const btn = document.getElementById('load-more-logs');
  if (btn) btn.classList.toggle('hidden', logs.length < logsLimit);
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
  const cost  = summary.api_cost || {};
  const snap  = summary.snapshot || {};
  const macro = (() => { try { return JSON.parse(snap.macro_data || '{}'); } catch { return {}; } })();
  const fred  = macro.fred || {};

  const grid = document.getElementById('data-status-grid');
  grid.innerHTML = [
    { label: 'VIX (공포지수)',    value: macro.vix         != null ? macro.vix.toFixed(1)          : '—', icon: 'ssid_chart',        color: '#ef4444' },
    { label: 'Fear & Greed',      value: macro.fear_greed  != null ? macro.fear_greed.toFixed(0)    : '—', icon: 'sentiment_stressed', color: '#f59e0b' },
    { label: '미국 10년 국채',    value: fred['10Y_YIELD'] != null ? fred['10Y_YIELD'].toFixed(2)+'%': '—', icon: 'percent',            color: '#3b82f6' },
    { label: '10Y-2Y 스프레드',   value: fred.T10Y2Y       != null ? fred.T10Y2Y.toFixed(2)+'%'     : '—', icon: 'trending_flat',      color: '#8b5cf6' },
    { label: 'KR 시장 국면',      value: snap.regime_kr    || '—',                                         icon: 'flag',               color: '#10b981' },
    { label: 'US 시장 국면',      value: snap.regime_us    || '—',                                         icon: 'public',             color: '#06b6d4' },
    { label: '이번달 API 비용',   value: '$' + (cost.total_cost  || 0).toFixed(4),                         icon: 'payments',           color: '#22c55e' },
    { label: 'API 호출 횟수',     value: (cost.call_count  || 0) + '회',                                   icon: 'api',                color: '#7c6aff' },
  ].map(s => `
    <div class="bg-card border border-[#2a2f3e] rounded-2xl p-5">
      <span class="material-symbols-outlined text-xl mb-2 block" style="color:${s.color}">${s.icon}</span>
      <div class="text-lg font-bold text-white">${s.value}</div>
      <div class="text-xs text-gray-600 mt-1">${s.label}</div>
    </div>`).join('');

  const detail = document.getElementById('api-usage-detail');
  const rows = [
    snap.narrative_kr ? `<p class="mb-3"><span class="text-xs font-bold text-success bg-success/10 px-2 py-0.5 rounded mr-2">KR</span><span class="text-sm text-gray-400">${snap.narrative_kr}</span></p>` : '',
    snap.narrative_us ? `<p><span class="text-xs font-bold text-primary bg-primary/10 px-2 py-0.5 rounded mr-2">US</span><span class="text-sm text-gray-400">${snap.narrative_us}</span></p>` : '',
  ].filter(Boolean).join('');
  detail.innerHTML = rows || '<p class="text-gray-600 text-sm text-center py-4">데이터 없음 (매일 07:00 수집)</p>';
}

// ── Init (스크립트가 body 하단에 있으므로 DOM 이미 준비됨) ──────
document.getElementById('refresh-btn')?.addEventListener('click', () => {
  loadPageData(currentPage || 'main');
});

document.getElementById('global-search')?.addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    const v = e.target.value.trim();
    if (v) { goToStock(v.toUpperCase()); e.target.value = ''; }
  }
});

// 초기 메인 페이지 로드
showPage('main');

let currentPage = 'main';

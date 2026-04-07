// ── Constants ──────────────────────────────────────────────────
const AGENTS = [
  { id:'macro',      name:'매크로',    icon:'public',        color:'#7c6aff', style:'거시테마형' },
  { id:'strategist', name:'전략가',    icon:'analytics',     color:'#3b82f6', style:'퀄리티형' },
  { id:'surfer',     name:'서퍼',      icon:'trending_up',   color:'#f59e0b', style:'모멘텀형' },
  { id:'explorer',   name:'미래탐색자',icon:'rocket_launch', color:'#ec4899', style:'성장테마형' },
  { id:'bear',       name:'베어',      icon:'trending_down', color:'#ef4444', style:'하락베팅형' },
];

const PAGE_TITLES = {
  main:'메인', agents:'에이전트', logs:'로그',
  stocks:'종목뷰', debate:'토론', roundtable:'라운드테이블', data:'데이터현황',
};

let logsLimit = 30;
const LOGS_STEP = 30;
let notifOpen = false;
let notifLoaded = false;

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

// ── Notifications ──────────────────────────────────────────────
function toggleNotifications() {
  notifOpen = !notifOpen;
  document.getElementById('notif-dropdown').classList.toggle('hidden', !notifOpen);
  if (notifOpen && !notifLoaded) loadNotifications();
}

async function loadNotifications() {
  const list = document.getElementById('notif-list');
  list.innerHTML = '<div class="px-4 py-4 text-xs text-gray-600 text-center"><span class="material-symbols-outlined animate-spin text-sm align-middle">progress_activity</span></div>';
  const events = await apiFetch('/api/dashboard/notifications').catch(() => []);
  notifLoaded = true;
  if (!events.length) {
    list.innerHTML = '<div class="px-4 py-6 text-xs text-gray-600 text-center">이벤트 없음</div>';
    return;
  }
  const dot = document.getElementById('notif-dot');
  if (dot) dot.classList.remove('hidden');
  list.innerHTML = events.map(e => `
    <div class="px-4 py-3 hover:bg-white/[.03] border-b border-[#2a2f3e] last:border-0">
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0">
          <span class="text-xs font-semibold text-white">${e.event_type || '이벤트'}</span>
          ${e.description ? `<p class="text-[11px] text-gray-500 mt-0.5 truncate">${e.description}</p>` : ''}
        </div>
        <span class="text-[10px] text-gray-600 shrink-0">${formatTs(e.created_at)}</span>
      </div>
    </div>`).join('');
}

document.addEventListener('click', e => {
  const dropdown = document.getElementById('notif-dropdown');
  const btn = document.getElementById('notif-btn');
  if (notifOpen && dropdown && btn && !dropdown.contains(e.target) && !btn.contains(e.target)) {
    notifOpen = false;
    dropdown.classList.add('hidden');
  }
});

// ── Navigation ─────────────────────────────────────────────────
function showPage(pageId) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const page = document.getElementById('page-' + pageId);
  if (page) page.classList.add('active');

  document.querySelectorAll('.nav-link').forEach(n => {
    n.classList.remove('nav-active');
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

  const [summary, portfolio, conflicts, agentsList, consensus, sectorWarnings] = await Promise.all([
    apiFetch('/api/dashboard/summary').catch(() => ({})),
    apiFetch('/api/dashboard/portfolio').catch(() => []),
    apiFetch('/api/dashboard/conflicts').catch(() => []),
    apiFetch('/api/agents/').catch(() => []),
    apiFetch('/api/dashboard/consensus').catch(() => []),
    apiFetch('/api/dashboard/sector-concentration').catch(() => []),
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

  // Agent cards — prefer /api/agents/ (has cash_krw + daily_return)
  renderAgentCards(agentsList.length ? agentsList : (summary.agents || []));

  // Performance chart
  await loadPerformanceChart();

  // Conflicts
  renderConflicts(conflicts);

  // Portfolio table
  renderUnifiedPortfolio(portfolio);

  // 섹터 집중도 경고
  renderSectorConcentrationWarning(sectorWarnings);

  // 중복 추천 섹션
  renderConsensus(consensus);

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

// 최신 행동 표시용 설정
const ACTION_LABELS = {
  buy:  { label: 'BUY',  cls: 'text-success bg-success/10' },
  hold: { label: 'HOLD', cls: 'text-yellow-400 bg-yellow-400/10' },
  pass: { label: 'PASS', cls: 'text-gray-400 bg-gray-700/30' },
  monitor: { label: 'MON', cls: 'text-gray-500 bg-gray-800/50' },
};

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

    // 베어: 손실이 정상일 수 있음 — 색상 반전
    const isBear = agent.id === 'bear';
    const retColor = isBear
      ? (ret >= 0 ? 'text-success' : 'text-gray-400')
      : (ret > 0 ? 'text-success' : ret < 0 ? 'text-danger' : 'text-warning');

    // 베어 상태 설명
    let bearNote = '';
    if (isBear) {
      if (ret < 0) bearNote = '<span class="text-[9px] text-gray-500 ml-1">(상승장 정상)</span>';
      else if (!a.today_action || a.today_action === 'pass') bearNote = '<span class="text-[9px] text-gray-500 ml-1">(조건 미충족)</span>';
    }

    const daily = a.daily_return || 0;
    const dailySign = daily >= 0 ? '+' : '';
    const dailyColor = daily > 0 ? 'text-success' : daily < 0 ? 'text-danger' : 'text-gray-600';

    // MDD — 항상 표시 (0이면 —)
    const mdd = a.mdd || 0;
    const mddHtml = mdd < 0
      ? `<span class="${mdd < -5 ? 'text-danger/80' : 'text-gray-500'}">MDD ${mdd.toFixed(1)}%</span>`
      : `<span class="text-gray-700">MDD —</span>`;

    // 최신 행동 섹션
    let actionHtml = '';
    if (a.today_action) {
      const cfg = ACTION_LABELS[a.today_action] || ACTION_LABELS['pass'];
      const ticker = a.today_ticker ? `<span class="font-mono text-primary/80 ml-1">${a.today_ticker}</span>` : '';
      const confBadge = a.today_confidence ? confidenceBadge(a.today_confidence) : '';
      const dateStr = a.today_action_at ? formatTs(a.today_action_at) : '';
      actionHtml = `
      <div class="mt-2 pt-2 border-t border-[#2a2f3e]">
        <div class="flex items-center gap-1 flex-wrap">
          <span class="text-[10px] px-1.5 py-0.5 rounded font-bold ${cfg.cls}">${cfg.label}</span>
          ${ticker}
          ${confBadge}
          <span class="text-[9px] text-gray-600 ml-auto">${dateStr}</span>
        </div>
      </div>`;
    }

    return `
    <div class="bg-card p-4 rounded-xl border border-[#2a2f3e] hover:border-primary/50 transition-all group cursor-pointer"
         onclick="openAgentDetail('${agent.id}')">
      <div class="flex items-center justify-between mb-3">
        <div class="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 group-hover:bg-primary transition-colors"
             style="background:${agent.color}33">
          <span class="material-symbols-outlined text-sm" style="color:${agent.color}">${agent.icon}</span>
        </div>
        <span class="${retColor} text-xs font-bold">${sign}${ret.toFixed(2)}%${bearNote}</span>
      </div>
      <p class="text-xs font-bold text-white">${agent.name}</p>
      <p class="text-[10px] text-gray-500 uppercase tracking-tighter">${agent.style}</p>
      <div class="mt-2 pt-2 border-t border-[#2a2f3e] flex justify-between text-[10px]">
        <span class="text-gray-600">${(a.open_positions || 0)}종목</span>
        <span class="${dailyColor}">일간 ${dailySign}${daily.toFixed(2)}%</span>
      </div>
      <div class="mt-1 text-[10px]">${mddHtml}</div>
      ${actionHtml}
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

function renderSectorConcentrationWarning(warnings) {
  const el = document.getElementById('sector-concentration-warning');
  if (!el) return;
  if (!warnings || !warnings.length) {
    el.classList.add('hidden');
    return;
  }
  el.classList.remove('hidden');
  el.innerHTML = `
    <div class="bg-warning/5 border border-warning/30 rounded-2xl p-4 flex items-start gap-3">
      <span class="material-symbols-outlined text-warning text-xl shrink-0 mt-0.5">warning</span>
      <div>
        <p class="text-xs font-bold text-warning mb-1">섹터 집중도 경고</p>
        <div class="space-y-0.5">
          ${warnings.map(w => `
            <p class="text-xs text-gray-400">${w.description || w.msg || ''}</p>
          `).join('')}
        </div>
        <p class="text-[10px] text-gray-600 mt-1">특정 섹터 60% 이상 집중 — 분산 투자 권장</p>
      </div>
    </div>`;
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

function renderConsensus(consensus) {
  const el = document.getElementById('consensus-section');
  if (!el) return;
  if (!consensus || !consensus.length) {
    el.innerHTML = '<p class="text-xs text-gray-600 py-2">중복 보유 종목 없음</p>';
    return;
  }
  el.innerHTML = consensus.map(c => {
    const agentBadges = (c.agents || []).map(id => {
      const agent = AGENTS.find(a => a.id === id);
      if (!agent) return `<span class="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 text-gray-400">${id}</span>`;
      return `<span class="text-[10px] px-1.5 py-0.5 rounded font-medium" style="background:${agent.color}22;color:${agent.color}">${agent.name}</span>`;
    }).join('');

    // 이유 비교 (thesis)
    const details = c.agent_details || [];
    const reasonRows = details.map(d => {
      const agent = AGENTS.find(a => a.id === d.agent_id);
      const color = agent ? agent.color : '#888';
      const name = agent ? agent.name : d.agent_id;
      return `<div class="flex gap-2 text-[10px] mt-1">
        <span class="shrink-0 font-medium" style="color:${color}">${name}</span>
        <span class="text-gray-400">${d.thesis || '테제 없음'}</span>
      </div>`;
    }).join('');

    const sameLabel = c.same_reason === true
      ? '<span class="text-[9px] text-warning/80 ml-1">같은 이유</span>'
      : c.same_reason === false
        ? '<span class="text-[9px] text-primary/80 ml-1">다른 이유</span>'
        : '';

    return `
    <div class="bg-card border border-gray-800 rounded-xl p-3 mb-2">
      <div class="flex items-center gap-2 mb-1.5">
        <span class="text-xs font-bold text-white">${c.name || c.ticker}</span>
        <span class="text-[10px] text-gray-500">${c.ticker} · ${c.market}</span>
        ${sameLabel}
        <span class="ml-auto text-[10px] text-gray-500">${c.agent_count}개 에이전트</span>
      </div>
      <div class="flex gap-1 flex-wrap mb-2">${agentBadges}</div>
      <div class="border-t border-gray-800/60 pt-2">${reasonRows}</div>
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
    <tr class="hover:bg-white/5 transition-colors cursor-pointer group" onclick="goToStock('${p.ticker}')" title="클릭하여 종목뷰에서 에이전트별 스탠스 비교">
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
        <div class="flex items-center justify-end gap-2">
          <span class="px-2 py-1 text-[10px] font-bold rounded ${statusBg}">${agentCount >= 3 ? 'HOT' : 'HOLD'}</span>
          <span class="material-symbols-outlined text-sm text-gray-600 group-hover:text-primary transition-colors">open_in_new</span>
        </div>
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

  const [positions, perf, postmortems] = await Promise.all([
    apiFetch(`/api/agents/${agentId}/positions`).catch(() => []),
    apiFetch(`/api/agents/${agentId}/performance`).catch(() => ({})),
    apiFetch(`/api/agents/${agentId}/postmortems`).catch(() => []),
  ]);

  const snapshots = perf.snapshots || [];
  const totalReturn = snapshots.length
    ? parseFloat(snapshots[snapshots.length-1].total_value_krw || 0).toFixed(2)
    : '0.00';
  const agentFullData = await apiFetch('/api/agents/').then(list => list.find(a => a.agent_id === agentId)).catch(() => null);

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

      <!-- Return info + MDD -->
      ${agentFullData ? `
      <div class="bg-card border border-gray-800/60 rounded-2xl p-4 flex flex-wrap gap-5 text-sm">
        <div><div class="text-xs text-gray-600 mb-0.5">보유 종목</div><div class="font-bold text-white">${agentFullData.open_positions || 0}개</div></div>
        <div><div class="text-xs text-gray-600 mb-0.5">누적 수익률</div>
          <div class="font-bold ${(agentFullData.total_return||0)>0?'text-success':(agentFullData.total_return||0)<0?'text-danger':'text-gray-400'}">
            ${(agentFullData.total_return||0)>=0?'+':''}${(agentFullData.total_return||0).toFixed(2)}%
          </div>
        </div>
        <div><div class="text-xs text-gray-600 mb-0.5">일간 수익률</div>
          <div class="font-bold ${(agentFullData.daily_return||0)>0?'text-success':(agentFullData.daily_return||0)<0?'text-danger':'text-gray-400'}">
            ${(agentFullData.daily_return||0)>=0?'+':''}${(agentFullData.daily_return||0).toFixed(2)}%
          </div>
        </div>
        <div><div class="text-xs text-gray-600 mb-0.5">고점 수익률</div>
          <div class="font-bold text-gray-300">+${(perf.peak_return||0).toFixed(2)}%</div>
        </div>
        <div><div class="text-xs text-gray-600 mb-0.5">MDD (최대 낙폭)</div>
          <div class="font-bold ${(perf.mdd||0)<-5?'text-danger':'text-gray-400'}">${(perf.mdd||0).toFixed(2)}%</div>
        </div>
        <div><div class="text-xs text-gray-600 mb-0.5">현재 낙폭</div>
          <div class="font-bold ${(perf.current_drawdown||0)<-3?'text-warning':'text-gray-400'}">${(perf.current_drawdown||0).toFixed(2)}%</div>
        </div>
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
                <th class="px-5 py-3 text-right">매수가</th>
                <th class="px-5 py-3 text-right">수익률</th>
                <th class="px-5 py-3">상태</th>
                <th class="px-5 py-3">섹터</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-800/40">
              ${positions.map(p => {
                const pnl = p.pnl_pct != null ? parseFloat(p.pnl_pct) : null;
                const pnlHtml = pnl != null
                  ? `<span class="${pnl > 0 ? 'text-success' : pnl < 0 ? 'text-danger' : 'text-gray-400'} font-bold">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%</span>`
                  : '<span class="text-gray-600">-</span>';
                return `
              <tr class="hover:bg-white/[.025]">
                <td class="px-5 py-3">
                  <span class="font-semibold text-white">${p.name || p.ticker}</span>
                  <span class="text-gray-600 ml-1">${p.ticker}</span>
                </td>
                <td class="px-5 py-3 text-gray-500">${p.market}</td>
                <td class="px-5 py-3 text-right text-gray-400">${(p.price || 0).toLocaleString()}</td>
                <td class="px-5 py-3 text-right">${pnlHtml}</td>
                <td class="px-5 py-3 status-${p.status}">${{buy:'매수',hold:'보유',watch:'경계',closed:'종료'}[p.status] || p.status}</td>
                <td class="px-5 py-3 text-gray-600">${p.sector || '-'}</td>
              </tr>`;
              }).join('') || '<tr><td colspan="6" class="px-5 py-8 text-center text-gray-600">포지션 없음</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>

      <!-- Postmortems -->
      ${postmortems.length ? `
      <div class="bg-card border border-gray-800/60 rounded-2xl overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-800/60">
          <h4 class="text-xs font-bold text-gray-400 uppercase">사후 검증 (${postmortems.length})</h4>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-xs text-left data-table">
            <thead class="bg-[#0f1117] text-gray-600 uppercase tracking-wider">
              <tr>
                <th class="px-5 py-3">종목</th>
                <th class="px-5 py-3 text-right">수익률</th>
                <th class="px-5 py-3 text-right">환율반영</th>
                <th class="px-5 py-3">적중</th>
                <th class="px-5 py-3">날짜</th>
                <th class="px-5 py-3"></th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-800/40">
              ${postmortems.map(pm => {
                const pnl = pm.pnl_pct || 0;
                const pnlClass = pnl > 0 ? 'text-success' : pnl < 0 ? 'text-danger' : 'text-gray-500';
                const pnlKrw = pm.pnl_pct_krw;
                const correct = pm.was_correct;
                return `<tr class="hover:bg-white/[.025]">
                  <td class="px-5 py-3 font-semibold text-white">${pm.ticker}</td>
                  <td class="px-5 py-3 text-right ${pnlClass}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%</td>
                  <td class="px-5 py-3 text-right ${pnlKrw != null ? (pnlKrw > 0 ? 'text-success' : pnlKrw < 0 ? 'text-danger' : 'text-gray-500') : 'text-gray-600'}">
                    ${pnlKrw != null ? (pnlKrw >= 0 ? '+' : '') + pnlKrw.toFixed(2) + '%' : '-'}
                  </td>
                  <td class="px-5 py-3">
                    ${correct === true ? '<span class="text-success font-bold">✓ 맞음</span>' : correct === false ? '<span class="text-danger font-bold">✗ 틀림</span>' : '<span class="text-gray-600">-</span>'}
                  </td>
                  <td class="px-5 py-3 text-gray-600">${formatTs(pm.created_at)}</td>
                  <td class="px-5 py-3"><button onclick="openReportModal(${pm.id})" class="text-primary/60 hover:text-primary text-[10px]">리포트</button></td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>
      </div>` : ''}
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

  const agent    = document.getElementById('log-agent-filter')?.value || '';
  const type     = document.getElementById('log-type-filter')?.value  || '';
  const fromDate = document.getElementById('log-from-date')?.value   || '';
  const toDate   = document.getElementById('log-to-date')?.value     || '';

  let url = `/api/logs/?limit=${logsLimit}`;
  if (agent)    url += `&agent_id=${agent}`;
  if (type)     url += `&log_type=${type}`;
  if (fromDate) url += `&from_date=${fromDate}`;
  if (toDate)   url += `&to_date=${toDate}`;

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

// ── 온디맨드 종목 분석 ─────────────────────────────────────────
const AGENT_NAME_KR = {
  macro: '매크로', strategist: '전략가',
  surfer: '서퍼', explorer: '미래탐색자', bear: '베어',
};
const DECISION_LABEL = { buy: '매수', hold: '관망', pass: '패스' };
const DECISION_COLOR = { buy: '#22c55e', hold: '#f59e0b', pass: '#6b7280' };

async function runAnalyze() {
  const ticker = document.getElementById('analyze-ticker').value.trim().toUpperCase();
  const market = document.getElementById('analyze-market').value;
  if (!ticker) { alert('종목 코드를 입력하세요'); return; }

  const checked = [...document.querySelectorAll('.analyze-agent-chk:checked')].map(el => el.value);

  const btn = document.getElementById('analyze-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-base">progress_activity</span>분석 중…';

  const resultEl = document.getElementById('analyze-result');
  const headerEl = document.getElementById('analyze-header');
  const cardsEl  = document.getElementById('analyze-cards');
  resultEl.classList.add('hidden');
  cardsEl.innerHTML = '';

  try {
    // 온디맨드 분석은 에이전트 수 × 10초 + LLM 처리 시간 → 타임아웃 5분
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 300000);
    let data;
    try {
      const r = await fetch('/api/analyze/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, market, agents: checked }),
        signal: controller.signal,
      });
      clearTimeout(timer);
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      data = await r.json();
    } catch (fetchErr) {
      clearTimeout(timer);
      throw fetchErr;
    }

    const agentIds = Object.keys(data.results);
    headerEl.innerHTML = `
      <span class="font-semibold text-white">${data.name} (${ticker})</span>
      <span class="text-gray-600 mx-2">|</span>
      현재가 ${data.price ? data.price.toLocaleString() : '-'}
      <span class="text-gray-600 mx-2">|</span>
      ${agentIds.length}개 에이전트 분석 완료`;

    cardsEl.innerHTML = agentIds.map(agentId => {
      const r = data.results[agentId];
      const decision = r.decision || 'pass';
      const color = DECISION_COLOR[decision] || '#6b7280';
      const label = DECISION_LABEL[decision] || decision;
      const confidence = r.confidence || '';
      const confBadge = confidence
        ? `<span class="text-xs px-2 py-0.5 rounded-full bg-white/10 text-gray-400">${{ low:'낮음', medium:'보통', high:'높음' }[confidence] || confidence}</span>`
        : '';
      const reportHtml = r.report_md ? renderMarkdown(r.report_md) : '<p class="text-gray-600">리포트 없음</p>';

      return `
        <div class="bg-[#0f1117] border border-[#2a2f3e] rounded-2xl overflow-hidden">
          <div class="px-5 py-4 border-b border-[#2a2f3e] flex items-center justify-between">
            <span class="font-bold text-white text-sm">${AGENT_NAME_KR[agentId] || agentId}</span>
            <div class="flex items-center gap-2">
              ${confBadge}
              <span class="text-sm font-bold" style="color:${color}">${label}</span>
            </div>
          </div>
          <div class="px-5 py-4 prose prose-invert prose-sm max-w-none text-gray-400 text-xs leading-relaxed">
            ${reportHtml}
          </div>
        </div>`;
    }).join('');

    resultEl.classList.remove('hidden');
  } catch (e) {
    alert('분석 실패: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="material-symbols-outlined text-base">search</span>분석 실행';
  }
}

// ── Page: 데이터현황 ───────────────────────────────────────────
async function loadDataStatus() {
  const [summary, sectors] = await Promise.all([
    apiFetch('/api/dashboard/summary').catch(() => ({})),
    apiFetch('/api/dashboard/sectors').catch(() => []),
  ]);
  const cost  = summary.api_cost || {};
  const snap  = summary.snapshot || {};
  const macro = (() => { try { return JSON.parse(snap.macro_data || '{}'); } catch { return {}; } })();
  const fred  = macro.fred || {};

  const grid = document.getElementById('data-status-grid');
  grid.innerHTML = [
    { label: 'VIX (공포지수)',    value: macro.vix         != null ? macro.vix.toFixed(1)          : '—', icon: 'ssid_chart',        color: '#ef4444' },
    { label: 'Fear & Greed',      value: macro.fear_greed  != null ? (typeof macro.fear_greed === 'object' ? (macro.fear_greed.value ?? '—') : Number(macro.fear_greed).toFixed(0)) : '—', icon: 'sentiment_stressed', color: '#f59e0b' },
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

  // Sector ETF table
  const etfTbody = document.getElementById('sector-etf-table');
  if (etfTbody) {
    if (!sectors.length) {
      etfTbody.innerHTML = '<tr><td colspan="6" class="px-5 py-8 text-center text-gray-600 text-xs">데이터 없음</td></tr>';
    } else {
      const retCell = (v) => {
        if (v == null) return '<td class="px-5 py-3 text-right text-gray-600">—</td>';
        const cls = v > 0 ? 'text-success' : v < 0 ? 'text-danger' : 'text-gray-500';
        return `<td class="px-5 py-3 text-right ${cls}">${v >= 0 ? '+' : ''}${v.toFixed(2)}%</td>`;
      };
      etfTbody.innerHTML = sectors.map(s => `
        <tr class="hover:bg-white/[.025]">
          <td class="px-5 py-3">
            <span class="text-[10px] font-bold px-1.5 py-0.5 rounded ${s.market === 'KR' ? 'bg-success/10 text-success' : 'bg-primary/10 text-primary'}">${s.market}</span>
          </td>
          <td class="px-5 py-3 font-mono text-white text-xs">${s.etf_ticker}</td>
          <td class="px-5 py-3 text-gray-400">${s.etf_name || '-'}</td>
          ${retCell(s.return_1d)}
          ${retCell(s.return_5d)}
          ${retCell(s.return_20d)}
        </tr>`).join('');
    }
  }
}

// ── Init (스크립트가 body 하단에 있으므로 DOM 이미 준비됨) ──────
let currentPage = 'main';
showPage('main');

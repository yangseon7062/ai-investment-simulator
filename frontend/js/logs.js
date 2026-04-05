/**
 * logs.js — Log rendering helpers for AI 투자 시뮬레이터
 */

// ── Constants ─────────────────────────────────────────────────
const LOG_TYPE_LABELS = {
    research:    '조사',
    buy:         '매수',
    sell:        '매도',
    monitor:     '모니터',
    hold:        '관망',       // 관심 있음, 조건 대기
    pass:        '패스',       // 전략 기준 대상 없음
    postmortem:  '사후검증',
    debate:      '토론',
    roundtable:  '라운드테이블',
};

const LOG_TYPE_CHIPS = {
    research:    'chip-research',
    buy:         'chip-buy',
    sell:        'chip-sell',
    monitor:     'chip-monitor',
    hold:        'chip-monitor',   // 관망 — 모니터와 유사한 톤
    pass:        'chip-pass',
    postmortem:  'chip-postmortem',
    debate:      'chip-debate',
    roundtable:  'chip-roundtable',
};

const THESIS_VALIDITY_LABELS = {
    true:  { label: '유효', cls: 'text-success bg-success/10' },
    false: { label: '무효', cls: 'text-danger  bg-danger/10' },
    null:  { label: '미정', cls: 'text-gray-400 bg-gray-700/30' },
};

// ── Markdown renderer ──────────────────────────────────────────
function renderMarkdown(md) {
    if (!md) return '<p class="text-gray-500">내용 없음</p>';
    return md
        .replace(/^### (.+)/gm, '<h3 class="text-sm font-bold text-white mt-3 mb-1">$1</h3>')
        .replace(/^## (.+)/gm,  '<h2 class="text-base font-bold text-primary mt-4 mb-2">$1</h2>')
        .replace(/^# (.+)/gm,   '<h1 class="text-lg font-bold text-white mt-4 mb-2">$1</h1>')
        .replace(/\*\*(.+?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
        .replace(/\*(.+?)\*/g,     '<em class="text-gray-300">$1</em>')
        .replace(/^- (.+)/gm,   '<li class="ml-4 text-gray-400 list-disc">$1</li>')
        .replace(/\n\n/g, '<br><br>')
        .replace(/\n/g, '<br>');
}

// ── Format timestamp ───────────────────────────────────────────
function formatTs(str) {
    if (!str) return '';
    try {
        const d = new Date(str);
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const dd = String(d.getDate()).padStart(2, '0');
        const hh = String(d.getHours()).padStart(2, '0');
        const mi = String(d.getMinutes()).padStart(2, '0');
        return `${mm}/${dd} ${hh}:${mi}`;
    } catch { return str.slice(0, 16).replace('T', ' '); }
}

// ── Agent badge HTML ───────────────────────────────────────────
function agentBadge(agentId) {
    const agent = AGENTS.find(a => a.id === agentId);
    if (!agent) return `<span class="text-xs px-2 py-0.5 rounded-full bg-gray-700/40 text-gray-400">${agentId || '시스템'}</span>`;
    return `<span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium"
                  style="background:${agent.color}22; color:${agent.color}; border:1px solid ${agent.color}44">
                <span class="material-symbols-outlined" style="font-size:12px">${agent.icon}</span>
                ${agent.name}
            </span>`;
}

// ── Log type chip HTML ─────────────────────────────────────────
function logTypeChip(logType) {
    const cls   = LOG_TYPE_CHIPS[logType] || 'chip-pass';
    const label = LOG_TYPE_LABELS[logType] || logType;
    return `<span class="text-xs px-2 py-0.5 rounded-full font-medium ${cls}">${label}</span>`;
}

// ── Confidence badge ───────────────────────────────────────────
const CONFIDENCE_LABELS = {
    high:   { label: '확신 높음', cls: 'text-success bg-success/10' },
    medium: { label: '확신 중간', cls: 'text-yellow-400 bg-yellow-400/10' },
    low:    { label: '확신 낮음', cls: 'text-gray-400 bg-gray-700/30' },
};
function confidenceBadge(confidence) {
    if (!confidence) return '';
    const cfg = CONFIDENCE_LABELS[confidence] || CONFIDENCE_LABELS['low'];
    return `<span class="text-xs px-2 py-0.5 rounded-full font-medium ${cfg.cls}">${cfg.label}</span>`;
}

// ── Thesis validity badge ──────────────────────────────────────
function thesisBadge(wasCorrect) {
    const key = wasCorrect === null || wasCorrect === undefined ? 'null' : String(wasCorrect);
    const cfg = THESIS_VALIDITY_LABELS[key] || THESIS_VALIDITY_LABELS['null'];
    return `<span class="text-xs px-2 py-0.5 rounded-full font-medium ${cfg.cls}">${cfg.label}</span>`;
}

// ── Regime badge ──────────────────────────────────────────────
function regimeBadge(market, regime) {
    if (!regime) return '';
    const cls = regime === '상승장' ? 'regime-up'
              : regime === '하락장' ? 'regime-down'
              : regime === '변동성급등' ? 'regime-vol'
              : 'regime-side';
    return `<span class="text-[9px] px-1.5 py-0.5 rounded-full font-bold ${cls}">${market} ${regime}</span>`;
}

// ── 토론 요약 블록 파싱 ───────────────────────────────────────
function parseDebateSummary(reportMd) {
    if (!reportMd) return null;
    // "## 📋 요약" 섹션에서 항목 추출
    const summaryMatch = reportMd.match(/##\s*📋\s*요약([\s\S]*?)(?=\n##\s|\n---|\n# |$)/);
    if (!summaryMatch) return null;
    const block = summaryMatch[1];
    const extract = (label) => {
        const m = block.match(new RegExp(`\\*\\*${label}\\*\\*[:\\s]*([^\\n]+)`));
        return m ? m[1].replace(/\*\*/g, '').trim() : null;
    };
    return {
        ticker:    extract('종목'),
        sides:     extract('대립 구도'),
        issue:     extract('핵심 쟁점'),
        conclusion:extract('결론'),
    };
}

// ── Render a single collapsible log card ──────────────────────
let _logCardCounter = 0;
function renderLogCard(log, index) {
    const summary = (log.thesis || log.report_md || '')
        .replace(/[#*\-`]/g, '').trim().slice(0, 140);

    const tickers = log.tickers
        ? `<span class="text-xs font-mono text-primary/80">${log.tickers}</span>`
        : '';

    const regimes = [
        regimeBadge('KR', log.market_regime_kr),
        regimeBadge('US', log.market_regime_us),
    ].filter(Boolean).join('');

    const bodyId = `log-body-${++_logCardCounter}`;

    // 토론 요약 블록 (debate 타입만)
    let debateSummaryHtml = '';
    if (log.log_type === 'debate' && log.report_md) {
        const ds = parseDebateSummary(log.report_md);
        if (ds) {
            debateSummaryHtml = `
        <div class="px-4 pb-3 grid grid-cols-1 gap-1 pointer-events-none">
            ${ds.sides     ? `<div class="text-[10px]"><span class="text-gray-600 mr-1">대립:</span><span class="text-gray-300">${ds.sides}</span></div>` : ''}
            ${ds.issue     ? `<div class="text-[10px]"><span class="text-gray-600 mr-1">쟁점:</span><span class="text-gray-400">${ds.issue}</span></div>` : ''}
            ${ds.conclusion? `<div class="text-[10px]"><span class="text-warning/80 mr-1">결론:</span><span class="text-gray-300">${ds.conclusion}</span></div>` : ''}
        </div>`;
        }
    }

    return `
    <div class="bg-card border border-gray-800 rounded-xl mb-2 overflow-hidden transition-all">
        <div class="flex items-center gap-2 px-4 py-3 cursor-pointer hover:bg-white/[.03] select-none"
             onclick="toggleLogBody('${bodyId}', ${log.id})">
            ${agentBadge(log.agent_id)}
            ${logTypeChip(log.log_type)}
            ${tickers}
            ${regimes}
            <span class="ml-auto flex items-center gap-2 shrink-0">
                ${confidenceBadge(log.confidence)}
                ${thesisBadge(log.thesis_valid)}
                <span class="text-xs text-gray-600">${formatTs(log.created_at)}</span>
                <span class="material-symbols-outlined text-gray-600 text-sm expand-icon">expand_more</span>
            </span>
        </div>
        ${debateSummaryHtml || (summary ? `<p class="px-4 pb-2 text-xs text-gray-500 truncate pointer-events-none">${summary}…</p>` : '')}
        <div id="${bodyId}" class="log-body px-4 pb-4 border-t border-gray-800/60 pt-3 prose-report">
            <div class="text-xs text-gray-500 py-4 text-center">
                <span class="material-symbols-outlined animate-spin text-base align-middle">progress_activity</span>
                로딩 중…
            </div>
        </div>
    </div>`;
}

// ── Toggle log body (lazy-load report) ───────────────────────
async function toggleLogBody(bodyId, logId) {
    const body = document.getElementById(bodyId);
    if (!body) return;

    const card = body.closest('.bg-card');
    const icon = card?.querySelector('.expand-icon');

    if (body.classList.contains('open')) {
        body.classList.remove('open');
        if (icon) icon.textContent = 'expand_more';
        return;
    }

    body.classList.add('open');
    if (icon) icon.textContent = 'expand_less';

    // Already loaded?
    if (body.dataset.loaded === '1') return;

    try {
        const data = await apiFetch(`/api/logs/${logId}`);
        body.innerHTML = renderMarkdown(data.report_md || data.thesis || '내용 없음');
        body.dataset.loaded = '1';
    } catch {
        body.innerHTML = '<p class="text-gray-500 text-xs">리포트 로드 실패</p>';
    }
}

// ── Render log list into container ───────────────────────────
function renderLogList(container, logs) {
    if (!container) return;
    if (!logs || logs.length === 0) {
        container.innerHTML = `
            <div class="flex flex-col items-center justify-center py-16 text-gray-600">
                <span class="material-symbols-outlined text-4xl mb-2">inbox</span>
                <p class="text-sm">로그 없음</p>
            </div>`;
        return;
    }
    container.innerHTML = logs.map((l, i) => renderLogCard(l, i)).join('');
}

// ── Open full report in modal ─────────────────────────────────
async function openReportModal(logId) {
    showModal('<div class="text-center py-8 text-gray-500">로딩 중…</div>');
    try {
        const data = await apiFetch(`/api/logs/${logId}`);
        const agent = AGENTS.find(a => a.id === data.agent_id);
        const header = agent
            ? `<div class="flex items-center gap-2 mb-4">${agentBadge(data.agent_id)}${logTypeChip(data.log_type)}<span class="text-xs text-gray-500 ml-auto">${formatTs(data.created_at)}</span></div>`
            : '';
        updateModal(header + `<div class="prose-report">${renderMarkdown(data.report_md || data.thesis || '내용 없음')}</div>`);
    } catch {
        updateModal('<p class="text-danger text-sm">리포트 로드 실패</p>');
    }
}

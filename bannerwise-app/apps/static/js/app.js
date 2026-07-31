/* ===================================================
   Bannerwise Quality Agent — Client-Side Application
   All data fetched via API calls (mock-backed for now).
   =================================================== */

// --- Navigation Toggle ---
document.getElementById('navToggle').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('collapsed');
});

// ============================================================
// ASK PAGE
// ============================================================

function useExample(el) {
    document.getElementById('promptInput').value = el.textContent;
}

async function submitPrompt() {
    const input = document.getElementById('promptInput');
    const prompt = input.value.trim();
    if (!prompt) return;

    const btn = document.getElementById('submitBtn');
    const loading = document.getElementById('loadingIndicator');
    const response = document.getElementById('responseSection');

    // Show loading state
    btn.disabled = true;
    loading.classList.remove('hidden');
    response.classList.add('hidden');

    try {
        const result = await apiPost('/api/quality/assess', { prompt });
        renderResponse(result);
    } catch (err) {
        renderError(err.message);
    } finally {
        btn.disabled = false;
        loading.classList.add('hidden');
    }
}

function renderResponse(result) {
    const section = document.getElementById('responseSection');
    const isCertified = result.lane === 'certified';

    section.innerHTML = `
        <div class="response-card">
            <div class="response-badge ${isCertified ? 'badge-certified' : 'badge-analytical'}">
                <span>${isCertified ? '\u2705' : '\u26A0\uFE0F'} ${result.badge}</span>
                <span class="confidence-display">Confidence: ${(result.confidence * 100).toFixed(1)}%</span>
            </div>
            <div class="response-body">
                <div class="response-answer">${escapeHtml(result.answer)}</div>
                ${!isCertified ? `
                    <div class="response-warning">
                        This answer was generated dynamically and has not been certified by an SME.
                    </div>
                    <div class="response-actions">
                        <button class="btn btn-secondary" onclick="requestSMEReview()">Request SME Review</button>
                        <button class="btn btn-secondary" onclick="flagIncorrect()">Flag Incorrect</button>
                    </div>
                ` : ''}
                <div class="provenance-section">
                    <button class="provenance-toggle" onclick="toggleProvenance(this)">
                        \u25B6 Show Provenance
                    </button>
                    <dl class="provenance-details hidden">
                        ${renderProvenance(result.provenance)}
                    </dl>
                </div>
            </div>
        </div>
    `;
    section.classList.remove('hidden');
}

function renderProvenance(provenance) {
    return Object.entries(provenance).map(([key, value]) => `
        <dt>${formatKey(key)}</dt>
        <dd>${typeof value === 'object' ? JSON.stringify(value) : value}</dd>
    `).join('');
}

function toggleProvenance(btn) {
    const details = btn.nextElementSibling;
    const isHidden = details.classList.toggle('hidden');
    btn.textContent = isHidden ? '\u25B6 Show Provenance' : '\u25BC Hide Provenance';
}

function requestSMEReview() {
    alert('SME Review request submitted. This will be routed to the certification flywheel.');
}

function flagIncorrect() {
    alert('Flagged as incorrect. An admin will review this response.');
}

function renderError(message) {
    const section = document.getElementById('responseSection');
    section.innerHTML = `<div class="response-warning">Error: ${escapeHtml(message)}</div>`;
    section.classList.remove('hidden');
}

// ============================================================
// HISTORY PAGE
// ============================================================

async function loadHistory(laneFilter) {
    const params = laneFilter && laneFilter !== 'all' ? `?lane=${laneFilter}` : '';
    const data = await apiGet(`/api/history${params}`);
    renderHistoryStats(data.stats);
    renderHistoryTable(data.entries);
}

function filterHistory(lane) {
    // Update active button
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === lane);
    });
    loadHistory(lane);
}

function renderHistoryStats(stats) {
    const el = document.getElementById('historyStats');
    if (!el) return;
    el.innerHTML = `
        <span class="stat-item"><strong>${stats.total_queries}</strong> total queries</span>
        <span class="stat-item"><strong>${stats.certified_count}</strong> certified</span>
        <span class="stat-item"><strong>${stats.analytical_count}</strong> analytical</span>
        <span class="stat-item">Avg confidence: <strong>${(stats.avg_confidence * 100).toFixed(1)}%</strong></span>
    `;
}

function renderHistoryTable(entries) {
    const tbody = document.getElementById('historyTableBody');
    if (!tbody) return;
    tbody.innerHTML = entries.map(entry => `
        <tr>
            <td>${formatTimestamp(entry.timestamp)}</td>
            <td>${escapeHtml(entry.prompt)}</td>
            <td><span class="badge ${entry.lane === 'certified' ? 'badge-green' : 'badge-amber'}">${entry.badge}</span></td>
            <td>${(entry.confidence * 100).toFixed(1)}%</td>
            <td>${entry.latency_ms}ms</td>
        </tr>
    `).join('');
}

// ============================================================
// CORPUS PAGE
// ============================================================

async function loadCorpus(statusFilter, search) {
    let params = [];
    if (statusFilter && statusFilter !== 'all') params.push(`status=${statusFilter}`);
    if (search) params.push(`search=${encodeURIComponent(search)}`);
    const query = params.length ? '?' + params.join('&') : '';

    const data = await apiGet(`/api/corpus${query}`);
    renderCorpusStats(data.stats);
    renderCorpusTable(data.entries);
}

function filterCorpus(status) {
    document.querySelectorAll('.pill').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.status === status);
    });
    const search = document.getElementById('corpusSearch')?.value || '';
    loadCorpus(status, search);
}

function searchCorpus() {
    const search = document.getElementById('corpusSearch').value;
    const activeStatus = document.querySelector('.pill.active')?.dataset.status || 'all';
    loadCorpus(activeStatus, search);
}

function renderCorpusStats(stats) {
    const el = document.getElementById('corpusStats');
    if (!el) return;
    el.innerHTML = `
        <span class="stat-item"><strong>${stats.total}</strong> total</span>
        <span class="stat-item"><strong>${stats.certified}</strong> certified</span>
        <span class="stat-item"><strong>${stats.draft}</strong> draft</span>
        <span class="stat-item"><strong>${stats.expired}</strong> expired</span>
    `;
}

function renderCorpusTable(entries) {
    const tbody = document.getElementById('corpusTableBody');
    if (!tbody) return;
    tbody.innerHTML = entries.map(entry => {
        const statusClass = entry.status === 'certified' ? 'badge-green'
            : entry.status === 'expired' ? 'badge-red' : 'badge-gray';
        return `
            <tr onclick="showCorpusDetail('${entry.id}')" style="cursor:pointer">
                <td><code>${entry.id}</code></td>
                <td>${escapeHtml(entry.question)}</td>
                <td><span class="badge ${statusClass}">${entry.status}</span></td>
                <td>${entry.certified_by || '—'}</td>
                <td>${entry.next_review_date}</td>
            </tr>
        `;
    }).join('');
}

async function showCorpusDetail(entryId) {
    const entry = await apiGet(`/api/corpus/${entryId}`);
    const panel = document.getElementById('corpusDetail');
    if (!panel) return;

    panel.innerHTML = `
        <h3>${escapeHtml(entry.question)}</h3>
        <dl class="provenance-details">
            <dt>ID</dt><dd>${entry.id}</dd>
            <dt>Status</dt><dd>${entry.status}</dd>
            <dt>SQL</dt><dd><code>${escapeHtml(entry.parameterized_sql)}</code></dd>
            <dt>Answer Template</dt><dd>${escapeHtml(entry.answer_template)}</dd>
            <dt>Parameters</dt><dd>${entry.parameters.join(', ') || 'None'}</dd>
            <dt>Certified By</dt><dd>${entry.certified_by || '—'}</dd>
            <dt>Next Review</dt><dd>${entry.next_review_date}</dd>
        </dl>
    `;
    panel.classList.remove('hidden');
}

// ============================================================
// ADMIN PAGE
// ============================================================

async function loadAdminConfig() {
    const data = await apiGet('/api/admin/config');
    renderSystemStatus(data.system_status);
    renderCorpusAdminStats(data.corpus_stats);
    renderEndpointConfig(data.config);

    // Set threshold slider
    const slider = document.getElementById('thresholdSlider');
    if (slider) {
        slider.value = data.config.confidence_threshold * 100;
        updateThresholdDisplay();
    }
}

function renderSystemStatus(status) {
    const el = document.getElementById('systemStatus');
    if (!el) return;
    el.innerHTML = Object.entries(status).map(([key, value]) => `
        <div class="status-row">
            <span>${formatKey(key)}</span>
            <span class="status-indicator ${value === 'healthy' || value === 'active' ? 'healthy' : 'unhealthy'}"></span>
        </div>
    `).join('');
}

function renderCorpusAdminStats(stats) {
    const el = document.getElementById('adminCorpusStats');
    if (!el) return;
    el.innerHTML = `
        <div class="stat-card"><div class="stat-number">${stats.total}</div><div class="stat-label">Total Entries</div></div>
        <div class="stat-card"><div class="stat-number">${stats.certified}</div><div class="stat-label">Certified</div></div>
        <div class="stat-card"><div class="stat-number">${stats.draft}</div><div class="stat-label">Draft</div></div>
        <div class="stat-card"><div class="stat-number">${stats.expired}</div><div class="stat-label">Expired</div></div>
    `;
}

function renderEndpointConfig(config) {
    const el = document.getElementById('endpointConfig');
    if (!el) return;
    el.innerHTML = Object.entries(config).filter(([k]) => k !== 'confidence_threshold').map(([key, value]) => `
        <div class="config-row">
            <span>${formatKey(key)}</span>
            <code style="font-size:0.75rem">${value}</code>
        </div>
    `).join('');
}

function updateThresholdDisplay() {
    const slider = document.getElementById('thresholdSlider');
    const display = document.getElementById('thresholdValue');
    if (slider && display) {
        display.textContent = (slider.value / 100).toFixed(2);
    }
}

async function saveThreshold() {
    const value = document.getElementById('thresholdSlider').value / 100;
    await apiPut('/api/admin/config', { confidence_threshold: value });
    alert(`Threshold updated to ${value.toFixed(2)}`);
}

// ============================================================
// API HELPERS (swap these for real endpoint calls later)
// ============================================================

async function apiGet(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return response.json();
}

async function apiPost(url, data) {
    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return response.json();
}

async function apiPut(url, data) {
    const response = await fetch(url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    return response.json();
}

// ============================================================
// UTILITIES
// ============================================================

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatKey(key) {
    return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function formatTimestamp(iso) {
    const d = new Date(iso);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// Allow Enter key to submit on Ask page
document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        const input = document.getElementById('promptInput');
        if (input && document.activeElement === input) {
            e.preventDefault();
            submitPrompt();
        }
    }
});

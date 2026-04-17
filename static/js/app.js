/**
 * Social Media Manager - Dashboard Application
 */

const API_BASE = '/social-admin-v2/api';
let TOKEN = '';
let accounts = [];
let currentAccountId = null;
let currentTab = 'queue';
let publishPollTimer = null;

// ── API Helpers ─────────────────────────────────────────────────────

async function api(method, path, body = null, isFormData = false) {
    const opts = {
        method,
        headers: { 'Authorization': `Bearer ${TOKEN}` },
    };
    if (body && !isFormData) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    } else if (body && isFormData) {
        opts.body = body;
    }
    const resp = await fetch(`${API_BASE}${path}`, opts);
    if (resp.status === 401) {
        showLogin();
        throw new Error('Unauthorized');
    }
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'API Error');
    return data;
}

function videoUrl(accountId, subdir, filename) {
    return `${API_BASE}/video-file/${accountId}/${subdir}/${filename}?token=${TOKEN}`;
}

// ── Toast ───────────────────────────────────────────────────────────

function toast(msg, type = 'info') {
    const container = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    const icons = { success: '\u2713', error: '\u2717', info: '\u2139' };
    el.innerHTML = `<span>${icons[type] || ''}</span><span>${msg}</span>`;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

// ── Login ───────────────────────────────────────────────────────────

function showLogin() {
    document.getElementById('login-screen').style.display = 'flex';
    document.getElementById('app').style.display = 'none';
    TOKEN = '';
    localStorage.removeItem('smm_token');
}

function showApp() {
    document.getElementById('login-screen').style.display = 'none';
    document.getElementById('app').style.display = 'grid';
}

async function doLogin() {
    const input = document.getElementById('login-password');
    const err = document.getElementById('login-error');
    const password = input.value.trim();
    if (!password) { err.textContent = 'Podaj has\u0142o'; err.style.display = 'block'; return; }
    try {
        const resp = await fetch(`${API_BASE}/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            err.textContent = data.detail || 'Nieprawid\u0142owe has\u0142o';
            err.style.display = 'block';
            return;
        }
        TOKEN = data.token;
        localStorage.setItem('smm_token', TOKEN);
        err.style.display = 'none';
        showApp();
        loadAccounts();
    } catch (e) {
        err.textContent = 'B\u0142\u0105d po\u0142\u0105czenia';
        err.style.display = 'block';
    }
}

// ── Accounts ────────────────────────────────────────────────────────

async function loadAccounts() {
    try {
        accounts = await api('GET', '/accounts');
        renderSidebar();
        if (accounts.length > 0 && !currentAccountId) {
            selectAccount(accounts[0].id);
        } else if (currentAccountId) {
            selectAccount(currentAccountId);
        } else {
            renderNoAccount();
        }
    } catch (e) {
        toast('B\u0142\u0105d \u0142adowania kont: ' + e.message, 'error');
    }
}

function renderSidebar() {
    const igFbAccounts = accounts.filter(a => a.type === 'instagram_facebook');
    const ytAccounts = accounts.filter(a => a.type === 'youtube');

    let html = '';

    // IG+FB section
    html += `<div class="sidebar-section">
        <div class="sidebar-section-title">Instagram + Facebook</div>`;
    for (const acc of igFbAccounts) {
        const queueCount = acc.stats?.queued || 0;
        const hasToken = acc.fb_access_token === '***configured***';
        const icon = acc.ig_profile_pic
            ? `<img src="${acc.ig_profile_pic}" alt="">`
            : acc.name.charAt(0).toUpperCase();
        const meta = acc.ig_username
            ? '@' + esc(acc.ig_username)
            : (hasToken ? 'Po\u0142\u0105czono' : '\u26a0 Brak tokena');
        html += `<div class="sidebar-item ${acc.id === currentAccountId ? 'active' : ''}"
                     onclick="selectAccount(${acc.id})">
            <div class="sidebar-item-icon">${icon}</div>
            <div class="sidebar-item-info">
                <div class="sidebar-item-name">${esc(acc.name)}</div>
                <div class="sidebar-item-meta" ${!hasToken && !acc.ig_username ? 'style="color:var(--yellow)"' : ''}>${meta}</div>
            </div>
            ${queueCount > 0 ? `<span class="sidebar-item-badge">${queueCount}</span>` : ''}
        </div>`;
    }
    html += '</div>';

    // YouTube section
    html += `<div class="sidebar-section">
        <div class="sidebar-section-title">YouTube</div>`;
    for (const acc of ytAccounts) {
        const queueCount = acc.stats?.queued || 0;
        const icon = acc.yt_channel_pic
            ? `<img src="${acc.yt_channel_pic}" alt="">`
            : '\u25B6';
        html += `<div class="sidebar-item ${acc.id === currentAccountId ? 'active' : ''}"
                     onclick="selectAccount(${acc.id})">
            <div class="sidebar-item-icon">${icon}</div>
            <div class="sidebar-item-info">
                <div class="sidebar-item-name">${esc(acc.name)}</div>
                <div class="sidebar-item-meta">${acc.yt_channel_name || 'Nie po\u0142\u0105czono'}</div>
            </div>
            ${queueCount > 0 ? `<span class="sidebar-item-badge">${queueCount}</span>` : ''}
        </div>`;
    }
    if (ytAccounts.length === 0) {
        html += `<div class="sidebar-item" style="color:var(--text-muted);font-size:12px;cursor:default">
            Brak kont YouTube</div>`;
    }
    html += '</div>';

    document.getElementById('sidebar-accounts').innerHTML = html;
}

function renderNoAccount() {
    document.getElementById('main-content').innerHTML = `
        <div class="no-account-view">
            <div>
                <h2>Social Media Manager</h2>
                <p>Dodaj konto aby rozpocz\u0105\u0107</p>
                <br>
                <button class="btn btn-primary" onclick="showAddAccountModal()">+ Dodaj konto</button>
            </div>
        </div>`;
}

async function selectAccount(id) {
    currentAccountId = id;
    renderSidebar();
    const acc = accounts.find(a => a.id === id);
    if (!acc) return;

    const isYT = acc.type === 'youtube';
    await renderAccountView(acc, isYT);
    switchTab(currentTab);
}

async function renderAccountView(acc, isYT) {
    const statsRow = isYT
        ? `<div class="account-stat"><span class="account-stat-value">${fmtNum(acc.yt_subscribers)}</span><span class="account-stat-label">Sub</span></div>
           <div class="account-stat"><span class="account-stat-value">${fmtNum(acc.yt_video_count)}</span><span class="account-stat-label">Film\u00f3w</span></div>`
        : `<div class="account-stat"><span class="account-stat-value">${fmtNum(acc.ig_followers)}</span><span class="account-stat-label">IG</span></div>
           <div class="account-stat"><span class="account-stat-value">${fmtNum(acc.fb_followers)}</span><span class="account-stat-label">FB</span></div>
           <div class="account-stat"><span class="account-stat-value">${acc.ig_media_count || 0}</span><span class="account-stat-label">Post\u00f3w</span></div>`;

    const avatar = isYT
        ? (acc.yt_channel_pic ? `<img src="${acc.yt_channel_pic}">` : '\u25B6')
        : (acc.ig_profile_pic ? `<img src="${acc.ig_profile_pic}">` : acc.name.charAt(0));

    const handle = isYT
        ? (acc.yt_channel_name || '')
        : (acc.ig_username ? `@${acc.ig_username}` : '') + (acc.fb_page_name ? ` \u2022 ${acc.fb_page_name}` : '');

    const stats = acc.stats || {};

    // Fetch comment stats for badge
    let cStats = {};
    try { cStats = await api('GET', `/accounts/${acc.id}/comments/stats`); } catch(e) {}
    const cBadge = cStats.no_reply ? `<span class="tab-badge">${cStats.no_reply}</span>` : '';

    const tabsHtml = isYT
        ? `<div class="tab active" data-tab="queue" onclick="switchTab('queue')">Kolejka<span class="tab-badge">${stats.queued || 0}</span></div>
           <div class="tab" data-tab="published" onclick="switchTab('published')">Opublikowane<span class="tab-badge">${stats.published || 0}</span></div>
           <div class="tab" data-tab="comments" onclick="switchTab('comments')">Komentarze${cBadge}</div>
           <div class="tab" data-tab="upload" onclick="switchTab('upload')">Upload</div>
           <div class="tab" data-tab="schedule" onclick="switchTab('schedule')">Harmonogram</div>
           <div class="tab" data-tab="logs" onclick="switchTab('logs')">Logi</div>
           <div class="tab" data-tab="settings" onclick="switchTab('settings')">Ustawienia</div>`
        : `<div class="tab active" data-tab="queue" onclick="switchTab('queue')">Kolejka<span class="tab-badge">${stats.queued || 0}</span></div>
           <div class="tab" data-tab="published" onclick="switchTab('published')">Opublikowane<span class="tab-badge">${stats.published || 0}</span></div>
           <div class="tab" data-tab="comments" onclick="switchTab('comments')">Komentarze${cBadge}</div>
           <div class="tab" data-tab="stories" onclick="switchTab('stories')">Relacje</div>
           <div class="tab" data-tab="upload" onclick="switchTab('upload')">Upload</div>
           <div class="tab" data-tab="schedule" onclick="switchTab('schedule')">Harmonogram</div>
           <div class="tab" data-tab="logs" onclick="switchTab('logs')">Logi</div>
           <div class="tab" data-tab="settings" onclick="switchTab('settings')">Ustawienia</div>`;

    document.getElementById('main-content').innerHTML = `
        <div class="account-header">
            <div class="account-avatar">${avatar}</div>
            <div class="account-info">
                <div class="account-name">${esc(acc.name)}</div>
                <div class="account-handle">${esc(handle)}</div>
                <div class="account-stats-row">
                    ${statsRow}
                    <div class="account-stat"><span class="account-stat-value">${stats.queued || 0}</span><span class="account-stat-label">W kolejce</span></div>
                    <div class="account-stat"><span class="account-stat-value">${stats.published_today || 0}</span><span class="account-stat-label">Dzi\u015b</span></div>
                    ${stats.failed ? `<div class="account-stat"><span class="account-stat-value" style="color:var(--red)">${stats.failed}</span><span class="account-stat-label">B\u0142\u0119dy</span></div>` : ''}
                </div>
            </div>
            <div class="account-actions">
                <button class="btn" onclick="refreshAccount(${acc.id})">Od\u015bwie\u017c</button>
                <button class="btn btn-danger btn-sm" onclick="confirmDeleteAccount(${acc.id})">Usu\u0144</button>
            </div>
        </div>
        <div class="tabs" id="tabs-bar">${tabsHtml}</div>
        <div id="tab-content-area"></div>`;
}

// ── Tabs ────────────────────────────────────────────────────────────

async function switchTab(tab) {
    currentTab = tab;
    // Update tab bar active states
    document.querySelectorAll('.tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === tab);
    });

    const area = document.getElementById('tab-content-area');
    if (!area) return;

    switch (tab) {
        case 'queue': await renderQueue(area); break;
        case 'published': await renderPublished(area); break;
        case 'stories': await renderStories(area); break;
        case 'comments': await renderComments(area); break;
        case 'upload': renderUpload(area); break;
        case 'schedule': await renderSchedule(area); break;
        case 'logs': await renderLogs(area); break;
        case 'settings': renderSettings(area); break;
    }
}

// ── Queue Tab ───────────────────────────────────────────────────────

async function renderQueue(container) {
    const acc = accounts.find(a => a.id === currentAccountId);
    const isYT = acc?.type === 'youtube';
    try {
        const videos = await api('GET', `/accounts/${currentAccountId}/videos?status=queued`);
        if (videos.length === 0) {
            container.innerHTML = `<div class="tab-content active">
                <div class="empty-state">
                    <div class="empty-state-icon">\u{1F4F9}</div>
                    <div class="empty-state-text">Kolejka jest pusta</div>
                    <div class="empty-state-sub">Wgraj filmy w zak\u0142adce Upload</div>
                </div>
            </div>`;
            return;
        }

        let html = `<div class="tab-content active">
            <div class="queue-header">
                <h3>Kolejka <span class="queue-count">(${videos.length} film\u00f3w)</span></h3>
            </div>
            <div class="video-list" id="video-queue">`;

        videos.forEach((v, i) => {
            const thumb = videoUrl(v.account_id, 'queue', v.filename);
            const typeLabel = { reel: 'Reel', story: 'Story', short: 'Short', video: 'Film' }[v.video_type] || v.video_type;
            const caption = v.caption || v.title || v.filename;
            const size = v.file_size ? fmtSize(v.file_size) : '';
            const estDate = v.estimated_publish_at ? fmtDateFull(v.estimated_publish_at) : '';
            // Platform badges for IG+FB accounts
            let platformBadges = '';
            if (!isYT) {
                const igOn = v.target_ig !== 0;
                const fbOn = v.target_fb !== 0;
                platformBadges = `<span class="platform-badge ig clickable ${igOn ? '' : 'off'}" onclick="togglePlatform(event, ${v.id}, 'target_ig', ${igOn ? 'false' : 'true'})" title="Kliknij aby ${igOn ? 'wy\u0142\u0105czy\u0107' : 'w\u0142\u0105czy\u0107'} Instagram">IG</span>`
                    + `<span class="platform-badge fb clickable ${fbOn ? '' : 'off'}" onclick="togglePlatform(event, ${v.id}, 'target_fb', ${fbOn ? 'false' : 'true'})" title="Kliknij aby ${fbOn ? 'wy\u0142\u0105czy\u0107' : 'w\u0142\u0105czy\u0107'} Facebook">FB</span>`;
            }

            html += `<div class="video-card" draggable="true" data-id="${v.id}"
                        ondragstart="dragStart(event)" ondragover="dragOver(event)"
                        ondrop="drop(event)" ondragend="dragEnd(event)" ondragleave="dragLeave(event)">
                <div class="video-position">
                    <input type="number" class="pos-input" value="${i + 1}" min="1" max="${videos.length}"
                           title="Wpisz numer pozycji"
                           onkeydown="if(event.key==='Enter'){moveVideoToPos(${v.id},this.value,${videos.length});this.blur()}"
                           onblur="moveVideoToPos(${v.id},this.value,${videos.length})"
                           data-orig="${i + 1}">
                </div>
                <div class="video-thumbnail">
                    <video src="${thumb}#t=0.5" preload="metadata" muted
                           onclick="this.paused ? this.play() : this.pause()"></video>
                </div>
                <div class="video-info">
                    <div class="video-title">${esc(v.title || v.filename)}</div>
                    <div class="video-caption-preview">${esc(caption).substring(0, 120)}</div>
                    <div class="video-meta">
                        <span class="status-badge queued">${typeLabel}</span>
                        ${platformBadges}
                        <span>${size}</span>
                        ${estDate ? `<span class="est-date" title="Planowana publikacja">\u{1F4C5} ${estDate}</span>` : ''}
                    </div>
                </div>
                <div class="video-actions">
                    <button class="btn btn-sm" onclick="window.open('${thumb}', '_blank')" title="Otw\u00f3rz wideo">\u25b6</button>
                    <button class="btn btn-sm" onclick="showEditVideoModal(${v.id})">Edytuj</button>
                    <button class="btn btn-success btn-sm" onclick="publishNow(${v.id})">Publikuj</button>
                    <button class="btn btn-sm btn-icon" onclick="moveVideo(${v.id}, 'up', ${currentAccountId})" ${i === 0 ? 'disabled' : ''}>\u2191</button>
                    <button class="btn btn-sm btn-icon" onclick="moveVideo(${v.id}, 'down', ${currentAccountId})" ${i === videos.length - 1 ? 'disabled' : ''}>\u2193</button>
                    <button class="btn btn-sm" onclick="showCopyDropdown(event, ${v.id})" title="Kopiuj do innego konta">\u29C9</button>
                    <button class="btn btn-danger btn-sm" onclick="confirmDeleteVideo(${v.id})">\u2717</button>
                </div>
            </div>`;
        });

        html += '</div></div>';
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<div class="tab-content active"><p style="color:var(--red)">B\u0142\u0105d: ${e.message}</p></div>`;
    }
}

async function togglePlatform(event, videoId, field, value) {
    event.stopPropagation();
    try {
        await api('PUT', `/videos/${videoId}`, { [field]: value });
        await renderQueue(document.getElementById('tab-content-area'));
    } catch (e) {
        toast('B\u0142\u0105d: ' + e.message, 'error');
    }
}

// ── Published Tab ───────────────────────────────────────────────────

let publishedFilter = 'all'; // 'all', 'ig', 'fb', 'yt'
let publishedSort = 'newest'; // 'newest', 'oldest'

async function renderPublished(container) {
    try {
        const videos = await api('GET', `/accounts/${currentAccountId}/videos?status=published`);
        const failed = await api('GET', `/accounts/${currentAccountId}/videos?status=failed`);
        let all = [...failed, ...videos];
        const acc = accounts.find(a => a.id === currentAccountId);
        const isYT = acc?.type === 'youtube';

        // Sort
        all.sort((a, b) => {
            const da = new Date(a.published_at || a.created_at || 0);
            const db2 = new Date(b.published_at || b.created_at || 0);
            return publishedSort === 'newest' ? db2 - da : da - db2;
        });

        // Filter by platform
        if (publishedFilter === 'ig') all = all.filter(v => v.ig_media_id || v.ig_permalink);
        else if (publishedFilter === 'fb') all = all.filter(v => v.fb_video_id || v.fb_permalink);
        else if (publishedFilter === 'yt') all = all.filter(v => v.yt_video_id || v.yt_url);

        if (videos.length === 0 && failed.length === 0) {
            container.innerHTML = `<div class="tab-content active">
                <div class="empty-state">
                    <div class="empty-state-icon">\u2713</div>
                    <div class="empty-state-text">Brak opublikowanych film\u00f3w</div>
                    <div class="empty-state-sub">Kliknij "Pobierz opublikowane filmy" w Ustawieniach</div>
                </div>
            </div>`;
            return;
        }

        let html = `<div class="tab-content active">
            <div class="published-toolbar">
                <div class="published-filters">
                    <button class="btn btn-sm ${publishedFilter === 'all' ? 'active' : ''}" onclick="setPublishedFilter('all')">Wszystkie (${videos.length + failed.length})</button>
                    ${!isYT ? `<button class="btn btn-sm ${publishedFilter === 'ig' ? 'active' : ''}" onclick="setPublishedFilter('ig')">Instagram</button>
                    <button class="btn btn-sm ${publishedFilter === 'fb' ? 'active' : ''}" onclick="setPublishedFilter('fb')">Facebook</button>` : ''}
                    ${isYT ? `<button class="btn btn-sm ${publishedFilter === 'yt' ? 'active' : ''}" onclick="setPublishedFilter('yt')">YouTube</button>` : ''}
                </div>
                <div>
                    <select onchange="setPublishedSort(this.value)" style="background:var(--bg-input);border:1px solid var(--border);color:var(--text);padding:4px 8px;font-size:12px;border-radius:var(--radius)">
                        <option value="newest" ${publishedSort === 'newest' ? 'selected' : ''}>Najnowsze</option>
                        <option value="oldest" ${publishedSort === 'oldest' ? 'selected' : ''}>Najstarsze</option>
                    </select>
                </div>
            </div>
            <div class="video-list">`;

        for (const v of all) {
            const isFailed = v.status === 'failed';
            const platforms = [];
            if (v.ig_permalink || v.ig_media_id) platforms.push(`<a href="${v.ig_permalink || '#'}" target="_blank" class="platform-badge ig">IG</a>`);
            if (v.fb_permalink || v.fb_video_id) platforms.push(`<a href="${v.fb_permalink || '#'}" target="_blank" class="platform-badge fb">FB</a>`);
            if (v.yt_url || v.yt_video_id) platforms.push(`<a href="${v.yt_url || '#'}" target="_blank" class="platform-badge yt">YT</a>`);
            const dateStr = v.published_at ? fmtDate(v.published_at) : fmtDate(v.created_at);

            html += `<div class="published-card" style="${isFailed ? 'border-color:var(--red-dim)' : ''}">
                <div class="video-thumbnail">
                    <video src="${videoUrl(v.account_id, isFailed ? 'queue' : 'archive', v.filename)}#t=0.5"
                           preload="metadata" muted onclick="this.paused ? this.play() : this.pause()"
                           onerror="this.style.display='none'"></video>
                </div>
                <div class="video-info">
                    <div class="video-title">${esc(v.yt_title || v.title || v.filename)}</div>
                    <div class="video-caption-preview">${esc(v.caption || '').substring(0, 100)}</div>
                    <div class="video-meta">
                        <span class="status-badge ${v.status}">${v.status === 'failed' ? 'B\u0141\u0104D' : 'LIVE'}</span>
                        <span>${dateStr}</span>
                    </div>
                    <div class="published-platforms" style="margin-top:4px">${platforms.join(' ')}</div>
                    ${isFailed ? `<div style="color:var(--red);font-size:11px;margin-top:4px">${esc(v.error_message || '')}</div>` : ''}
                </div>
                <div class="video-actions">
                    ${isFailed ? `<button class="btn btn-sm" onclick="retryVideo(${v.id})">Pon\u00f3w</button>` : ''}
                    ${isFailed ? `<button class="btn btn-danger btn-sm" onclick="confirmDeleteVideo(${v.id})">\u2717</button>` : ''}
                </div>
            </div>`;
        }
        html += '</div></div>';
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<div class="tab-content active"><p style="color:var(--red)">B\u0142\u0105d: ${e.message}</p></div>`;
    }
}

function setPublishedFilter(f) {
    publishedFilter = f;
    switchTab('published');
}

function setPublishedSort(s) {
    publishedSort = s;
    switchTab('published');
}

// ── Stories Tab ──────────────────────────────────────────────────────

async function renderStories(container) {
    try {
        const videos = await api('GET', `/accounts/${currentAccountId}/videos?video_type=story`);
        const queued = videos.filter(v => v.status === 'queued');
        const published = videos.filter(v => v.status === 'published');

        let html = `<div class="tab-content active">
            <div class="queue-header">
                <h3>Relacje <span class="queue-count">(${queued.length} w kolejce, ${published.length} opublikowanych)</span></h3>
            </div>`;

        if (queued.length === 0 && published.length === 0) {
            html += `<div class="empty-state">
                <div class="empty-state-icon">\u{1F4F1}</div>
                <div class="empty-state-text">Brak relacji</div>
                <div class="empty-state-sub">Wgraj relacje w zak\u0142adce Upload (typ: Story)</div>
            </div>`;
        } else {
            html += '<div class="video-list">';
            for (const v of queued) {
                html += `<div class="video-card">
                    <div class="video-position">\u{1F4F1}</div>
                    <div class="video-thumbnail">
                        <video src="${videoUrl(v.account_id, 'queue', v.filename)}#t=0.5" preload="metadata" muted></video>
                    </div>
                    <div class="video-info">
                        <div class="video-title">${esc(v.title || v.filename)}</div>
                        <div class="video-meta">
                            <span class="platform-badge story">STORY</span>
                            <span class="status-badge queued">QUEUED</span>
                        </div>
                    </div>
                    <div class="video-actions">
                        <button class="btn btn-success btn-sm" onclick="publishNow(${v.id})">Publikuj</button>
                        <button class="btn btn-danger btn-sm" onclick="confirmDeleteVideo(${v.id})">\u2717</button>
                    </div>
                </div>`;
            }
            html += '</div>';
        }
        html += '</div>';
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<div class="tab-content active"><p style="color:var(--red)">B\u0142\u0105d: ${e.message}</p></div>`;
    }
}

// ── Upload Tab ──────────────────────────────────────────────────────

function renderUpload(container) {
    const acc = accounts.find(a => a.id === currentAccountId);
    const isYT = acc?.type === 'youtube';

    const typeOptions = isYT
        ? `<option value="short">Short</option><option value="video">Film</option>`
        : `<option value="reel">Reel</option><option value="story">Story</option>`;

    container.innerHTML = `<div class="tab-content active">
        <div class="upload-area" id="upload-drop-area"
             onclick="document.getElementById('upload-files').click()">
            <div class="upload-area-icon">\u2B06</div>
            <div class="upload-area-text">Kliknij lub przeci\u0105gnij pliki</div>
            <div class="upload-area-hint">MP4, MOV, AVI, MKV, WEBM \u2022 max 500MB per plik</div>
        </div>
        <input type="file" id="upload-files" multiple accept="video/*,.txt,.srt" style="display:none"
               onchange="handleFileSelect(this.files)">
        <div class="form-group">
            <label>Typ</label>
            <select id="upload-type">${typeOptions}</select>
        </div>
        ${isYT ? `
        <div class="form-group">
            <label>Tytu\u0142 YouTube</label>
            <input type="text" id="upload-yt-title" placeholder="Tytu\u0142 filmu">
        </div>
        <div class="form-group">
            <label>Opis YouTube</label>
            <textarea id="upload-yt-desc" rows="4" placeholder="Opis filmu"></textarea>
        </div>
        <div class="form-group">
            <label>Tagi (oddzielone przecinkami)</label>
            <input type="text" id="upload-yt-tags" placeholder="historia, edukacja, Polska">
        </div>
        <div class="form-group">
            <label>Prywatno\u015b\u0107</label>
            <select id="upload-yt-privacy">
                <option value="public">Publiczny</option>
                <option value="unlisted">Niepubliczny</option>
                <option value="private">Prywatny</option>
            </select>
        </div>` : `
        <div class="form-group">
            <label>Publikuj na</label>
            <div class="platform-toggles">
                <label class="platform-toggle">
                    <input type="checkbox" id="upload-target-ig" checked>
                    Instagram
                </label>
                <label class="platform-toggle">
                    <input type="checkbox" id="upload-target-fb" checked>
                    Facebook
                </label>
            </div>
        </div>
        <div class="form-group">
            <label>Opis Instagram (caption)</label>
            <textarea id="upload-caption" rows="4" placeholder="Opis do posta na IG..." maxlength="2200"></textarea>
            <div class="char-count" id="upload-char-count">0 / 2200</div>
        </div>
        <div class="form-group">
            <label>Opis Facebook <span style="color:var(--text-muted)">(osobny, opcjonalnie)</span></label>
            <textarea id="upload-fb-title" rows="3" placeholder="Je\u015bli puste, u\u017cyje opisu z Instagrama..."></textarea>
        </div>`}
        <div id="upload-file-list" class="upload-file-list"></div>
        <button class="btn btn-primary" id="upload-btn" onclick="doUpload()" style="display:none">Wgraj pliki</button>
    </div>`;

    // Setup drag & drop
    const dropArea = document.getElementById('upload-drop-area');
    ['dragenter', 'dragover'].forEach(ev => {
        dropArea.addEventListener(ev, e => { e.preventDefault(); dropArea.classList.add('dragover'); });
    });
    ['dragleave', 'drop'].forEach(ev => {
        dropArea.addEventListener(ev, e => { e.preventDefault(); dropArea.classList.remove('dragover'); });
    });
    dropArea.addEventListener('drop', e => handleFileSelect(e.dataTransfer.files));

    // Char counter for IG/FB
    const captionEl = document.getElementById('upload-caption');
    if (captionEl) {
        captionEl.addEventListener('input', () => {
            const count = captionEl.value.length;
            const counter = document.getElementById('upload-char-count');
            counter.textContent = `${count} / 2200`;
            counter.classList.toggle('over', count > 2200);
        });
    }
}

let selectedFiles = [];

function handleFileSelect(files) {
    selectedFiles = Array.from(files);
    const list = document.getElementById('upload-file-list');
    list.innerHTML = selectedFiles.map(f =>
        `<div class="upload-file-item"><span class="status-icon">\u25CB</span> ${esc(f.name)} <span style="margin-left:auto">${fmtSize(f.size)}</span></div>`
    ).join('');
    document.getElementById('upload-btn').style.display = selectedFiles.length ? 'inline-flex' : 'none';
}

async function doUpload() {
    if (!selectedFiles.length) return;
    const btn = document.getElementById('upload-btn');
    btn.disabled = true;
    btn.textContent = 'Wgrywanie...';

    const videoType = document.getElementById('upload-type').value;
    const acc = accounts.find(a => a.id === currentAccountId);
    const isYT = acc?.type === 'youtube';

    const formData = new FormData();
    formData.append('video_type', videoType);

    for (const f of selectedFiles) {
        formData.append('files', f);
    }

    try {
        const result = await api('POST', `/accounts/${currentAccountId}/videos/bulk-upload`, formData, true);
        toast(`Wgrano ${result.uploaded} plik\u00f3w`, 'success');

        // Update uploaded videos with metadata
        const uploadedIds = result.results.filter(r => r.ok).map(r => r.id);
        for (const videoId of uploadedIds) {
            const updateData = {};

            if (isYT) {
                const ytTitle = document.getElementById('upload-yt-title')?.value;
                const ytDesc = document.getElementById('upload-yt-desc')?.value;
                const ytTags = document.getElementById('upload-yt-tags')?.value;
                const ytPrivacy = document.getElementById('upload-yt-privacy')?.value;
                if (ytTitle) updateData.yt_title = ytTitle;
                if (ytDesc) updateData.yt_description = ytDesc;
                if (ytTags) updateData.yt_tags = ytTags.split(',').map(t => t.trim()).filter(Boolean);
                if (ytPrivacy) updateData.yt_privacy = ytPrivacy;
            } else {
                const caption = document.getElementById('upload-caption')?.value;
                if (caption) updateData.caption = caption;
                const fbTitle = document.getElementById('upload-fb-title')?.value;
                if (fbTitle) updateData.fb_title = fbTitle;
                const targetIg = document.getElementById('upload-target-ig');
                const targetFb = document.getElementById('upload-target-fb');
                if (targetIg) updateData.target_ig = targetIg.checked;
                if (targetFb) updateData.target_fb = targetFb.checked;
            }

            if (Object.keys(updateData).length) {
                await api('PUT', `/videos/${videoId}`, updateData);
            }
        }

        // Show results
        const list = document.getElementById('upload-file-list');
        list.innerHTML = result.results.map(r =>
            `<div class="upload-file-item">
                <span class="status-icon ${r.ok ? 'ok' : 'err'}">${r.ok ? '\u2713' : '\u2717'}</span>
                ${esc(r.filename)} ${r.error ? `<span style="color:var(--red)">${esc(r.error)}</span>` : ''}
            </div>`
        ).join('');

        selectedFiles = [];
        btn.style.display = 'none';
        await loadAccounts();
    } catch (e) {
        toast('B\u0142\u0105d uploadu: ' + e.message, 'error');
    }
    btn.disabled = false;
    btn.textContent = 'Wgraj pliki';
}

// ── Schedule Tab ────────────────────────────────────────────────────

function buildHourOptions(selected) {
    let opts = '';
    for (let h = 0; h < 24; h++) {
        const val = String(h).padStart(2, '0');
        opts += `<option value="${val}" ${val === selected ? 'selected' : ''}>${val}</option>`;
    }
    return opts;
}

function buildMinuteOptions(selected) {
    let opts = '';
    for (let m = 0; m < 60; m += 5) {
        const val = String(m).padStart(2, '0');
        opts += `<option value="${val}" ${val === selected ? 'selected' : ''}>${val}</option>`;
    }
    return opts;
}

async function renderSchedule(container) {
    try {
        const schedule = await api('GET', `/accounts/${currentAccountId}/schedule`);
        const acc = accounts.find(a => a.id === currentAccountId);
        const isYT = acc?.type === 'youtube';

        const days = ['pon', 'wt', '\u015br', 'czw', 'pt', 'sob', 'nd'];
        const daysEn = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
        const activeDays = schedule.day_of_week === '*' ? daysEn : schedule.day_of_week.split(',').map(d => d.trim());

        const times = (schedule.publish_times || []).slice().sort();

        let html = `<div class="tab-content active">
            <div class="schedule-panel">
                <h3>Harmonogram publikacji</h3>

                <div class="schedule-row" style="margin-bottom:16px">
                    <div class="schedule-field">
                        <label>Dni tygodnia</label>
                        <div class="days-selector">
                            ${days.map((d, i) => `<button type="button" class="day-btn ${activeDays.includes(daysEn[i]) ? 'active' : ''}"
                                data-day="${daysEn[i]}" onclick="toggleDay(this)">${d}</button>`).join('')}
                        </div>
                    </div>
                    <div class="schedule-field">
                        <label>Aktywny</label>
                        <select id="sched-enabled">
                            <option value="1" ${schedule.enabled ? 'selected' : ''}>Tak</option>
                            <option value="0" ${!schedule.enabled ? 'selected' : ''}>Nie</option>
                        </select>
                    </div>
                </div>

                <div class="schedule-section" style="margin-bottom:16px">
                    <label class="schedule-section-label">Godziny publikacji (ka\u017cda = 1 film)</label>
                    <div id="sched-times-list">
                        ${times.map((t, idx) => {
                            const [h, m] = t.split(':');
                            return `<div class="time-slot" data-idx="${idx}">
                                <select class="time-hour">${buildHourOptions(h)}</select>
                                <span class="time-sep">:</span>
                                <select class="time-minute">${buildMinuteOptions(m)}</select>
                                <button type="button" class="btn-remove-time" onclick="removeTimeSlot(this)" title="Usu\u0144">\u00d7</button>
                            </div>`;
                        }).join('')}
                    </div>
                    <button type="button" class="btn btn-sm" onclick="addTimeSlot()" style="margin-top:8px">+ Dodaj godzin\u0119</button>
                    <div class="schedule-hint" id="sched-summary"></div>
                </div>`;

        if (!isYT) {
            html += `<div class="schedule-row" style="margin-bottom:16px">
                <div class="schedule-field">
                    <label>Platformy</label>
                    <div class="platform-toggles">
                        <label class="platform-toggle">
                            <input type="checkbox" id="sched-ig" ${acc.publish_to_ig ? 'checked' : ''}>
                            Instagram
                        </label>
                        <label class="platform-toggle">
                            <input type="checkbox" id="sched-fb" ${acc.publish_to_fb ? 'checked' : ''}>
                            Facebook
                        </label>
                        <label class="platform-toggle">
                            <input type="checkbox" id="sched-stories" ${acc.publish_to_stories ? 'checked' : ''}>
                            Relacje
                        </label>
                    </div>
                </div>
            </div>`;
        }

        html += `<div style="margin-top:16px">
                    <button class="btn btn-primary" onclick="saveSchedule()">Zapisz harmonogram</button>
                </div>
            </div>`;

        // Show active scheduler jobs
        const jobs = await api('GET', '/scheduler/jobs');
        const myJobs = jobs.filter(j => j.account_id === currentAccountId);
        if (myJobs.length > 0) {
            html += `<h3 style="font-size:14px;margin-bottom:12px">Aktywne zadania schedulera</h3>
                <div class="scheduler-grid">`;
            for (const j of myJobs) {
                html += `<div class="scheduler-card">
                    <h4>${j.time}</h4>
                    <div class="detail">Nast\u0119pne: ${j.next_run ? fmtDate(j.next_run) : 'N/A'}</div>
                </div>`;
            }
            html += '</div>';
        }

        html += '</div>';
        container.innerHTML = html;
        updateSchedSummary();
    } catch (e) {
        container.innerHTML = `<div class="tab-content active"><p style="color:var(--red)">B\u0142\u0105d: ${e.message}</p></div>`;
    }
}

function toggleDay(btn) {
    btn.classList.toggle('active');
    updateSchedSummary();
}

function addTimeSlot() {
    const list = document.getElementById('sched-times-list');
    const div = document.createElement('div');
    div.className = 'time-slot';
    div.innerHTML = `
        <select class="time-hour">${buildHourOptions('12')}</select>
        <span class="time-sep">:</span>
        <select class="time-minute">${buildMinuteOptions('00')}</select>
        <button type="button" class="btn-remove-time" onclick="removeTimeSlot(this)" title="Usu\u0144">\u00d7</button>
    `;
    list.appendChild(div);
    updateSchedSummary();
}

function removeTimeSlot(btn) {
    btn.closest('.time-slot').remove();
    updateSchedSummary();
}

function getScheduleTimes() {
    return Array.from(document.querySelectorAll('.time-slot')).map(slot => {
        const h = slot.querySelector('.time-hour').value;
        const m = slot.querySelector('.time-minute').value;
        return `${h}:${m}`;
    }).sort();
}

function updateSchedSummary() {
    const el = document.getElementById('sched-summary');
    if (!el) return;
    const times = getScheduleTimes();
    const dayCount = document.querySelectorAll('.day-btn.active').length;
    if (times.length === 0) {
        el.textContent = 'Brak godzin \u2014 automatyczne publikowanie wy\u0142\u0105czone';
    } else {
        el.textContent = `${times.length} film${times.length === 1 ? '' : times.length < 5 ? 'y' : '\u00f3w'} dziennie \u00d7 ${dayCount} dni = ${times.length * dayCount} tygodniowo`;
    }
}

async function saveSchedule() {
    const activeDays = Array.from(document.querySelectorAll('.day-btn.active')).map(b => b.dataset.day);
    const times = getScheduleTimes();
    const enabled = document.getElementById('sched-enabled').value === '1';

    if (times.length === 0 && enabled) {
        toast('Dodaj przynajmniej jedn\u0105 godzin\u0119 publikacji', 'error');
        return;
    }

    // Check for duplicate times
    const unique = [...new Set(times)];
    if (unique.length !== times.length) {
        toast('Usun\u0105\u0142e\u015b zduplikowane godziny', 'error');
        return;
    }

    try {
        await api('PUT', `/accounts/${currentAccountId}/schedule`, {
            day_of_week: activeDays.length === 7 ? '*' : activeDays.join(','),
            publish_times: times,
            max_per_day: times.length,
            enabled: enabled,
        });

        // Save platform toggles
        const acc = accounts.find(a => a.id === currentAccountId);
        if (acc?.type === 'instagram_facebook') {
            await api('PUT', `/accounts/${currentAccountId}`, {
                publish_to_ig: document.getElementById('sched-ig')?.checked ?? true,
                publish_to_fb: document.getElementById('sched-fb')?.checked ?? true,
                publish_to_stories: document.getElementById('sched-stories')?.checked ?? false,
            });
        }

        toast('Harmonogram zapisany', 'success');
        await loadAccounts();
    } catch (e) {
        toast('B\u0142\u0105d: ' + e.message, 'error');
    }
}

// ── Logs Tab ────────────────────────────────────────────────────────

async function renderLogs(container) {
    try {
        const logs = await api('GET', `/logs?account_id=${currentAccountId}&limit=100`);
        if (logs.length === 0) {
            container.innerHTML = `<div class="tab-content active"><div class="empty-state">
                <div class="empty-state-text">Brak log\u00f3w</div>
            </div></div>`;
            return;
        }

        let html = `<div class="tab-content active">
            <table class="logs-table">
                <thead><tr>
                    <th>Data</th><th>Platforma</th><th>Status</th><th>Szczeg\u00f3\u0142y</th>
                </tr></thead><tbody>`;
        for (const log of logs) {
            html += `<tr>
                <td>${fmtDate(log.created_at)}</td>
                <td><span class="platform-badge ${log.platform === 'instagram' ? 'ig' : log.platform === 'facebook' ? 'fb' : 'yt'}">${log.platform}</span></td>
                <td><span class="status-badge ${log.status}">${log.status}</span></td>
                <td>${esc(log.error_message || '-')}</td>
            </tr>`;
        }
        html += '</tbody></table></div>';
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<div class="tab-content active"><p style="color:var(--red)">B\u0142\u0105d: ${e.message}</p></div>`;
    }
}

// ── Settings Tab ────────────────────────────────────────────────────

async function renderSettings(container) {
    const acc = accounts.find(a => a.id === currentAccountId);
    if (!acc) return;
    const isYT = acc.type === 'youtube';

    // Fetch actual tokens
    let tokens = {};
    try {
        tokens = await api('GET', `/accounts/${currentAccountId}/tokens`);
    } catch (e) {}

    let html = `<div class="tab-content active">
        <div class="settings-section">
            <h3>Informacje o koncie</h3>
            <div class="form-group">
                <label>Nazwa konta</label>
                <input type="text" id="settings-name" value="${esc(acc.name)}" placeholder="Nazwa konta">
            </div>
            <div class="setting-row"><span class="setting-label">Typ</span><span class="setting-value">${acc.type === 'youtube' ? 'YouTube' : 'Instagram + Facebook'}</span></div>
            <div class="setting-row"><span class="setting-label">ID</span><span class="setting-value">${acc.id}</span></div>
            <div class="setting-row"><span class="setting-label">Utworzono</span><span class="setting-value">${fmtDate(acc.created_at)}</span></div>`;

    if (isYT) {
        html += `<div class="setting-row"><span class="setting-label">Kana\u0142</span><span class="setting-value">${esc(acc.yt_channel_name || '-')}</span></div>
            <div class="setting-row"><span class="setting-label">Channel ID</span><span class="setting-value">${esc(acc.yt_channel_id || '-')}</span></div>
            <div class="setting-row"><span class="setting-label">Subskrybenci</span><span class="setting-value">${fmtNum(acc.yt_subscribers)}</span></div>`;
    } else {
        html += `<div class="setting-row"><span class="setting-label">IG Username</span><span class="setting-value">@${esc(acc.ig_username || '-')}</span></div>
            <div class="setting-row"><span class="setting-label">IG User ID</span><span class="setting-value">${esc(acc.ig_user_id || '-')}</span></div>
            <div class="setting-row"><span class="setting-label">FB Page ID</span><span class="setting-value">${esc(acc.fb_page_id || '-')}</span></div>
            <div class="setting-row"><span class="setting-label">FB Page</span><span class="setting-value">${esc(acc.fb_page_name || '-')}</span></div>
            <div class="setting-row"><span class="setting-label">IG Obserwuj\u0105cy</span><span class="setting-value">${fmtNum(acc.ig_followers)}</span></div>
            <div class="setting-row"><span class="setting-label">FB Obserwuj\u0105cy</span><span class="setting-value">${fmtNum(acc.fb_followers)}</span></div>`;
    }

    html += `</div>
        <div class="settings-section">
            <h3>Klucze API <button class="btn btn-sm" style="margin-left:8px" onclick="toggleTokenVisibility()">Poka\u017c / Ukryj</button></h3>`;

    if (isYT) {
        html += tokenField('Client ID', 'settings-token', tokens.yt_client_id, 'OAuth Client ID', 'Google OAuth2 Client ID')
            + tokenField('Client Secret', 'settings-yt-secret', tokens.yt_client_secret, 'Client Secret')
            + tokenField('Refresh Token', 'settings-yt-refresh', tokens.yt_refresh_token, 'Refresh Token');
    } else {
        html += tokenField('Facebook Access Token', 'settings-token', tokens.fb_access_token, 'EAAx...', 'Page Access Token z Graph API')
            + `<div class="form-group">
                <label>Facebook Page ID</label>
                <div class="token-input-row">
                    <input type="text" id="settings-fb-page-id" value="${esc(tokens.fb_page_id || '')}"
                           placeholder="np. 1026165970576023" style="font-family:var(--font-mono);flex:1">
                    <button class="btn btn-sm btn-copy" onclick="copyField('settings-fb-page-id')" title="Kopiuj">Kopiuj</button>
                </div>
            </div>
            <div class="form-group">
                <label>Instagram User ID</label>
                <div class="token-input-row">
                    <input type="text" id="settings-ig-user-id" value="${esc(tokens.ig_user_id || '')}"
                           placeholder="np. 17841477144493942" style="font-family:var(--font-mono);flex:1">
                    <button class="btn btn-sm btn-copy" onclick="copyField('settings-ig-user-id')" title="Kopiuj">Kopiuj</button>
                </div>
            </div>`;
    }

    html += `<button class="btn btn-primary" onclick="saveAccountSettings()">Zapisz</button>
        </div>`;

    // YouTube OAuth section
    if (isYT) {
        html += `<div class="settings-section">
            <h3>Autoryzacja YouTube</h3>
            <p style="font-size:12px;color:var(--text-dim);margin-bottom:12px">
                Aby po\u0142\u0105czy\u0107 konto YouTube, musisz przej\u015b\u0107 przez autoryzacj\u0119 OAuth2 w Google.
                Upewnij si\u0119, \u017ce Client ID i Secret s\u0105 zapisane powy\u017cej, a nast\u0119pnie kliknij przycisk.
            </p>
            <button class="btn btn-primary" onclick="startYouTubeOAuth(${acc.id})">Autoryzuj przez Google</button>
        </div>`;
    }

    // Sync published videos
    html += `<div class="settings-section">
        <h3>Synchronizacja</h3>
        <p style="font-size:12px;color:var(--text-dim);margin-bottom:12px">
            Pobierz list\u0119 opublikowanych film\u00f3w z ${isYT ? 'YouTube' : 'Instagrama'} i zapisz w bazie danych.
        </p>
        <button class="btn" onclick="syncPublished(${acc.id})">Pobierz opublikowane filmy</button>
    </div>`;

    html += `<div class="settings-section">
            <h3 style="color:var(--red)">Strefa niebezpieczna</h3>
            <p style="font-size:12px;color:var(--text-dim);margin-bottom:12px">Usuni\u0119cie konta jest nieodwracalne.</p>
            <button class="btn btn-danger" onclick="confirmDeleteAccount(${acc.id})">Usu\u0144 konto</button>
        </div>
    </div>`;

    container.innerHTML = html;
}

function tokenField(label, id, value, placeholder, hint) {
    return `<div class="form-group">
        <label>${label}</label>
        <div class="token-input-row">
            <input type="password" class="token-field" id="${id}" value="${esc(value || '')}"
                   placeholder="${placeholder}" style="flex:1;font-family:var(--font-mono);font-size:12px">
            <button class="btn btn-sm btn-copy" onclick="copyField('${id}')" title="Kopiuj">Kopiuj</button>
        </div>
        ${hint ? `<div class="form-hint">${hint}</div>` : ''}
    </div>`;
}

function copyField(id) {
    const el = document.getElementById(id);
    if (!el || !el.value) { toast('Brak warto\u015bci', 'info'); return; }
    navigator.clipboard.writeText(el.value).then(() => {
        toast('Skopiowano do schowka', 'success');
    }).catch(() => {
        // Fallback
        el.type = 'text';
        el.select();
        document.execCommand('copy');
        toast('Skopiowano do schowka', 'success');
    });
}

function toggleTokenVisibility() {
    document.querySelectorAll('.token-field').forEach(el => {
        el.type = el.type === 'password' ? 'text' : 'password';
    });
}

async function saveAccountSettings() {
    const acc = accounts.find(a => a.id === currentAccountId);
    const isYT = acc?.type === 'youtube';
    const data = {};

    const name = document.getElementById('settings-name')?.value?.trim();
    if (name && name !== acc.name) data.name = name;

    if (isYT) {
        const clientId = document.getElementById('settings-token').value;
        const clientSecret = document.getElementById('settings-yt-secret').value;
        const refreshToken = document.getElementById('settings-yt-refresh').value;
        if (clientId) data.yt_client_id = clientId;
        if (clientSecret) data.yt_client_secret = clientSecret;
        if (refreshToken) data.yt_refresh_token = refreshToken;
    } else {
        const token = document.getElementById('settings-token').value;
        const fbPageId = document.getElementById('settings-fb-page-id')?.value;
        const igUserId = document.getElementById('settings-ig-user-id')?.value;
        if (token) data.fb_access_token = token;
        if (fbPageId) data.fb_page_id = fbPageId;
        if (igUserId) data.ig_user_id = igUserId;
    }

    if (Object.keys(data).length === 0) {
        toast('Brak zmian', 'info');
        return;
    }

    try {
        await api('PUT', `/accounts/${currentAccountId}`, data);
        toast('Zapisano ustawienia', 'success');
        await loadAccounts();
    } catch (e) {
        toast('B\u0142\u0105d: ' + e.message, 'error');
    }
}

// ── Video Actions ───────────────────────────────────────────────────

async function publishNow(videoId) {
    if (!confirm('Opublikowa\u0107 teraz?')) return;
    try {
        const result = await api('POST', `/videos/${videoId}/publish`);
        toast('Publikowanie rozpocz\u0119te...', 'info');
        pollPublishStatus(result.job_id);
    } catch (e) {
        toast('B\u0142\u0105d: ' + e.message, 'error');
    }
}

function pollPublishStatus(jobId) {
    const bar = document.getElementById('publish-bar');
    const barText = document.getElementById('publish-bar-text');
    bar.classList.add('active');
    barText.textContent = 'Publikowanie...';

    if (publishPollTimer) clearInterval(publishPollTimer);
    publishPollTimer = setInterval(async () => {
        try {
            const status = await api('GET', `/publish/status/${jobId}`);
            barText.textContent = status.messages?.slice(-1)[0] || status.status;
            if (status.status === 'done' || status.status === 'failed') {
                clearInterval(publishPollTimer);
                publishPollTimer = null;
                setTimeout(() => bar.classList.remove('active'), 3000);
                toast(
                    status.status === 'done' ? 'Opublikowano!' : 'Publikacja nie powiod\u0142a si\u0119',
                    status.status === 'done' ? 'success' : 'error'
                );
                await loadAccounts();
            }
        } catch (e) {
            clearInterval(publishPollTimer);
            bar.classList.remove('active');
        }
    }, 3000);
}

async function retryVideo(videoId) {
    try {
        await api('POST', `/videos/${videoId}/retry`);
        toast('Film wr\u00f3ci\u0142 do kolejki', 'success');
        await loadAccounts();
    } catch (e) {
        toast('B\u0142\u0105d: ' + e.message, 'error');
    }
}

function confirmDeleteVideo(videoId) {
    showConfirmModal('Usun\u0105\u0107 ten film?', async () => {
        try {
            await api('DELETE', `/videos/${videoId}`);
            toast('Film usuni\u0119ty', 'success');
            await loadAccounts();
        } catch (e) {
            toast('B\u0142\u0105d: ' + e.message, 'error');
        }
    });
}

async function moveVideo(videoId, direction, accountId) {
    try {
        const videos = await api('GET', `/accounts/${accountId}/videos?status=queued`);
        const ids = videos.map(v => v.id);
        const idx = ids.indexOf(videoId);
        if (idx === -1) return;
        if (direction === 'up' && idx > 0) {
            [ids[idx], ids[idx - 1]] = [ids[idx - 1], ids[idx]];
        } else if (direction === 'down' && idx < ids.length - 1) {
            [ids[idx], ids[idx + 1]] = [ids[idx + 1], ids[idx]];
        }
        await api('POST', `/accounts/${accountId}/videos/reorder`, { video_ids: ids });
        switchTab('queue');
    } catch (e) {
        toast('B\u0142\u0105d: ' + e.message, 'error');
    }
}

async function moveVideoToPos(videoId, newPosStr, total) {
    const newPos = parseInt(newPosStr);
    if (isNaN(newPos) || newPos < 1 || newPos > total) return;
    try {
        const videos = await api('GET', `/accounts/${currentAccountId}/videos?status=queued`);
        const ids = videos.map(v => v.id);
        const fromIdx = ids.indexOf(videoId);
        if (fromIdx === -1 || fromIdx === newPos - 1) return;
        ids.splice(fromIdx, 1);
        ids.splice(newPos - 1, 0, videoId);
        await api('POST', `/accounts/${currentAccountId}/videos/reorder`, { video_ids: ids });
        switchTab('queue');
    } catch (e) {
        toast('Błąd: ' + e.message, 'error');
    }
}

// ── Copy to Another Account ─────────────────────────────────────────

function showCopyDropdown(event, videoId) {
    event.stopPropagation();
    // Remove existing dropdown
    const old = document.getElementById('copy-dropdown');
    if (old) old.remove();

    const btn = event.currentTarget;
    const rect = btn.getBoundingClientRect();

    const dd = document.createElement('div');
    dd.id = 'copy-dropdown';
    dd.className = 'copy-dropdown';

    const otherAccounts = accounts.filter(a => a.id !== currentAccountId);
    if (!otherAccounts.length) {
        dd.innerHTML = '<div class="copy-dropdown-item" style="color:var(--text-muted)">Brak innych kont</div>';
    } else {
        otherAccounts.forEach(a => {
            const typeTag = a.type === 'youtube' ? 'YT' : 'IG+FB';
            const item = document.createElement('div');
            item.className = 'copy-dropdown-item';
            item.innerHTML = `<span>${esc(a.name)}</span> <span class="copy-type-tag ${a.type === 'youtube' ? 'yt' : 'igfb'}">${typeTag}</span>`;
            item.onclick = (e) => { e.stopPropagation(); copyVideoToAccount(videoId, a.id); dd.remove(); };
            dd.appendChild(item);
        });
    }

    document.body.appendChild(dd);

    // Position: prefer below the button, flip up if no space
    const ddH = dd.offsetHeight;
    const spaceBelow = window.innerHeight - rect.bottom;
    dd.style.left = Math.min(rect.left, window.innerWidth - dd.offsetWidth - 8) + 'px';
    if (spaceBelow >= ddH + 4) {
        dd.style.top = (rect.bottom + 4) + 'px';
    } else {
        dd.style.top = (rect.top - ddH - 4) + 'px';
    }

    // Close on outside click
    setTimeout(() => document.addEventListener('click', function handler() {
        dd.remove();
        document.removeEventListener('click', handler);
    }, { once: true }), 0);
}

async function copyVideoToAccount(videoId, targetAccountId) {
    try {
        await api('POST', `/videos/${videoId}/copy`, { target_account_id: targetAccountId });
        toast('Film skopiowany', 'success');
        await loadAccounts();
        switchTab('queue');
    } catch (e) {
        toast('Błąd: ' + e.message, 'error');
    }
}

// ── Comments Tab ────────────────────────────────────────────────────

let commentsFilter = 'unsent';

async function renderComments(container) {
    try {
        const [comments, stats, tone, aiSettings] = await Promise.all([
            api('GET', `/accounts/${currentAccountId}/comments?filter=${commentsFilter}`),
            api('GET', `/accounts/${currentAccountId}/comments/stats`),
            api('GET', `/accounts/${currentAccountId}/comment-tone`),
            api('GET', '/ai-settings').catch(() => null),
        ]);

        const unsent = (stats.no_reply || 0) + (stats.drafts || 0) + (stats.failed || 0);
        const filters = [
            { key: 'unsent', label: 'Do wysłania', count: unsent },
            { key: 'all', label: 'Wszystkie', count: stats.total },
            { key: 'no_reply', label: 'Bez draftu', count: stats.no_reply },
            { key: 'draft', label: 'Wersje robocze', count: stats.drafts },
            { key: 'sent', label: 'Wysłane', count: stats.sent },
            { key: 'failed', label: 'Błędy', count: stats.failed },
        ];

        let html = `<div class="tab-content active">`;

        // Toolbar
        html += `<div class="comments-toolbar">
            <div class="comments-toolbar-row">
                <button class="btn btn-success" onclick="fetchComments()">Pobierz komentarze</button>
                <button class="btn" onclick="generateAllReplies()" ${!aiSettings ? 'disabled title="Skonfiguruj AI w ustawieniach"' : ''}>Generuj odpowiedzi AI</button>
                <button class="btn" onclick="sendAllReplies()" ${stats.drafts === 0 ? 'disabled' : ''}>Wyślij wszystkie (${stats.drafts})</button>
                <button class="btn btn-sm" onclick="exportComments()">Eksport JSON</button>
                <label class="btn btn-sm"><input type="file" accept=".json" onchange="importComments(event)" hidden>Import JSON</label>
                <button class="btn btn-sm" onclick="showAISettingsModal()">Ustawienia AI</button>
            </div>
            <div class="comments-filters">
                ${filters.map(f => `<button class="filter-btn ${commentsFilter === f.key ? 'active' : ''}"
                    onclick="commentsFilter='${f.key}';renderComments(document.getElementById('tab-content-area'))">
                    ${f.label}${f.count !== null ? ` (${f.count})` : ''}
                </button>`).join('')}
            </div>
        </div>`;

        if (comments.length === 0) {
            html += `<p style="color:var(--text-muted);padding:20px">Brak komentarzy${commentsFilter !== 'all' ? ' dla tego filtra' : '. Kliknij "Pobierz komentarze"'}.</p>`;
        } else {
            // Group by video
            const byVideo = {};
            comments.forEach(c => {
                const key = c.platform_video_id || 'unknown';
                if (!byVideo[key]) byVideo[key] = { title: c.video_title, url: c.video_url, desc: c.video_description, platform: c.platform, comments: [] };
                byVideo[key].comments.push(c);
            });

            const fixGroupUrl = (url, platform) => {
                if (!url) return '';
                if (url.startsWith('http')) return url;
                if (platform === 'facebook') return 'https://www.facebook.com' + url;
                if (platform === 'instagram') return 'https://www.instagram.com' + url;
                return url;
            };

            for (const [vid, group] of Object.entries(byVideo)) {
                const platBadge = group.platform === 'youtube' ? 'yt' : group.platform === 'instagram' ? 'ig' : 'fb';
                const platLabel = group.platform === 'youtube' ? 'YT' : group.platform === 'instagram' ? 'IG' : 'FB';
                const groupUrl = fixGroupUrl(group.url, group.platform);
                html += `<div class="comment-group">
                    <div class="comment-video-header">
                        <span class="platform-badge ${platBadge}">${platLabel}</span>
                        <a href="${esc(groupUrl)}" target="_blank" class="comment-video-title">${esc(group.title || 'Bez tytułu')}</a>
                        <span class="comment-video-count">${group.comments.length} komentarzy</span>
                        ${groupUrl ? `<a href="${esc(groupUrl)}" target="_blank" class="btn btn-sm comment-open-btn">Otworz</a>` : ''}
                    </div>`;

                group.comments.forEach(c => {
                    const statusCls = c.reply_status === 'sent' ? 'sent' : c.reply_status === 'failed' ? 'failed' :
                                      c.reply_status === 'draft' || c.reply_status === 'edited' ? 'draft' : 'none';
                    const statusLabel = {none: '', draft: 'Wersja robocza', edited: 'Edytowano', sending: 'Wysyłanie...', sent: 'Wysłano', failed: 'Błąd'}[c.reply_status] || '';
                    const date = c.comment_date ? new Date(c.comment_date).toLocaleDateString('pl-PL', {day:'numeric',month:'short',year:'numeric'}) : '';

                    // Build direct comment/video links (ensure full URLs)
                    const fixUrl = (url, platform) => {
                        if (!url) return '';
                        if (url.startsWith('http')) return url;
                        if (platform === 'facebook') return 'https://www.facebook.com' + url;
                        if (platform === 'instagram') return 'https://www.instagram.com' + url;
                        return url;
                    };
                    const videoFullUrl = fixUrl(c.video_url, c.platform);
                    let commentLink = '';
                    if (c.platform === 'youtube' && videoFullUrl && c.platform_comment_id) {
                        commentLink = videoFullUrl + '&lc=' + c.platform_comment_id;
                    } else if (c.platform === 'facebook' && c.platform_comment_id) {
                        commentLink = 'https://www.facebook.com/' + c.platform_comment_id;
                    } else if (videoFullUrl) {
                        commentLink = videoFullUrl;
                    }

                    html += `<div class="comment-card" data-id="${c.id}">
                        <div class="comment-header">
                            <strong class="comment-author">${c.commenter_profile_url ? `<a href="${esc(c.commenter_profile_url)}" target="_blank">${esc(c.commenter_name)}</a>` : esc(c.commenter_name)}</strong>
                            <span class="comment-date">${date}</span>
                            ${c.like_count ? `<span class="comment-likes">${c.like_count}</span>` : ''}
                            ${commentLink ? `<a href="${esc(commentLink)}" target="_blank" class="comment-direct-link" title="Zobacz komentarz na platformie">link</a>` : ''}
                            ${c.has_owner_reply && c.reply_status === 'none' ? '<span class="comment-replied-ext">Odpowiedziano</span>' : ''}
                            ${statusLabel ? `<span class="reply-status-badge ${statusCls}">${statusLabel}</span>` : ''}
                        </div>
                        <div class="comment-text">${esc(c.comment_text)}</div>
                        <div class="comment-reply-area">
                            <textarea class="comment-reply-input" id="reply-${c.id}" placeholder="Napisz odpowiedź...">${esc(c.reply_text || '')}</textarea>
                            <div class="comment-reply-actions">
                                <button class="btn btn-sm" onclick="saveReply(${c.id})">Zapisz</button>
                                <button class="btn btn-sm" onclick="generateSingleReply(${c.id})" ${!aiSettings ? 'disabled' : ''}>AI</button>
                                <button class="btn btn-success btn-sm" onclick="sendSingleReply(${c.id})" ${!c.reply_text || c.reply_status === 'sent' ? 'disabled' : ''}>${c.reply_status === 'sent' ? 'Wysłano' : 'Wyślij'}</button>
                                ${c.reply_error ? `<span class="reply-error" title="${esc(c.reply_error)}">Błąd</span>` : ''}
                            </div>
                        </div>
                    </div>`;
                });

                html += `</div>`;
            }
        }

        html += `</div>`;
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<div class="tab-content active"><p style="color:var(--red)">Błąd: ${e.message}</p></div>`;
    }
}

async function fetchComments() {
    try {
        toast('Pobieranie komentarzy...', 'info');
        const { job_id } = await api('POST', `/accounts/${currentAccountId}/comments/fetch`);
        pollJob(job_id, () => { toast('Komentarze pobrane', 'success'); switchTab('comments'); });
    } catch (e) { toast('Błąd: ' + e.message, 'error'); }
}

function pollJob(jobId, onDone) {
    const poll = async () => {
        try {
            const job = await api('GET', `/jobs/${jobId}`);
            if (job.status === 'done') { onDone(job); return; }
            if (job.status === 'failed') { toast(job.progress || 'Błąd', 'error'); return; }
            setTimeout(poll, 1500);
        } catch (e) { toast('Błąd pollowania: ' + e.message, 'error'); }
    };
    poll();
}

async function saveReply(commentId) {
    const text = document.getElementById(`reply-${commentId}`).value.trim();
    if (!text) return;
    try {
        await api('PUT', `/comments/${commentId}`, { reply_text: text });
        toast('Zapisano', 'success');
    } catch (e) { toast('Błąd: ' + e.message, 'error'); }
}

async function sendSingleReply(commentId) {
    const text = document.getElementById(`reply-${commentId}`).value.trim();
    if (text) await saveReply(commentId);
    try {
        await api('POST', `/comments/${commentId}/send`);
        toast('Wysłano', 'success');
        // Remove the card from view immediately
        const card = document.querySelector(`.comment-card[data-id="${commentId}"]`);
        if (card) card.remove();
    } catch (e) { toast('Błąd: ' + e.message, 'error'); }
}

async function generateSingleReply(commentId) {
    try {
        toast('Generowanie...', 'info');
        const { job_id } = await api('POST', `/accounts/${currentAccountId}/comments/generate-replies`, { comment_ids: [commentId] });
        pollJob(job_id, () => { toast('Wygenerowano', 'success'); switchTab('comments'); });
    } catch (e) { toast('Błąd: ' + e.message, 'error'); }
}

async function generateAllReplies() {
    try {
        toast('Generowanie odpowiedzi AI...', 'info');
        const { job_id, target_count } = await api('POST', `/accounts/${currentAccountId}/comments/generate-replies`, {});
        toast(`Generowanie ${target_count} odpowiedzi...`, 'info');
        pollJob(job_id, (job) => { toast(job.progress, 'success'); switchTab('comments'); });
    } catch (e) { toast('Błąd: ' + e.message, 'error'); }
}

async function sendAllReplies() {
    if (!confirm('Wysłać wszystkie wersje robocze?')) return;
    try {
        const { job_id, pending } = await api('POST', `/accounts/${currentAccountId}/comments/send-all`, {});
        toast(`Wysyłanie ${pending} odpowiedzi...`, 'info');
        pollJob(job_id, (job) => { toast(job.progress, 'success'); switchTab('comments'); });
    } catch (e) { toast('Błąd: ' + e.message, 'error'); }
}

async function exportComments() {
    try {
        const data = await api('GET', `/accounts/${currentAccountId}/comments/export?filter=${commentsFilter}`);
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `comments_${currentAccountId}_${new Date().toISOString().slice(0,10)}.json`;
        a.click();
        toast(`Wyeksportowano ${data.count} komentarzy`, 'success');
    } catch (e) { toast('Błąd: ' + e.message, 'error'); }
}

async function importComments(event) {
    const file = event.target.files[0];
    if (!file) return;
    try {
        const text = await file.text();
        const data = JSON.parse(text);
        const result = await api('POST', `/accounts/${currentAccountId}/comments/import`, data);
        toast(`Zaimportowano ${result.updated} odpowiedzi (pominięto ${result.skipped})`, 'success');
        switchTab('comments');
    } catch (e) { toast('Błąd importu: ' + e.message, 'error'); }
    event.target.value = '';
}

async function showAISettingsModal() {
    const [aiSettings, models, tones, currentTone] = await Promise.all([
        api('GET', '/ai-settings').catch(() => ({})),
        api('GET', '/ai-models').catch(() => ({})),
        api('GET', '/ai-tones').catch(() => ({})),
        api('GET', `/accounts/${currentAccountId}/comment-tone`).catch(() => ({ tone_preset: 'friendly', custom_tone: '' })),
    ]);

    const providerOptions = ['anthropic', 'openai', 'google'].map(p =>
        `<option value="${p}" ${aiSettings.provider === p ? 'selected' : ''}>${p === 'anthropic' ? 'Anthropic (Claude)' : p === 'openai' ? 'OpenAI (GPT)' : 'Google (Gemini)'}</option>`
    ).join('');

    const toneOptions = Object.entries(tones).map(([k, v]) =>
        `<option value="${k}" ${currentTone.tone_preset === k ? 'selected' : ''}>${k.charAt(0).toUpperCase() + k.slice(1)}</option>`
    ).join('') + `<option value="custom" ${currentTone.tone_preset === 'custom' ? 'selected' : ''}>Niestandardowy</option>`;

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    overlay.innerHTML = `<div class="modal ai-settings-modal">
        <h3>Ustawienia AI</h3>
        <div class="form-group">
            <label>Dostawca AI</label>
            <select id="ai-provider" onchange="updateModelList()">${providerOptions}</select>
        </div>
        <div class="form-group">
            <label>Klucz API</label>
            <input type="password" id="ai-api-key" placeholder="${aiSettings.api_key === '***configured***' ? 'Skonfigurowany (wpisz nowy aby zmienić)' : 'Wklej klucz API'}" value="">
        </div>
        <div class="form-group">
            <label>Model</label>
            <select id="ai-model"></select>
        </div>
        <hr>
        <h4>Ton odpowiedzi (${esc(accounts.find(a => a.id === currentAccountId)?.name || '')})</h4>
        <div class="form-group">
            <label>Predefiniowany styl</label>
            <select id="ai-tone" onchange="document.getElementById('ai-custom-tone').style.display = this.value === 'custom' ? 'block' : 'none'">${toneOptions}</select>
        </div>
        <div class="form-group">
            <textarea id="ai-custom-tone" placeholder="Opisz własny styl odpowiedzi..." style="display:${currentTone.tone_preset === 'custom' ? 'block' : 'none'}">${esc(currentTone.custom_tone || '')}</textarea>
        </div>
        <div class="modal-actions">
            <button class="btn" onclick="this.closest('.modal-overlay').remove()">Anuluj</button>
            <button class="btn btn-success" onclick="saveAISettings()">Zapisz</button>
        </div>
    </div>`;
    document.body.appendChild(overlay);

    // Store models data globally for the modal
    window._aiModels = models;
    updateModelList();

    function updateModelList() {
        const prov = document.getElementById('ai-provider').value;
        const sel = document.getElementById('ai-model');
        const provModels = window._aiModels[prov] || [];
        sel.innerHTML = provModels.map(m =>
            `<option value="${m.id}" ${aiSettings.model_name === m.id ? 'selected' : ''}>${m.name}</option>`
        ).join('');
    }
    window.updateModelList = updateModelList;
}

async function saveAISettings() {
    try {
        const provider = document.getElementById('ai-provider').value;
        const apiKey = document.getElementById('ai-api-key').value;
        const model = document.getElementById('ai-model').value;
        const tone = document.getElementById('ai-tone').value;
        const customTone = document.getElementById('ai-custom-tone').value;

        // Save AI settings (only if key provided)
        if (apiKey) {
            await api('PUT', '/ai-settings', { provider, api_key: apiKey, model_name: model });
        } else if (model) {
            // Try to save just the model change - need existing key
            const existing = await api('GET', '/ai-settings');
            if (existing.provider) {
                // Can't change without key if not set
            }
        }

        // Save tone for current account
        await api('PUT', `/accounts/${currentAccountId}/comment-tone`, {
            tone_preset: tone, custom_tone: customTone,
        });

        document.querySelector('.modal-overlay')?.remove();
        toast('Ustawienia AI zapisane', 'success');
    } catch (e) { toast('Błąd: ' + e.message, 'error'); }
}

// ── Drag & Drop Reorder ─────────────────────────────────────────────

let draggedId = null;

function dragStart(e) {
    draggedId = parseInt(e.currentTarget.dataset.id);
    e.currentTarget.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
}

function dragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const card = e.currentTarget;
    if (parseInt(card.dataset.id) !== draggedId) {
        card.classList.add('drag-over');
    }
}

function dragLeave(e) {
    e.currentTarget.classList.remove('drag-over');
}

function dragEnd(e) {
    e.currentTarget.classList.remove('dragging');
    document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
}

async function drop(e) {
    e.preventDefault();
    const targetId = parseInt(e.currentTarget.dataset.id);
    e.currentTarget.classList.remove('drag-over');

    if (draggedId === targetId) return;

    try {
        const videos = await api('GET', `/accounts/${currentAccountId}/videos?status=queued`);
        const ids = videos.map(v => v.id);
        const fromIdx = ids.indexOf(draggedId);
        const toIdx = ids.indexOf(targetId);
        if (fromIdx === -1 || toIdx === -1) return;
        ids.splice(fromIdx, 1);
        ids.splice(toIdx, 0, draggedId);
        await api('POST', `/accounts/${currentAccountId}/videos/reorder`, { video_ids: ids });
        switchTab('queue');
    } catch (e) {
        toast('B\u0142\u0105d: ' + e.message, 'error');
    }
}

// ── Modals ──────────────────────────────────────────────────────────

function showModal(title, bodyHtml, footerHtml = '') {
    const overlay = document.getElementById('modal-overlay');
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = bodyHtml;
    document.getElementById('modal-footer').innerHTML = footerHtml;
    overlay.classList.add('active');
}

function closeModal() {
    document.getElementById('modal-overlay').classList.remove('active');
}

function showConfirmModal(message, onConfirm) {
    showModal('Potwierd\u017a', `
        <div class="confirm-dialog">
            <p>${message}</p>
            <div class="btn-row">
                <button class="btn" onclick="closeModal()">Anuluj</button>
                <button class="btn btn-danger" id="confirm-btn">Tak, usu\u0144</button>
            </div>
        </div>`);
    document.getElementById('confirm-btn').onclick = () => { closeModal(); onConfirm(); };
}

// ── Edit Video Modal ────────────────────────────────────────────────

async function showEditVideoModal(videoId) {
    try {
        const video = await api('GET', `/videos/${videoId}`);
        const acc = accounts.find(a => a.id === video.account_id);
        const isYT = acc?.type === 'youtube';

        let body = `<div class="form-group">
            <label>Tytu\u0142</label>
            <input type="text" id="edit-title" value="${esc(video.title || '')}">
        </div>`;

        if (isYT) {
            body += `<div class="form-group">
                <label>Tytu\u0142 YouTube</label>
                <input type="text" id="edit-yt-title" value="${esc(video.yt_title || '')}">
            </div>
            <div class="form-group">
                <label>Opis YouTube</label>
                <textarea id="edit-yt-desc" rows="6">${esc(video.yt_description || '')}</textarea>
            </div>
            <div class="form-group">
                <label>Tagi</label>
                <input type="text" id="edit-yt-tags" value="${esc((JSON.parse(video.yt_tags || '[]')).join(', '))}">
            </div>
            <div class="form-group">
                <label>Prywatno\u015b\u0107</label>
                <select id="edit-yt-privacy">
                    <option value="public" ${video.yt_privacy === 'public' ? 'selected' : ''}>Publiczny</option>
                    <option value="unlisted" ${video.yt_privacy === 'unlisted' ? 'selected' : ''}>Niepubliczny</option>
                    <option value="private" ${video.yt_privacy === 'private' ? 'selected' : ''}>Prywatny</option>
                </select>
            </div>
            <div class="form-group">
                <label>Typ</label>
                <select id="edit-type">
                    <option value="short" ${video.video_type === 'short' ? 'selected' : ''}>Short</option>
                    <option value="video" ${video.video_type === 'video' ? 'selected' : ''}>Film</option>
                </select>
            </div>`;
        } else {
            body += `<div class="form-group">
                <label>Publikuj na</label>
                <div class="platform-toggles">
                    <label class="platform-toggle">
                        <input type="checkbox" id="edit-target-ig" ${video.target_ig !== 0 ? 'checked' : ''}>
                        Instagram
                    </label>
                    <label class="platform-toggle">
                        <input type="checkbox" id="edit-target-fb" ${video.target_fb !== 0 ? 'checked' : ''}>
                        Facebook
                    </label>
                </div>
            </div>
            <div class="form-group">
                <label>Opis Instagram (caption)</label>
                <textarea id="edit-caption" rows="6" maxlength="2200">${esc(video.caption || '')}</textarea>
                <div class="char-count" id="edit-char-count">${(video.caption || '').length} / 2200</div>
            </div>
            <div class="form-group">
                <label>Tytu\u0142 / Opis Facebook <span style="color:var(--text-muted)">(osobny, je\u015bli inny ni\u017c IG)</span></label>
                <textarea id="edit-fb-title" rows="4" placeholder="Je\u015bli puste, u\u017cyje opisu z Instagrama">${esc(video.fb_title || '')}</textarea>
            </div>
            <div class="form-group">
                <label>Typ</label>
                <select id="edit-type">
                    <option value="reel" ${video.video_type === 'reel' ? 'selected' : ''}>Reel</option>
                    <option value="story" ${video.video_type === 'story' ? 'selected' : ''}>Story</option>
                </select>
            </div>`;
        }

        body += `<div class="form-group">
            <label>Plik</label>
            <div style="font-family:var(--font-mono);font-size:12px;color:var(--text-dim)">${esc(video.filename)} \u2022 ${fmtSize(video.file_size || 0)}</div>
        </div>`;

        showModal('Edytuj film', body,
            `<button class="btn" onclick="closeModal()">Anuluj</button>
             <button class="btn btn-primary" onclick="saveVideoEdit(${videoId})">Zapisz</button>`);

        // Char counter
        const captionEl = document.getElementById('edit-caption');
        if (captionEl) {
            captionEl.addEventListener('input', () => {
                const c = captionEl.value.length;
                const counter = document.getElementById('edit-char-count');
                counter.textContent = `${c} / 2200`;
                counter.classList.toggle('over', c > 2200);
            });
        }
    } catch (e) {
        toast('B\u0142\u0105d: ' + e.message, 'error');
    }
}

async function saveVideoEdit(videoId) {
    const data = {};
    const title = document.getElementById('edit-title')?.value;
    if (title !== undefined) data.title = title;

    const caption = document.getElementById('edit-caption')?.value;
    if (caption !== undefined) data.caption = caption;

    const type = document.getElementById('edit-type')?.value;
    if (type) data.video_type = type;

    const ytTitle = document.getElementById('edit-yt-title')?.value;
    if (ytTitle !== undefined) data.yt_title = ytTitle;

    const ytDesc = document.getElementById('edit-yt-desc')?.value;
    if (ytDesc !== undefined) data.yt_description = ytDesc;

    const ytTags = document.getElementById('edit-yt-tags')?.value;
    if (ytTags !== undefined) data.yt_tags = ytTags.split(',').map(t => t.trim()).filter(Boolean);

    const ytPrivacy = document.getElementById('edit-yt-privacy')?.value;
    if (ytPrivacy) data.yt_privacy = ytPrivacy;

    // IG+FB platform targeting
    const targetIg = document.getElementById('edit-target-ig');
    if (targetIg) data.target_ig = targetIg.checked;
    const targetFb = document.getElementById('edit-target-fb');
    if (targetFb) data.target_fb = targetFb.checked;
    const fbTitle = document.getElementById('edit-fb-title');
    if (fbTitle) data.fb_title = fbTitle.value;

    try {
        await api('PUT', `/videos/${videoId}`, data);
        closeModal();
        toast('Film zaktualizowany', 'success');
        switchTab(currentTab);
    } catch (e) {
        toast('B\u0142\u0105d: ' + e.message, 'error');
    }
}

// ── Add Account Modal ───────────────────────────────────────────────

function showAddAccountModal() {
    const body = `
        <div class="form-group">
            <label>Typ konta</label>
            <select id="new-acc-type" onchange="toggleAccountFields()">
                <option value="instagram_facebook">Instagram + Facebook</option>
                <option value="youtube">YouTube</option>
            </select>
        </div>
        <div class="form-group">
            <label>Nazwa</label>
            <input type="text" id="new-acc-name" placeholder="np. Role Playing Live">
        </div>
        <div id="igfb-fields">
            <div class="form-group">
                <label>Facebook Page Access Token <span style="color:var(--text-muted)">(opcjonalnie)</span></label>
                <input type="password" id="new-acc-fb-token" placeholder="EAAx...">
                <div class="form-hint">Mo\u017cesz doda\u0107 token p\u00f3\u017aniej w Ustawieniach konta. Je\u015bli podasz teraz, aplikacja automatycznie pobierze ID strony i konto IG.</div>
            </div>
        </div>
        <div id="yt-fields" style="display:none">
            <div class="form-group">
                <label>Google OAuth Client ID <span style="color:var(--text-muted)">(opcjonalnie)</span></label>
                <input type="text" id="new-acc-yt-client" placeholder="xxxx.apps.googleusercontent.com">
            </div>
            <div class="form-group">
                <label>Client Secret</label>
                <input type="password" id="new-acc-yt-secret" placeholder="GOCSPX-...">
            </div>
            <div class="form-group">
                <label>Refresh Token</label>
                <input type="password" id="new-acc-yt-refresh" placeholder="1//...">
                <div class="form-hint">Mo\u017cesz skonfigurowa\u0107 p\u00f3\u017aniej w Ustawieniach.</div>
            </div>
        </div>`;

    showModal('Dodaj konto', body,
        `<button class="btn" onclick="closeModal()">Anuluj</button>
         <button class="btn btn-primary" onclick="createAccount()">Dodaj</button>`);
}

function toggleAccountFields() {
    const type = document.getElementById('new-acc-type').value;
    document.getElementById('igfb-fields').style.display = type === 'instagram_facebook' ? 'block' : 'none';
    document.getElementById('yt-fields').style.display = type === 'youtube' ? 'block' : 'none';
}

async function createAccount() {
    const type = document.getElementById('new-acc-type').value;
    const name = document.getElementById('new-acc-name').value.trim();
    if (!name) { toast('Podaj nazw\u0119 konta', 'error'); return; }

    const data = { name, type };
    if (type === 'instagram_facebook') {
        const token = document.getElementById('new-acc-fb-token').value.trim();
        if (token) data.fb_access_token = token;
    } else {
        const clientId = document.getElementById('new-acc-yt-client').value.trim();
        const secret = document.getElementById('new-acc-yt-secret').value.trim();
        const refresh = document.getElementById('new-acc-yt-refresh').value.trim();
        if (clientId) data.yt_client_id = clientId;
        if (secret) data.yt_client_secret = secret;
        if (refresh) data.yt_refresh_token = refresh;
    }

    try {
        const acc = await api('POST', '/accounts', data);
        closeModal();
        toast(`Konto "${name}" dodane`, 'success');
        currentAccountId = acc.id;
        await loadAccounts();
    } catch (e) {
        toast('B\u0142\u0105d: ' + e.message, 'error');
    }
}

// ── Account Actions ─────────────────────────────────────────────────

async function refreshAccount(accountId) {
    try {
        await api('POST', `/accounts/${accountId}/refresh`);
        toast('Dane od\u015bwie\u017cone', 'success');
        await loadAccounts();
    } catch (e) {
        toast('B\u0142\u0105d: ' + e.message, 'error');
    }
}

function confirmDeleteAccount(accountId) {
    const acc = accounts.find(a => a.id === accountId);
    showConfirmModal(`Usun\u0105\u0107 konto "${acc?.name}"? Wszystkie filmy zostan\u0105 usuni\u0119te!`, async () => {
        try {
            await api('DELETE', `/accounts/${accountId}`);
            toast('Konto usuni\u0119te', 'success');
            currentAccountId = null;
            await loadAccounts();
        } catch (e) {
            toast('B\u0142\u0105d: ' + e.message, 'error');
        }
    });
}

// ── YouTube OAuth & Sync ───────────────────────────────────────────

async function startYouTubeOAuth(accountId) {
    try {
        const result = await api('GET', `/youtube/oauth/start?account_id=${accountId}`);
        if (result.url) {
            toast('Przekierowanie do Google...', 'info');
            window.open(result.url, '_self');
        }
    } catch (e) {
        toast('B\u0142\u0105d: ' + e.message, 'error');
    }
}

async function syncPublished(accountId) {
    try {
        toast('Synchronizacja...', 'info');
        const result = await api('POST', `/accounts/${accountId}/sync-published`);
        if (result.errors?.length) {
            toast(`Zsynchronizowano ${result.synced} film\u00f3w, b\u0142\u0119dy: ${result.errors.join('; ')}`, 'error');
        } else {
            toast(`Zsynchronizowano ${result.synced} nowych film\u00f3w (${result.total_on_platform} na platformie)`, 'success');
        }
        await loadAccounts();
    } catch (e) {
        toast('B\u0142\u0105d: ' + e.message, 'error');
    }
}

// ── Utilities ───────────────────────────────────────────────────────

function esc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

function fmtNum(n) {
    if (!n) return '0';
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return String(n);
}

function fmtSize(bytes) {
    if (!bytes) return '0B';
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + 'GB';
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + 'MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(0) + 'KB';
    return bytes + 'B';
}

function fmtDate(str) {
    if (!str) return '';
    try {
        const d = new Date(str);
        return d.toLocaleDateString('pl-PL', { day: '2-digit', month: '2-digit', year: 'numeric' })
            + ' ' + d.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' });
    } catch { return str; }
}

function fmtDateFull(str) {
    if (!str) return '';
    try {
        const d = new Date(str);
        const days = ['nd', 'pn', 'wt', '\u015br', 'cz', 'pt', 'sb'];
        const day = days[d.getDay()];
        const dd = String(d.getDate()).padStart(2, '0');
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const hh = String(d.getHours()).padStart(2, '0');
        const mi = String(d.getMinutes()).padStart(2, '0');
        return `${day} ${dd}.${mm} ${hh}:${mi}`;
    } catch { return str; }
}

// ── Init ────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    const saved = localStorage.getItem('smm_token');
    if (saved) {
        TOKEN = saved;
        api('GET', '/stats').then(() => {
            showApp();
            loadAccounts();
            // Handle OAuth success redirect
            if (window.location.hash === '#oauth-success') {
                toast('YouTube OAuth zako\u0144czony pomy\u015blnie!', 'success');
                window.location.hash = '';
            }
        }).catch(() => showLogin());
    } else {
        showLogin();
    }

    // Close modal on overlay click
    document.getElementById('modal-overlay').addEventListener('click', e => {
        if (e.target === e.currentTarget) closeModal();
    });

    // ESC to close modal
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') closeModal();
    });

    // Login on Enter
    document.getElementById('login-password').addEventListener('keydown', e => {
        if (e.key === 'Enter') doLogin();
    });
});

// 全局状态
        let csrfToken = null;
        let csrfTokenRefreshPromise = null;
        let currentAccount = null;
        let currentGroupId = null;
        let currentEmails = [];
        let currentMethod = 'graph';
        let currentFolder = 'inbox';
        let isListVisible = true;
        let groups = [];
        let accountsCache = {};
        let editingGroupId = null;
        let selectedColor = '#B85C38';
        let isTempEmailGroup = false;
        let tempEmailGroupId = null;
        let isLoadingMore = false;
        let hasMoreEmails = true;
        let currentSkip = 0;
        let lastRefreshTime = null;
        let mailboxViewMode = localStorage.getItem('ol_mailbox_view_mode') || 'standard';
        let latestInvalidTokenDetectedCount = 0;
        let invalidTokenGovernanceCandidates = [];
        let selectedInvalidTokenCandidateIds = new Set();

        // 缓存与信任模式
        let emailListCache = {};
        let currentEmailDetail = null;
        let isTrustedMode = false;

        // 轮询相关（Phase 2: 变量保留用于设置读写，实际轮询由统一引擎处理）
        let maxPollingCount = 5;
        let pollingInterval = 10;
        let autoPollingEnabled = false;
        // [Phase 3] compact 独立变量已废弃，统一使用上方标准字段

        // 导航状态
        let currentPage = 'dashboard';
        let accountPanelDensitySyncHandle = null;

        // ==================== 布局状态管理 (ui_layout_v2) ====================
        // 布局状态缓存
        let uiLayoutV2 = null;
        let layoutSaveDebounceTimer = null;
        const LAYOUT_SAVE_DEBOUNCE_MS = 2000;

        // 默认布局状态
        function getDefaultLayoutV2() {
            return {
                version: 2,
                sidebar: { collapsed: false },
                mailbox: { groupPanelWidth: 220, accountPanelWidth: 280 },
                tempEmails: { listPanelWidth: 300 }
            };
        }

        // 从后端读取布局状态
        async function loadLayoutFromServer() {
            try {
                const response = await fetch('/api/bootstrap');
                const data = await response.json();
                if (data.success && data.bootstrap) {
                    // 缓存轮询设置供 initPollingSettings 使用，避免重复请求
                    if (!window.__bootstrapPollingSettings) {
                        window.__bootstrapPollingSettings = data.bootstrap;
                    }
                    if (data.bootstrap.ui_layout_v2) {
                        const layout = data.bootstrap.ui_layout_v2;
                        if (layout.version === 2) {
                            uiLayoutV2 = layout;
                            return layout;
                        }
                    }
                }
            } catch (error) {
                console.warn('加载布局状态失败:', error);
            }
            return null;
        }

        // 迁移旧 localStorage key 到 ui_layout_v2
        function migrateOldLayoutKeys() {
            const migrated = { version: 2, sidebar: {}, mailbox: {}, tempEmails: {} };
            let needsMigration = false;

            try {
                // 迁移侧边栏折叠状态
                const oldSidebarCollapsed = localStorage.getItem('ol_sidebar_collapsed');
                if (oldSidebarCollapsed !== null) {
                    migrated.sidebar.collapsed = oldSidebarCollapsed === 'true';
                    needsMigration = true;
                } else {
                    migrated.sidebar.collapsed = false;
                }

                // 迁移列宽
                const oldColumnWidths = localStorage.getItem('ol_column_widths');
                if (oldColumnWidths) {
                    try {
                        const widths = JSON.parse(oldColumnWidths);
                        // groupPanel / accountPanel 的宽度迁移
                        if (widths.groupPanel) {
                            const w = parseInt(widths.groupPanel, 10);
                            if (!isNaN(w) && w > 0) {
                                migrated.mailbox.groupPanelWidth = w;
                                needsMigration = true;
                            }
                        }
                        if (widths.accountPanel) {
                            const w = parseInt(widths.accountPanel, 10);
                            if (!isNaN(w) && w > 0) {
                                migrated.mailbox.accountPanelWidth = w;
                                needsMigration = true;
                            }
                        }
                        // temp-emails 列宽迁移（如果有）
                        if (widths.tempEmailPanel) {
                            const w = parseInt(widths.tempEmailPanel, 10);
                            if (!isNaN(w) && w > 0) {
                                migrated.tempEmails.listPanelWidth = w;
                                needsMigration = true;
                            }
                        }
                    } catch (e) {
                        console.warn('解析旧列宽数据失败:', e);
                    }
                }

                // 设置默认值
                if (!migrated.mailbox.groupPanelWidth) migrated.mailbox.groupPanelWidth = 220;
                if (!migrated.mailbox.accountPanelWidth) migrated.mailbox.accountPanelWidth = 280;
                if (!migrated.tempEmails.listPanelWidth) migrated.tempEmails.listPanelWidth = 300;

            } catch (e) {
                console.warn('迁移布局状态失败:', e);
                return null;
            }

            return needsMigration ? migrated : null;
        }

        // 清理旧 localStorage key（可选，迁移成功后调用）
        function cleanupOldLayoutKeys() {
            try {
                localStorage.removeItem('ol_sidebar_collapsed');
                localStorage.removeItem('ol_column_widths');
            } catch (e) {}
        }

        // 保存布局状态到后端（带 debounce）
        function saveLayoutToServer() {
            if (!uiLayoutV2) return;

            if (layoutSaveDebounceTimer) {
                clearTimeout(layoutSaveDebounceTimer);
            }

            layoutSaveDebounceTimer = setTimeout(async () => {
                try {
                    await fetch('/api/settings', {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ui_layout_v2: uiLayoutV2 })
                    });
                } catch (error) {
                    console.warn('保存布局状态失败:', error);
                }
            }, LAYOUT_SAVE_DEBOUNCE_MS);
        }

        // 初始化布局状态
        async function initLayoutState() {
            // 1. 先尝试从后端加载
            let layout = await loadLayoutFromServer();

            // 2. 如果后端没有有效布局，尝试迁移旧 key
            if (!layout) {
                const migrated = migrateOldLayoutKeys();
                if (migrated) {
                    uiLayoutV2 = migrated;
                    // 保存迁移结果到后端
                    try {
                        await fetch('/api/settings', {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ ui_layout_v2: migrated })
                        });
                        // 迁移成功后清理旧 key
                        cleanupOldLayoutKeys();
                        console.log('布局状态迁移完成');
                    } catch (e) {
                        console.warn('保存迁移布局失败:', e);
                    }
                } else {
                    // 使用默认布局
                    uiLayoutV2 = getDefaultLayoutV2();
                }
            } else {
                uiLayoutV2 = layout;
            }

            // 3. 应用布局状态
            applyLayoutState();
        }

        // 应用布局状态到 DOM
        function applyLayoutState() {
            if (!uiLayoutV2) return;

            // 应用侧边栏折叠状态
            const app = document.getElementById('app');
            if (app && uiLayoutV2.sidebar && uiLayoutV2.sidebar.collapsed) {
                app.classList.add('sidebar-collapsed');
            }

            // 应用 mailbox 列宽
            if (uiLayoutV2.mailbox) {
                const groupPanel = document.getElementById('groupPanel');
                const accountPanel = document.getElementById('accountPanel');
                if (groupPanel && uiLayoutV2.mailbox.groupPanelWidth) {
                    groupPanel.style.width = uiLayoutV2.mailbox.groupPanelWidth + 'px';
                }
                if (accountPanel && uiLayoutV2.mailbox.accountPanelWidth) {
                    accountPanel.style.width = uiLayoutV2.mailbox.accountPanelWidth + 'px';
                }
            }

            // 应用 temp-emails 列宽
            if (uiLayoutV2.tempEmails) {
                const tempEmailPanel = document.getElementById('tempEmailPanel');
                if (tempEmailPanel && uiLayoutV2.tempEmails.listPanelWidth) {
                    tempEmailPanel.style.width = uiLayoutV2.tempEmails.listPanelWidth + 'px';
                }
            }
        }

        // 更新布局状态中的侧边栏折叠
        function updateLayoutSidebarCollapsed(collapsed) {
            if (!uiLayoutV2) uiLayoutV2 = getDefaultLayoutV2();
            uiLayoutV2.sidebar.collapsed = collapsed;
            saveLayoutToServer();
        }

        // 更新布局状态中的列宽
        function updateLayoutColumnWidths() {
            if (!uiLayoutV2) uiLayoutV2 = getDefaultLayoutV2();

            // 读取 mailbox 列宽
            const groupPanel = document.getElementById('groupPanel');
            const accountPanel = document.getElementById('accountPanel');
            if (groupPanel && groupPanel.style.width) {
                const w = parseInt(groupPanel.style.width, 10);
                if (!isNaN(w) && w > 0) {
                    uiLayoutV2.mailbox.groupPanelWidth = w;
                }
            }
            if (accountPanel && accountPanel.style.width) {
                const w = parseInt(accountPanel.style.width, 10);
                if (!isNaN(w) && w > 0) {
                    uiLayoutV2.mailbox.accountPanelWidth = w;
                }
            }

            // 读取 temp-emails 列宽
            const tempEmailPanel = document.getElementById('tempEmailPanel');
            if (tempEmailPanel && tempEmailPanel.style.width) {
                const w = parseInt(tempEmailPanel.style.width, 10);
                if (!isNaN(w) && w > 0) {
                    uiLayoutV2.tempEmails.listPanelWidth = w;
                }
            }

            saveLayoutToServer();
        }

        function getUiLanguage() {
            return window.getCurrentUiLanguage ? window.getCurrentUiLanguage() : 'zh';
        }

        function translateAppTextLocal(text) {
            return window.translateAppText ? window.translateAppText(text) : text;
        }

        function formatGroupDisplayName(name) {
            return translateAppTextLocal(String(name || '').trim());
        }

        function formatGroupDescription(description, fallback = '未填写说明') {
            const rawDescription = String(description || '').trim();
            return translateAppTextLocal(rawDescription || fallback);
        }

        function isTempMailboxGroup(groupOrName) {
            const rawName = typeof groupOrName === 'string'
                ? String(groupOrName || '').trim()
                : String(groupOrName?.name || '').trim();
            return rawName === '临时邮箱' || rawName === 'Temp Mailboxes' || rawName === 'Temp Mailbox';
        }

        function formatAccountStatusLabel(status) {
            const normalized = String(status || 'active').trim().toLowerCase();
            const zhStatusMap = {
                active: '正常',
                inactive: '停用',
                disabled: '停用',
                paused: '停用'
            };
            return translateAppTextLocal(zhStatusMap[normalized] || normalized || '正常');
        }

        function isRefreshableOutlookAccount(accountLike) {
            const accountType = String(accountLike?.account_type || 'outlook').trim().toLowerCase();
            const provider = String(accountLike?.provider || 'outlook').trim().toLowerCase();
            return accountType !== 'imap' && provider === 'outlook';
        }

        function formatSelectedItemsLabel(count) {
            return getUiLanguage() === 'en' ? `${count} selected` : `已选 ${count} 项`;
        }

        const pickApiMessage = (payload, fallbackZh, fallbackEn) => (
            window.pickApiMessage ? window.pickApiMessage(payload, fallbackZh, fallbackEn) : (fallbackZh || fallbackEn || '')
        );

        const formatUiDateTime = (dateStr, options = {}) => (
            window.formatUiDateTime ? window.formatUiDateTime(dateStr, options) : (dateStr || '')
        );

        const formatUiRelativeTime = (dateStr, fallbackZh = '从未刷新', fallbackEn = 'Never refreshed') => (
            window.formatUiRelativeTime ? window.formatUiRelativeTime(dateStr, fallbackZh, fallbackEn) : (dateStr || fallbackZh)
        );

        function parseIntegerSetting(value, fallback) {
            if (value === null || value === undefined) {
                return fallback;
            }
            const normalized = String(value).trim();
            if (!normalized) {
                return fallback;
            }
            const parsed = Number.parseInt(normalized, 10);
            return Number.isNaN(parsed) ? fallback : parsed;
        }

        function isAutoPollingEnabledSetting(value) {
            return value === true || value === 'true';
        }

        // 应用标准轮询设置到内部变量（Phase 2: 仅更新变量，实际轮询由统一引擎处理）
        function applyPollingSettings(settings, { restart = false } = {}) {
            // [Phase 3 兼容] 任一开关开启即启用轮询：
            // - enable_auto_polling：合并后的统一开关
            // - enable_compact_auto_poll：deprecated 旧字段，历史用户可能只设置了这个
            autoPollingEnabled = isAutoPollingEnabledSetting(settings.enable_auto_polling)
                || isAutoPollingEnabledSetting(settings.enable_compact_auto_poll);
            maxPollingCount = parseIntegerSetting(settings.polling_count, 5);
            pollingInterval = parseIntegerSetting(settings.polling_interval, 10);
            // [Phase 3] 合并后统一由标准字段驱动引擎
            if (typeof applyPollSettings === 'function') {
                applyPollSettings({
                    enabled: autoPollingEnabled,
                    interval: pollingInterval,
                    maxCount: maxPollingCount
                });
            }
        }

        // ==================== 标准模式轮询指示器 ====================
        // 在标准模式下，在账号卡片邮箱地址旁显示/隐藏轮询绿点。
        // 由统一轮询引擎通过 UI 回调调用（mailbox_compact.js 中根据 mailboxViewMode 分发）。

        function showStandardPollDot(email) {
            if (!email) return;
            var allCards = document.querySelectorAll('#accountList .account-card');
            allCards.forEach(function(card) {
                var emailEl = card.querySelector('.account-email');
                if (emailEl && emailEl.textContent.trim() === email) {
                    // 在 .account-info 容器中添加状态行（避免 .account-email 的 overflow:hidden 裁剪）
                    var infoEl = card.querySelector('.account-info');
                    if (infoEl && !infoEl.querySelector('.standard-poll-status')) {
                        var statusEl = document.createElement('div');
                        statusEl.className = 'standard-poll-status';
                        statusEl.innerHTML = '<span class="standard-poll-dot"></span>' + translateAppTextLocal('轮询监听中…');
                        infoEl.appendChild(statusEl);
                    }
                    // 给卡片加上边框高亮
                    card.classList.add('standard-poll-active');
                }
            });
        }

        function hideStandardPollDot(email) {
            if (email) {
                var allCards = document.querySelectorAll('#accountList .account-card');
                allCards.forEach(function(card) {
                    var emailEl = card.querySelector('.account-email');
                    if (emailEl && emailEl.textContent.trim() === email) {
                        var infoEl = card.querySelector('.account-info');
                        if (infoEl) {
                            var statusEl = infoEl.querySelector('.standard-poll-status');
                            if (statusEl) statusEl.remove();
                        }
                        card.classList.remove('standard-poll-active');
                    }
                });
            } else {
                // 无参数时清除所有
                document.querySelectorAll('.standard-poll-status').forEach(function(el) { el.remove(); });
                document.querySelectorAll('.standard-poll-active').forEach(function(el) { el.classList.remove('standard-poll-active'); });
            }
        }

        // ==================== 主题 & 导航 ====================

        function applyUiStyle(style) {
            const normalizedStyle = style === 'dashboard' ? 'dashboard' : 'classic';
            document.documentElement.dataset.uiStyle = normalizedStyle;
            localStorage.setItem('ol_ui_style', normalizedStyle);
            const select = document.getElementById('uiStyleSelect');
            if (select) select.value = normalizedStyle;
        }

        function applyTheme(theme) {
            document.documentElement.dataset.theme = theme;
            localStorage.setItem('ol_theme', theme);
            const btn = document.getElementById('themeToggleBtn');
            if (btn) btn.textContent = theme === 'dark' ? '☀ 浅色模式' : '☾ 深色模式';
        }

        function toggleTheme() {
            const current = document.documentElement.dataset.theme || 'light';
            applyTheme(current === 'dark' ? 'light' : 'dark');
        }

        function applyAccountPanelDensityClasses(panel, width) {
            panel.classList.toggle('is-narrow', width < 240);
            panel.classList.toggle('is-compact', width < 170);
        }

        function navigate(page) {
            currentPage = page;
            // Hide all pages
            document.querySelectorAll('.page').forEach(p => p.classList.add('page-hidden'));
            const target = document.getElementById('page-' + page);
            if (target) {
                target.classList.remove('page-hidden');
                target.style.display = '';
            }
            // Update nav active state
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            const navBtn = document.querySelector(`.nav-item[data-page="${page}"]`);
            if (navBtn) navBtn.classList.add('active');
            // Update topbar
            updateTopbar(page);
            // Close mobile sidebar
            closeSidebar();
            // Load page data
            if (page === 'dashboard' && typeof initOverview === 'function') initOverview();
            if (page === 'mailbox') {
                if (groups.length === 0) {
                    loadGroups();
                } else if (currentGroupId) {
                    loadAccountsByGroup(currentGroupId);
                }
                if (typeof switchMailboxViewMode === 'function') {
                    switchMailboxViewMode(mailboxViewMode);
                }
                syncAccountPanelDensityIfVisible();
                scheduleAccountPanelDensitySync();
            }
            if (page === 'temp-emails' && typeof loadTempEmails === 'function') loadTempEmails(true);
            if (page === 'settings') loadSettings();
            if (page === 'refresh-log') loadRefreshLogPage();
            if (page === 'pool-admin' && typeof loadPoolAdmin === 'function') loadPoolAdmin(true);
            if (page === 'audit') loadAuditLogPage();
            if (page === 'diagnostics') loadDiagnosticsPage();
        }

        function updateTopbar(page) {
            const titleEl = document.getElementById('topbarTitle');
            const subtitleEl = document.getElementById('topbarSubtitle');
            const actionsEl = document.getElementById('topbar-actions');
            const mailboxViewModeTemplate = document.getElementById('mailboxViewModeSwitcherTemplate');
            const titles = {
                'dashboard': ['数据概览', '运营数据大盘'],
                'mailbox': ['账号管理', '管理邮箱账号与查看邮件'],
                'temp-emails': ['临时邮箱', '创建和管理临时邮箱'],
                'refresh-log': ['刷新日志', 'Token 刷新历史记录'],
                'settings': ['系统设置', '配置系统参数'],
                'pool-admin': ['号池管理', '邮箱池状态维护与调度'],
                'audit': ['审计日志', '系统操作记录'],
                'diagnostics': ['诊断中心', '系统状态与错误关联查询']
            };
            const t = titles[page] || [page, ''];
            if (titleEl) titleEl.textContent = translateAppTextLocal(t[0]);
            if (subtitleEl) subtitleEl.textContent = translateAppTextLocal(t[1]);
            // Context actions
            if (actionsEl) {
                actionsEl.classList.remove('topbar-actions-compact');
                if (page === 'mailbox') {
                    const switcherHtml = mailboxViewModeTemplate ? mailboxViewModeTemplate.innerHTML.trim() : '';
                    const isCompactMode = mailboxViewMode === 'compact';
                    actionsEl.innerHTML = isCompactMode ? `
                        ${switcherHtml}
                    ` : `
                        ${switcherHtml}
                        <button class="btn-inline primary" onclick="showAddAccountModal()">＋ 添加账号</button>
                        <button class="btn-inline ghost" onclick="showExportModal()">📤 导出</button>
                        <button class="btn-inline ghost" onclick="showRefreshModal()">🔄 全量刷新 Token</button>
                    `;
                    actionsEl.classList.toggle('topbar-actions-compact', isCompactMode);
                    if (subtitleEl) {
                        subtitleEl.textContent = translateAppTextLocal(
                            isCompactMode ? '按分组查看账号摘要与验证码' : '管理邮箱账号与查看邮件'
                        );
                    }
                    const standardBtn = document.getElementById('mailboxStandardModeBtn');
                    const compactBtn = document.getElementById('mailboxCompactModeBtn');
                    if (standardBtn) {
                        standardBtn.classList.toggle('active', mailboxViewMode === 'standard');
                    }
                    if (compactBtn) {
                        compactBtn.classList.toggle('active', mailboxViewMode === 'compact');
                    }
                } else if (page === 'temp-emails') {
                    actionsEl.innerHTML = `
                        <button class="btn btn-sm btn-primary" onclick="generateTempEmail()">＋ 创建邮箱</button>
                    `;
                } else {
                    actionsEl.innerHTML = '';
                }
            }
        }

        function toggleSidebar() {
            const isMobile = window.innerWidth <= 768;
            if (isMobile) {
                // Mobile: toggle drawer
                const sidebar = document.getElementById('sidebar');
                const backdrop = document.getElementById('sidebarBackdrop');
                sidebar.classList.toggle('mob-open');
                backdrop.classList.toggle('show');
            } else {
                // Desktop: toggle collapsed state
                const app = document.getElementById('app');
                app.classList.toggle('sidebar-collapsed');
                const collapsed = app.classList.contains('sidebar-collapsed');
                // 使用新的布局状态管理保存
                updateLayoutSidebarCollapsed(collapsed);
            }
        }

        function closeSidebar() {
            const sidebar = document.getElementById('sidebar');
            const backdrop = document.getElementById('sidebarBackdrop');
            if (sidebar) sidebar.classList.remove('mob-open');
            if (backdrop) backdrop.classList.remove('show');
        }

        function logout() {
            if (!confirm(translateAppTextLocal('确认退出登录？'))) return;
            window.location.href = '/logout';
        }

        // ==================== 分组搜索过滤 ====================

        function filterGroups(query) {
            const items = document.querySelectorAll('#groupList .group-item');
            const q = query.toLowerCase();
            items.forEach(item => {
                const name = item.querySelector('.group-name');
                if (name && name.textContent.toLowerCase().includes(q)) {
                    item.style.display = '';
                } else {
                    item.style.display = q ? 'none' : '';
                }
            });
        }

        // ==================== 三栏拖拽调整 ====================

        function updateAccountPanelDensity() {
            const panel = document.getElementById('accountPanel');
            if (!panel) return;
            const width = panel.getBoundingClientRect().width;
            applyAccountPanelDensityClasses(panel, width);
        }

        function syncAccountPanelDensityIfVisible() {
            const page = document.getElementById('page-mailbox');
            const panel = document.getElementById('accountPanel');
            if (!page || !panel || page.classList.contains('page-hidden')) {
                return false;
            }

            const width = panel.getBoundingClientRect().width;
            if (width <= 0) {
                return false;
            }

            applyAccountPanelDensityClasses(panel, width);
            return true;
        }

        function scheduleAccountPanelDensitySync() {
            // 使用双层 rAF（以及 setTimeout fallback）刻意等待切页/拖拽后的布局回流完成，
            // 避免首次进入 mailbox 时按 0 宽或旧宽度错误计算紧凑模式。
            const runSync = () => {
                accountPanelDensitySyncHandle = null;
                syncAccountPanelDensityIfVisible();
            };

            if (accountPanelDensitySyncHandle !== null) {
                if (typeof cancelAnimationFrame === 'function') {
                    cancelAnimationFrame(accountPanelDensitySyncHandle);
                } else {
                    clearTimeout(accountPanelDensitySyncHandle);
                }
                accountPanelDensitySyncHandle = null;
            }

            if (typeof requestAnimationFrame === 'function') {
                accountPanelDensitySyncHandle = requestAnimationFrame(() => {
                    accountPanelDensitySyncHandle = requestAnimationFrame(runSync);
                });
                return;
            }

            accountPanelDensitySyncHandle = setTimeout(runSync, 0);
        }

        function initResizeHandles() {
            // 支持新的 .workspace-resizer 和旧的 .resize-handle 类名
            document.querySelectorAll('.workspace-resizer, .resize-handle').forEach(handle => {
                handle.addEventListener('mousedown', function(e) {
                    e.preventDefault();
                    const leftId = this.dataset.left;
                    const rightId = this.dataset.right;
                    const leftPanel = document.getElementById(leftId);
                    const rightPanel = document.getElementById(rightId);
                    if (!leftPanel) return;

                    this.classList.add('active');
                    document.body.style.cursor = 'col-resize';
                    document.body.style.userSelect = 'none';

                    const startX = e.clientX;
                    const startWidth = leftPanel.offsetWidth;

                    function onMouseMove(ev) {
                        const delta = ev.clientX - startX;
                        const newWidth = Math.max(120, Math.min(startWidth + delta, 500));
                        leftPanel.style.width = newWidth + 'px';
                        updateAccountPanelDensity();
                    }

                    function onMouseUp() {
                        handle.classList.remove('active');
                        document.body.style.cursor = '';
                        document.body.style.userSelect = '';
                        document.removeEventListener('mousemove', onMouseMove);
                        document.removeEventListener('mouseup', onMouseUp);
                        // 使用新的布局状态管理保存列宽
                        updateLayoutColumnWidths();
                    }

                    document.addEventListener('mousemove', onMouseMove);
                    document.addEventListener('mouseup', onMouseUp);
                });
            });

            // 布局状态已在 initLayoutState() 中恢复，这里只需更新紧凑模式
            if (currentPage === 'mailbox') {
                syncAccountPanelDensityIfVisible();
                scheduleAccountPanelDensitySync();
            }
            window.addEventListener('resize', scheduleAccountPanelDensitySync, { passive: true });
        }

        // 平板断点 groups 栏展开/折叠 — 方案 B: 点击 ☰ 按钮后 groups 作为浮动面板覆盖在内容上方
        // 仅在平板断点(769-1024px)下有意义，按钮由 CSS .btn-toggle-groups 控制显隐
        // HTML 绑定: index.html 中 #btnToggleGroups onclick="toggleGroupsColumn()"
        function toggleGroupsColumn() {
            const groupPanel = document.getElementById('groupPanel');
            const btn = document.getElementById('btnToggleGroups');
            if (!groupPanel) return;
            const isExpanded = groupPanel.classList.toggle('groups-expanded');
            if (isExpanded) {
                groupPanel.style.display = 'flex';
                groupPanel.style.position = 'absolute';
                groupPanel.style.left = '60px';
                groupPanel.style.top = '52px';
                groupPanel.style.height = 'calc(100vh - 52px)';
                groupPanel.style.width = '220px';
                groupPanel.style.zIndex = '20';
                groupPanel.style.boxShadow = '4px 0 24px rgba(0,0,0,0.25)';
                groupPanel.style.borderRight = '1px solid var(--border)';
                groupPanel.style.background = 'var(--bg-card)';
            } else {
                groupPanel.style.cssText = '';
                handleResponsiveGroups();
            }
            if (btn) {
                btn.title = isExpanded ? translateAppTextLocal('收起分组') : translateAppTextLocal('展开分组');
            }
        }

        // resize 监听: 窗口尺寸变化时自动同步 groups 栏显隐状态
        // 与 CSS @media 断点(768/1024px) 配合，但通过 JS 内联 style 确保即时生效
        // 展开(groups-expanded)状态下不干预，避免覆盖用户操作
        function handleResponsiveGroups() {
            const groupPanel = document.getElementById('groupPanel');
            if (!groupPanel) return;
            const isExpanded = groupPanel.classList.contains('groups-expanded');
            // 展开状态下不干预
            if (isExpanded) return;
            const width = window.innerWidth;
            if (width > 768 && width <= 1024) {
                groupPanel.style.display = 'none';
            } else {
                groupPanel.style.cssText = '';
            }
        }
        window.addEventListener('resize', handleResponsiveGroups, { passive: true });

        // ==================== 邮件详情显示控制 ====================

        function showEmailDetailSection() {
            const section = document.getElementById('emailDetailSection');
            if (section) section.style.display = 'flex';
        }

        function hideEmailDetailSection() {
            const section = document.getElementById('emailDetailSection');
            if (section) section.style.display = 'none';
        }

        function stopRefresh() {
            // Placeholder for stopping a bulk refresh operation
            showToast(translateAppTextLocal('刷新已停止'), 'warn');
            const bar = document.getElementById('refreshProgressBar');
            if (bar) bar.style.display = 'none';
        }

        // ==================== CSRF 防护 ====================

        function isMutationRequest(method) {
            const normalizedMethod = (method || 'GET').toUpperCase();
            return !['GET', 'HEAD', 'OPTIONS'].includes(normalizedMethod);
        }

        function cloneHeaders(headers) {
            return new Headers(headers || {});
        }

        function buildFetchRequest(input, options = {}) {
            if (input instanceof Request) {
                const mergedHeaders = cloneHeaders(input.headers);
                const optionHeaders = cloneHeaders(options.headers);
                optionHeaders.forEach((value, key) => mergedHeaders.set(key, value));

                const requestOptions = {
                    ...options,
                    headers: mergedHeaders
                };

                return {
                    method: (requestOptions.method || input.method || 'GET').toUpperCase(),
                    setHeader(name, value) {
                        mergedHeaders.set(name, value);
                    },
                    execute() {
                        return originalFetch(new Request(input, requestOptions));
                    }
                };
            }

            const requestOptions = {
                ...options,
                headers: cloneHeaders(options.headers)
            };

            return {
                method: (requestOptions.method || 'GET').toUpperCase(),
                setHeader(name, value) {
                    requestOptions.headers.set(name, value);
                },
                execute() {
                    return originalFetch(input, requestOptions);
                }
            };
        }

        async function parseJsonSafely(response) {
            const contentType = response.headers.get('content-type') || '';
            if (!contentType.includes('application/json')) {
                return null;
            }

            try {
                return await response.clone().json();
            } catch (error) {
                return null;
            }
        }

        function isCsrfFailurePayload(payload) {
            if (!payload || typeof payload !== 'object') {
                return false;
            }

            const error = payload.error && typeof payload.error === 'object' ? payload.error : payload;
            return error.code === 'CSRF_TOKEN_INVALID';
        }

        // 初始化 CSRF Token
        async function initCSRFToken({ force = false, silent = false } = {}) {
            if (!force && csrfToken) {
                return csrfToken;
            }

            // 单飞刷新：并发写请求共享同一次 token 拉取；若后端明确返回 CSRF_TOKEN_INVALID，
            // fetch 包装层会强制刷新 token 并只重放一次原请求，避免无限重试或抢刷 token。
            if (csrfTokenRefreshPromise) {
                return csrfTokenRefreshPromise;
            }

            csrfTokenRefreshPromise = (async () => {
                try {
                    const response = await originalFetch('/api/csrf-token');
                    if (!response.ok) {
                        throw new Error(`csrf_token_http_${response.status}`);
                    }

                    const data = await response.json();
                    if (data.csrf_disabled) {
                        csrfToken = null;
                        console.warn('CSRF protection is disabled. Install flask-wtf for better security.');
                        return csrfToken;
                    }

                    if (!data.csrf_token) {
                        throw new Error('csrf_token_missing_in_response');
                    }

                    csrfToken = data.csrf_token;
                    return csrfToken;
                } catch (error) {
                    if (!silent) {
                        showToast(translateAppTextLocal('初始化安全会话失败，请刷新页面后重试'), 'error');
                    }
                    console.error('Failed to initialize CSRF token:', error);
                    throw error;
                } finally {
                    csrfTokenRefreshPromise = null;
                }
            })();

            return csrfTokenRefreshPromise;
        }

        // 包装 fetch 请求，自动添加 CSRF Token
        const originalFetch = window.fetch;
        window.fetch = async function (input, options = {}) {
            const request = buildFetchRequest(input, options);
            const shouldAttachCsrf = isMutationRequest(request.method);

            if (shouldAttachCsrf && !csrfToken) {
                try {
                    await initCSRFToken({ silent: true });
                } catch (error) {
                    // 让原请求继续发出，由后端返回明确的 CSRF 错误提示
                }
            }

            if (shouldAttachCsrf && csrfToken) {
                request.setHeader('X-CSRFToken', csrfToken);
            }

            const response = await request.execute();
            if (!shouldAttachCsrf || options.__skipCsrfRetry || response.status !== 400) {
                return response;
            }

            const payload = await parseJsonSafely(response);
            if (!isCsrfFailurePayload(payload)) {
                return response;
            }

            try {
                await initCSRFToken({ force: true, silent: true });
            } catch (error) {
                return response;
            }

            if (!csrfToken) {
                return response;
            }

            const retryRequest = buildFetchRequest(input, {
                ...options,
                __skipCsrfRetry: true
            });
            retryRequest.setHeader('X-CSRFToken', csrfToken);
            return retryRequest.execute();
        };

        // 初始化
        document.addEventListener('DOMContentLoaded', async function () {
            applyUiStyle(localStorage.getItem('ol_ui_style') || 'classic');

            // 应用保存的主题
            applyTheme(localStorage.getItem('ol_theme') || 'light');

            // 初始化 CSRF Token。失败时不阻断首屏，其它初始化继续执行，
            // 具体的写请求再走按需恢复逻辑。
            try {
                await initCSRFToken();
            } catch (error) {}

            // 初始化布局状态（从后端读取或迁移旧 localStorage）
            await initLayoutState();

            closeAllModals();
            loadGroups();
            if (typeof loadTags === 'function') {
                loadTags();
            }
            initColorPicker();
            initEmailListScroll();
            initResizeHandles();
            handleResponsiveGroups();
            initTempMailSettingsDirtyTracking();

            // 初始化轮询设置
            initPollingSettings();

            // 初始化“一键更新配置”更新方式切换显隐逻辑（避免 index.html 内联脚本）
            initUpdateMethodConfigToggles();

            // 请求浏览器通知权限
            if ('Notification' in window && Notification.permission === 'default') {
                Notification.requestPermission();
            }

            // 绑定搜索框事件
            const searchInput = document.getElementById('globalSearch');
            if (searchInput) {
                const debouncedSearch = debounce((e) => {
                    searchAccounts(e.target.value);
                }, 300);
                searchInput.addEventListener('input', (e) => {
                    if (typeof updateAccountSearchClearButton === 'function') {
                        updateAccountSearchClearButton();
                    }
                    debouncedSearch(e);
                });
                searchInput.addEventListener('keydown', (e) => {
                    if (e.key === 'Escape') {
                        e.preventDefault();
                        if (typeof clearAccountSearch === 'function') {
                            clearAccountSearch();
                        }
                    }
                });
                if (typeof updateAccountSearchClearButton === 'function') {
                    updateAccountSearchClearButton();
                }
            }
            const scopeSelect = document.getElementById('accountSearchScope');
            if (scopeSelect && typeof setAccountSearchScope === 'function') {
                // keep select value in sync with default state
                scopeSelect.value = 'group';
            }

            // 加载数据概览
            if (typeof initOverview === 'function') initOverview();

            // 检查是否有版本更新（延迟 5 秒触发，避免首屏抢占唯一 sync worker）
            setTimeout(checkVersionUpdate, 5000);
        });

        // 初始化颜色选择器
        function initColorPicker() {
            document.querySelectorAll('.color-option').forEach(option => {
                option.addEventListener('click', function () {
                    document.querySelectorAll('.color-option').forEach(o => o.classList.remove('selected'));
                    this.classList.add('selected');
                    selectedColor = this.dataset.color;
                    // 同步更新自定义颜色输入框
                    document.getElementById('customColorInput').value = selectedColor;
                    document.getElementById('customColorHex').value = selectedColor;
                });
            });
        }

        // 初始化邮件列表滚动监听
        function initEmailListScroll() {
            const emailList = document.getElementById('emailList');
            emailList.addEventListener('scroll', function () {
                // 检查是否滚动到底部
                if (emailList.scrollHeight - emailList.scrollTop <= emailList.clientHeight + 50) {
                    if (!isLoadingMore && hasMoreEmails && currentAccount && !isTempEmailGroup) {
                        loadMoreEmails();
                    }
                }
            });
        }

        // 加载更多邮件
        async function loadMoreEmails() {
            if (isLoadingMore || !hasMoreEmails) return;

            isLoadingMore = true;
            currentSkip += 20; // 每页20封

            // 在列表底部显示加载状态
            const emailList = document.getElementById('emailList');
            const loadingDiv = document.createElement('div');
            loadingDiv.className = 'loading-overlay';
            loadingDiv.id = 'loadingMore';
            loadingDiv.innerHTML = `<span class="spinner"></span> ${translateAppTextLocal('加载更多…')}`;
            emailList.appendChild(loadingDiv);

            // 禁用按钮
            const refreshBtn = document.querySelector('.refresh-btn');
            const folderTabs = document.querySelectorAll('.email-tab');
            if (refreshBtn) {
                refreshBtn.disabled = true;
            }
            folderTabs.forEach(tab => tab.disabled = true);

            try {
                const response = await fetch(
                    `/api/emails/${encodeURIComponent(currentAccount)}?method=${currentMethod}&folder=${currentFolder}&skip=${currentSkip}&top=20`
                );
                const data = await response.json();

                if (data.success && data.emails.length > 0) {
                    // 追加新邮件到列表
                    const mergedEmails = currentEmails.concat(data.emails || []);
                    currentEmails = (typeof sortEmailsByNewestFirst === 'function')
                        ? sortEmailsByNewestFirst(mergedEmails)
                        : mergedEmails;
                    hasMoreEmails = data.has_more;

                    // 移除加载状态
                    const loadingEl = document.getElementById('loadingMore');
                    if (loadingEl) loadingEl.remove();

                    renderEmailList(currentEmails, { scrollToTop: false });

                    // 更新邮件数量
                    document.getElementById('emailCount').textContent = `(${currentEmails.length})`;

                    // 更新缓存
                    if (currentAccount && !isTempEmailGroup) {
                        const cacheKey = `${currentAccount}_${currentFolder}`;
                        if (emailListCache[cacheKey]) {
                            emailListCache[cacheKey].emails = currentEmails;
                            emailListCache[cacheKey].has_more = hasMoreEmails;
                            emailListCache[cacheKey].skip = currentSkip;
                        }
                    }
                } else {
                    hasMoreEmails = false;
                    // 显示"没有更多邮件"
                    const loadingEl = document.getElementById('loadingMore');
                    if (loadingEl) {
                        loadingEl.innerHTML = `<div style="text-align:center;padding:20px;color:#999;font-size:13px;">${translateAppTextLocal('没有更多邮件了')}</div>`;
                    }
                }
            } catch (error) {
                const loadingEl = document.getElementById('loadingMore');
                if (loadingEl) loadingEl.remove();
                showToast(translateAppTextLocal('加载失败'), 'error');
            } finally {
                isLoadingMore = false;
                // 启用按钮
                if (refreshBtn) {
                    refreshBtn.disabled = false;
                }
                folderTabs.forEach(tab => tab.disabled = false);
            }
        }

        // 切换文件夹（不触发查询）
        function switchFolder(folder) {
            if (currentFolder === folder) return;

            currentFolder = folder;

            // 更新按钮状态
            document.querySelectorAll('.email-tab').forEach(tab => {
                tab.classList.toggle('active', tab.dataset.folder === folder);
            });

            const cacheKey = `${currentAccount}_${folder}`;

            // 检查是否有缓存
            if (emailListCache[cacheKey]) {
                const cache = emailListCache[cacheKey];
                currentEmails = (typeof sortEmailsByNewestFirst === 'function')
                    ? sortEmailsByNewestFirst(cache.emails || [])
                    : (cache.emails || []);
                hasMoreEmails = cache.has_more;
                currentSkip = cache.skip;
                currentMethod = cache.method || 'graph';

                cache.emails = currentEmails;

                // 恢复 UI
                const methodTag = document.getElementById('methodTag');
                methodTag.textContent = currentMethod;
                methodTag.style.display = 'inline';
                document.getElementById('emailCount').textContent = `(${currentEmails.length})`;

                renderEmailList(currentEmails);
            } else {
                // 清空邮件列表，显示提示
                document.getElementById('emailList').innerHTML = `
                    <div class="empty-state">
                        <span class="empty-icon">📬</span>
                        <p>${translateAppTextLocal(folder === 'inbox' ? '点击"获取邮件"按钮获取收件箱' : '点击"获取邮件"按钮获取垃圾邮件')}</p>
                    </div>
                `;
                document.getElementById('emailCount').textContent = '';
                document.getElementById('methodTag').style.display = 'none';

                // 重置分页状态
                currentEmails = [];
                currentSkip = 0;
                hasMoreEmails = true;
            }
        }

        // 选择自定义颜色（颜色选择器）
        function selectCustomColor(color) {
            selectedColor = color;
            document.getElementById('customColorHex').value = color;
            // 取消预设颜色的选中状态
            document.querySelectorAll('.color-option').forEach(o => o.classList.remove('selected'));
        }

        // 选择自定义颜色（十六进制输入）
        function selectCustomColorHex(value) {
            // 验证十六进制颜色格式
            const hexPattern = /^#[0-9A-Fa-f]{6}$/;
            if (hexPattern.test(value)) {
                selectedColor = value;
                document.getElementById('customColorInput').value = value;
                // 取消预设颜色的选中状态
                document.querySelectorAll('.color-option').forEach(o => o.classList.remove('selected'));
            } else {
                showToast(translateAppTextLocal('请输入有效的十六进制颜色（如 #FF5500）'), 'error');
            }
        }

        // 显示消息提示
        function showToast(message, type = 'info', errorDetail = null, persistent = false) {
            let container = document.getElementById('toast-container');
            if (!container) {
                container = document.createElement('div');
                container.id = 'toast-container';
                container.setAttribute('aria-live', 'polite');
                document.body.appendChild(container);
            }

            const toast = document.createElement('div');
            toast.className = 'toast ' + type;

            const messageSpan = document.createElement('span');
            messageSpan.textContent = translateAppTextLocal(message);
            toast.appendChild(messageSpan);

            if (errorDetail && type === 'error') {
                const detailLink = document.createElement('a');
                detailLink.href = 'javascript:void(0)';
                detailLink.textContent = ' ' + translateAppTextLocal('[详情]');
                detailLink.style.cssText = 'color:var(--clr-danger);text-decoration:underline;margin-left:8px;';
                detailLink.onclick = function (e) {
                    e.stopPropagation();
                    showErrorDetailModal(errorDetail);
                };
                toast.appendChild(detailLink);
            }

            container.appendChild(toast);

            if (persistent) {
                // persistent 模式：追加关闭按钮，不自动消失
                const closeBtn = document.createElement('button');
                closeBtn.textContent = '×';
                closeBtn.style.cssText = 'background:none;border:none;color:inherit;cursor:pointer;margin-left:12px;font-size:1.1rem;opacity:0.8;';
                closeBtn.onclick = () => {
                    toast.style.opacity = '0';
                    setTimeout(() => toast.remove(), 300);
                };
                toast.appendChild(closeBtn);
            } else {
                const duration = (errorDetail && type === 'error') ? 8000 : 3000;
                setTimeout(() => {
                    toast.style.opacity = '0';
                    toast.style.transform = 'translateX(30px)';
                    setTimeout(() => toast.remove(), 300);
                }, duration);
            }
        }

        function buildRefreshErrorSuggestions({ accountType, provider, errorMessage }) {
            const language = getUiLanguage();
            const normalizedAccountType = String(accountType || 'outlook').trim().toLowerCase();
            const normalizedProvider = String(provider || 'outlook').trim().toLowerCase();
            const normalizedErrorMessage = String(errorMessage || '').trim();
            const looksLikeTokenRefreshError = /aadsts|refresh[_\s-]?token|invalid[_\s-]?grant|expired/i.test(normalizedErrorMessage);

            if (normalizedAccountType === 'imap') {
                if (normalizedProvider === 'gmail') {
                    return language === 'en'
                        ? [
                            'Confirm IMAP is enabled and use an app password instead of your normal account password.',
                            'If this looks like an old Outlook token-refresh error, switch the account to IMAP credentials and save again.',
                            'Re-check the IMAP host, port, and SSL settings before retrying.',
                        ]
                        : [
                            '请确认 Gmail 已开启 IMAP，并使用应用专用密码而不是普通登录密码。',
                            '如果这里其实是旧的 Outlook token-refresh error，请把账号切回 IMAP 凭据后重新保存。',
                            '请重新检查 IMAP 主机、端口和 SSL 配置后再重试。',
                        ];
                }

                return language === 'en'
                    ? [
                        'Check the IMAP host, port, SSL/TLS, and account password settings.',
                        'Confirm the mailbox provider allows IMAP login from third-party apps.',
                        'If this error came from a migrated Outlook account, remove the old token-refresh settings and save the IMAP credentials again.',
                    ]
                    : [
                        '请检查 IMAP 主机、端口、SSL/TLS 和账号密码配置是否正确。',
                        '请确认当前邮箱服务商允许第三方客户端通过 IMAP 登录。',
                        '如果这是从旧 Outlook 账号迁移过来的异常，请清理旧的刷新 Token 配置并重新保存 IMAP 凭据。',
                    ];
            }

            if (looksLikeTokenRefreshError) {
                return language === 'en'
                    ? [
                        'Check whether the Client ID and Refresh Token are complete and do not contain extra spaces.',
                        'Use the "Get Refresh Token" flow again to generate a fresh authorization token.',
                        'Confirm the Microsoft account or tenant permissions have not been revoked or expired.',
                    ]
                    : [
                        '请检查 Client ID 和 Refresh Token 是否填写完整且没有多余空格。',
                        '请重新使用“获取 Refresh Token”功能生成新的授权凭据。',
                        '请确认 Microsoft 账号权限未被撤销，且租户策略没有使当前 Token 失效。',
                    ];
            }

            return language === 'en'
                ? [
                    'Open the account editor and verify the saved Outlook authorization information.',
                    'Retry the refresh after confirming network, proxy, and Microsoft service availability.',
                    'If the problem persists, re-authorize the account to obtain a new Refresh Token.',
                ]
                : [
                    '请打开账号编辑弹窗，确认当前保存的 Outlook 授权信息仍然有效。',
                    '请检查网络、代理和 Microsoft 服务状态后再次尝试刷新。',
                    '如果问题持续存在，请重新授权该账号并获取新的 Refresh Token。',
                ];
        }

        // 显示刷新错误信息
        function showRefreshError(accountId, errorMessage, accountEmail, accountType = 'outlook', provider = 'outlook') {
            currentErrorAccountId = accountId;
            currentErrorAccountEmail = accountEmail;

            document.getElementById('refreshErrorModal').classList.add('show');
            document.getElementById('refreshErrorEmail').textContent = translateAppTextLocal(`账号：${accountEmail || '未知'}`);
            document.getElementById('refreshErrorMessage').textContent = translateAppTextLocal(errorMessage);
            const suggestionsEl = document.getElementById('refreshErrorSuggestions');
            const suggestions = buildRefreshErrorSuggestions({ accountType, provider, errorMessage });
            if (suggestionsEl) {
                suggestionsEl.innerHTML = suggestions.map(item => `<li>${escapeHtml(item)}</li>`).join('');
            }
            document.getElementById('editAccountFromErrorBtn').onclick = function () {
                hideRefreshErrorModal();
                showEditAccountModal(accountId);
            };

            const retryBtn = document.getElementById('errorModalRetryBtn');
            if (retryBtn) {
                const isRefreshable = provider === 'outlook' && accountType !== 'imap';
                if (isRefreshable) {
                    retryBtn.style.display = 'inline-block';
                } else {
                    retryBtn.style.display = 'none';
                }
            }
        }

        async function retryRefreshFromModal() {
            if (!currentErrorAccountId) return;
            hideRefreshErrorModal();
            await retrySingleAccount(currentErrorAccountId, currentErrorAccountEmail);
            if (typeof loadAccountsByGroup === 'function' && window.currentGroupId) {
                loadAccountsByGroup(currentGroupId, true);
            }
        }

        // 隐藏刷新错误模态框
        function hideRefreshErrorModal() {
            document.getElementById('refreshErrorModal').classList.remove('show');
            currentErrorAccountId = null;
        }

        // ==================== 统一错误处理相关 ====================

        // 显示统一错误详情模态框
        function showErrorDetailModal(error) {
            const titleEl = document.getElementById('errorDetailModalTitle');
            const standardBody = document.getElementById('errorModalStandardBody');
            const fetchBody = document.getElementById('errorModalFetchBody');
            if (titleEl) titleEl.textContent = translateAppTextLocal('❌ 错误详情');
            if (standardBody) standardBody.style.display = 'block';
            if (fetchBody) fetchBody.style.display = 'none';

            document.getElementById('errorDetailModal').classList.add('show');
            document.getElementById('errorModalUserMessage').textContent = window.resolveApiErrorMessage
                ? window.resolveApiErrorMessage(error, '发生未知错误', 'Unknown error')
                : (error.message || '发生未知错误');
            document.getElementById('errorModalCode').textContent = error.code || '-';
            document.getElementById('errorModalType').textContent = error.type || '-';
            document.getElementById('errorModalStatus').textContent = error.status || '-';
            document.getElementById('errorModalTraceId').textContent = error.trace_id || '-';

            const detailsEl = document.getElementById('errorModalDetails');
            const detailsContainer = document.getElementById('errorModalDetailsContainer');
            const toggleBtn = document.getElementById('toggleTraceBtn');

            const errorDetail = getErrorDetail(error);
            detailsEl.textContent = errorDetail || translateAppTextLocal('暂无详细技术堆栈信息');

            // 重置堆栈显示状态
            detailsContainer.style.display = 'none';
            toggleBtn.textContent = translateAppTextLocal('显示堆栈/细节');
        }

        // 隐藏统一错误详情模态框
        function hideErrorDetailModal() {
            const modal = document.getElementById('errorDetailModal');
            if (modal) modal.classList.remove('show');
        }

        // 邮件获取失败详情弹框（复用统一错误详情模态框）
        function showEmailFetchErrorModal(details) {
            if (!details) return;

            const methodNames = {
                'graph': 'Graph API',
                'imap_new': 'IMAP（新服务器）',
                'imap_old': 'IMAP（旧服务器）'
            };

            function translateError(err) {
                if (!err) return '未知错误';
                // err 可能是 string 或 object
                if (typeof err === 'string') return err;

                const code = err.code || '';
                const detailText = typeof err.details === 'string' ? err.details : JSON.stringify(err.details || '');
                const msg = err.message || '';

                // 翻译常见错误
                if (code === 'GRAPH_TOKEN_EXCEPTION' && detailText.includes('ProxyError')) {
                    return '代理连接失败：无法连接到代理服务器，请检查代理地址是否正确以及代理是否在运行';
                }
                if (code === 'GRAPH_TOKEN_FAILED' || code === 'IMAP_TOKEN_FAILED') {
                    if (detailText.includes('invalid_grant')) {
                        return 'Token 已失效或权限不足：请重新授权登录或更换 refresh_token';
                    }
                    if (detailText.includes('invalid_client')) {
                        return 'Client ID 无效：请检查 client_id 配置是否正确';
                    }
                    return `令牌获取失败：${msg}`;
                }
                if (code === 'EMAIL_FETCH_FAILED') {
                    return `获取邮件失败：${msg}`;
                }
                if (code === 'IMAP_CONNECTION_FAILED') {
                    return 'IMAP 连接失败：无法连接到邮件服务器';
                }
                return msg || detailText || '未知错误';
            }

            let html = '';
            const methods = ['graph', 'imap_new', 'imap_old'];
            methods.forEach(method => {
                const err = details[method];
                if (err !== undefined) {
                    const name = methodNames[method] || method;
                    const reason = translateError(err);
                    const codeText = (err && typeof err === 'object') ? (err.code || '-') : '-';
                    html += `
                        <div style="background: #fff5f5; border: 1px solid #fde2e2; border-radius: 8px; padding: 14px 16px; margin-bottom: 12px;">
                            <div style="font-weight: 600; color: #dc3545; margin-bottom: 6px; font-size: 14px;">${escapeHtml(name)}</div>
                            <div style="color: #333; font-size: 13px; line-height: 1.6;">${escapeHtml(reason)}</div>
                            <div style="color: #999; font-size: 12px; margin-top: 4px;">错误代码: ${escapeHtml(codeText)}</div>
                        </div>
                    `;
                }
            });

            if (!html) {
                html = '<div style="color:#666;">无详细错误信息</div>';
            }

            const titleEl = document.getElementById('errorDetailModalTitle');
            const standardBody = document.getElementById('errorModalStandardBody');
            const fetchBody = document.getElementById('errorModalFetchBody');
            if (titleEl) titleEl.textContent = translateAppTextLocal('❌ 获取邮件失败');
            if (standardBody) standardBody.style.display = 'none';
            if (fetchBody) fetchBody.style.display = 'block';
            document.getElementById('emailFetchErrorContent').innerHTML = html;
            document.getElementById('errorDetailModal').classList.add('show');
        }

        function hideEmailFetchErrorModal() {
            hideErrorDetailModal();
        }

        // 切换堆栈信息的显示/隐藏
        function toggleStackTrace() {
            const container = document.getElementById('errorModalDetailsContainer');
            const btn = document.getElementById('toggleTraceBtn');

            if (container.style.display === 'none') {
                container.style.display = 'block';
                btn.textContent = translateAppTextLocal('隐藏堆栈/细节');
            } else {
                container.style.display = 'none';
                btn.textContent = translateAppTextLocal('显示堆栈/细节');
            }
        }

        // 复制错误详情到剪贴板
        function copyErrorDetails() {
            const userMessage = document.getElementById('errorModalUserMessage').textContent;
            const details = document.getElementById('errorModalDetails').textContent;
            const code = document.getElementById('errorModalCode').textContent;
            const type = document.getElementById('errorModalType').textContent;
            const status = document.getElementById('errorModalStatus').textContent;
            const traceId = document.getElementById('errorModalTraceId').textContent;
            const userMessageHeader = translateAppTextLocal('【用户错误信息】');
            const detailHeader = translateAppTextLocal('【错误详情】');
            const technicalHeader = translateAppTextLocal('【技术堆栈/细节】');

            const fullErrorText = `
${userMessageHeader}
${userMessage}

${detailHeader}
Code: ${code}
Type: ${type}
Status: ${status}
Trace ID: ${traceId}

${technicalHeader}
${details}
            `.trim();

            navigator.clipboard.writeText(fullErrorText).then(() => {
                showToast(translateAppTextLocal('错误详情已复制'), 'success');
            }).catch(() => {
                // 降级方案
                const textarea = document.createElement('textarea');
                textarea.value = fullErrorText;
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                document.body.removeChild(textarea);
                showToast(translateAppTextLocal('错误详情已复制'), 'success');
            });
        }

        // 统一处理 API 响应错误
        function handleApiError(data, defaultMessage = '请求失败') {
            if (!data.success) {
                const error = data.error || data;
                const userMessage = window.resolveApiErrorMessage
                    ? window.resolveApiErrorMessage(error, defaultMessage, 'Request failed')
                    : (typeof error === 'string' ? translateAppTextLocal(error) : translateAppTextLocal(defaultMessage));
                const guidance = getCfWorkerErrorGuidance(error);
                showToast(guidance ? `${userMessage} ${guidance}` : userMessage, 'error', error && typeof error === 'object' ? error : null);
                return true;
            }
            return false;
        }

        function getErrorDetail(error) {
            const rawDetail = error && (error.error_detail || error.details) || '';
            if (typeof rawDetail !== 'string') return '';
            try {
                const parsed = JSON.parse(rawDetail);
                return typeof parsed.error_detail === 'string' ? parsed.error_detail : rawDetail;
            } catch (_) {
                return rawDetail;
            }
        }

        function getCfWorkerErrorGuidance(error) {
            if (!error || typeof error !== 'object') return '';
            const guides = {
                UNAUTHORIZED: '请检查 CF Worker 的 ADMIN_PASSWORDS 是否与这里保存的 Admin 密码一致。',
                UPSTREAM_BAD_PAYLOAD: '请同步 CF Worker 域名、确认默认域名存在，并检查 Worker API 版本。',
                UPSTREAM_RATE_LIMITED: '请求过于频繁，请稍后重试。',
                UPSTREAM_SERVER_ERROR: '请检查 CF Worker 的部署状态和运行日志。',
                UPSTREAM_TIMEOUT: '请检查网络连通性和 CF Worker 响应时间。',
            };
            return guides[String(error.code || '').trim()] || '';
        }

        function escapeJs(str) {
            if (!str) return '';
            return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"').replace(/\n/g, '\\n').replace(/\r/g, '\\r');
        }

        // ==================== 工具函数 ====================

        // HTML 转义
        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // 格式化日期
        function formatDate(dateStr) {
            return formatUiDateTime(dateStr, { fallback: dateStr || '' });
        }


        // ==================== 工具函数 ====================

        // 相对时间格式化
        function formatRelativeTime(timestamp) {
            return formatUiRelativeTime(timestamp, '从未刷新', 'Never refreshed');
        }


        function getCSRFToken() {
            const meta = document.querySelector('meta[name="csrf-token"]');
            return meta ? meta.getAttribute('content') : '';
        }

        // 统一失效账号缓存（同步清理全局搜索缓存 '__all__' 与涉及的分组）
        function invalidateAccountsCache(...groupIds) {
            if (typeof accountsCache === 'undefined' || !accountsCache) return;
            delete accountsCache['__all__'];
            if (typeof getAccountListCacheKey === 'function') {
                delete accountsCache[getAccountListCacheKey(currentGroupId)];
            }
            if (currentGroupId !== null && currentGroupId !== undefined) {
                delete accountsCache[currentGroupId];
            }
            groupIds.forEach(gid => {
                if (gid !== null && gid !== undefined && gid !== '') {
                    delete accountsCache[gid];
                    delete accountsCache[String(gid)];
                }
            });
        }

        // 统一关闭所有模态框的函数（覆盖全站全部活跃弹窗）
        function closeAllModals() {
            if (typeof hideAddGroupModal === 'function') hideAddGroupModal();
            if (typeof hideAddAccountModal === 'function') hideAddAccountModal();
            if (typeof hideEditAccountModal === 'function') hideEditAccountModal();
            if (typeof hideExportModal === 'function') hideExportModal();
            if (typeof hideExportVerifyModal === 'function') hideExportVerifyModal();
            if (typeof hideSettingsModal === 'function') hideSettingsModal();
            if (typeof hideRefreshModal === 'function') hideRefreshModal();
            if (typeof hideRefreshErrorModal === 'function') hideRefreshErrorModal();
            if (typeof hideErrorDetailModal === 'function') hideErrorDetailModal();
            if (typeof hideEmailFetchErrorModal === 'function') hideEmailFetchErrorModal();
            if (typeof hideTagManagementModal === 'function') hideTagManagementModal();
            if (typeof hideBatchTagModal === 'function') hideBatchTagModal();
            if (typeof hideBatchMoveGroupModal === 'function') hideBatchMoveGroupModal();
            if (typeof hideEmailAliasesModal === 'function') hideEmailAliasesModal();
            if (window.PluginManager && typeof window.PluginManager.closeCustomInstallModal === 'function') {
                window.PluginManager.closeCustomInstallModal();
            }
            if (typeof closeFullscreenEmail === 'function') closeFullscreenEmail();
        }

        // 键盘快捷键
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                closeAllModals();
            }
        });

        const accountPasswordCache = {};

        async function fetchAccountPassword(accountId) {
            if (accountPasswordCache[accountId]) {
                return { ok: true, password: accountPasswordCache[accountId] };
            }
            try {
                const response = await fetch(`/api/accounts/${accountId}/reveal-password`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await response.json();
                if (data.success) {
                    accountPasswordCache[accountId] = data.password;
                    return { ok: true, password: data.password };
                }
                return { ok: false, message: data.error?.message || translateAppTextLocal('无法获取密码') };
            } catch (error) {
                return { ok: false, message: translateAppTextLocal('网络错误') };
            }
        }

        async function revealPassword(accountId) {
            const row = document.getElementById(`password-row-${accountId}`);
            if (!row) return;

            const maskEl = row.querySelector('.pw-mask');
            if (maskEl.textContent !== '••••••••') {
                maskEl.textContent = '••••••••';
                return;
            }

            maskEl.textContent = '...';
            const res = await fetchAccountPassword(accountId);
            if (res.ok) {
                maskEl.textContent = res.password;
            } else {
                maskEl.textContent = '••••••••';
                showToast(res.message, 'error');
            }
        }

        async function copyPassword(accountId) {
            const res = await fetchAccountPassword(accountId);
            if (!res.ok) {
                showToast(res.message, 'error');
                return;
            }
            await copyToClipboard(res.password, '密码');
        }

        async function copyAccountAndPassword(accountId, email) {
            const res = await fetchAccountPassword(accountId);
            if (!res.ok) {
                showToast(res.message, 'error');
                return;
            }
            const combined = `${email}----${res.password}`;
            await copyToClipboard(combined, '账密');
        }

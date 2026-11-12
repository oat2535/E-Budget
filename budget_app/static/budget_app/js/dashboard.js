/* ==========================================================================
   E-Budget Single-Branch Dashboard Frontend Controller
   ========================================================================== */
(function () {
    'use strict';

    const MONTH_KEYS = [
        'january', 'february', 'march', 'april', 'may', 'june',
        'july', 'august', 'september', 'october', 'november', 'december'
    ];
    const PCT_KEYS = [
        'pct_jan', 'pct_feb', 'pct_mar', 'pct_apr', 'pct_may', 'pct_jun',
        'pct_jul', 'pct_aug', 'pct_sep', 'pct_oct', 'pct_nov', 'pct_dec'
    ];

    const state = {
        rows: [],
        payload: null,
        hasLoaded: false,
        isFullscreen: false,
        columnPreset: 'full',
        rowFilter: 'all',
        searchTerm: '',
        branchSelectInstance: null,
    };

    const el = {};

    function cacheElements() {
        el.configEl = document.getElementById('dashboard-config');
        el.branchSelect = document.getElementById('dashboard-branch-select');
        el.branchLockedInput = document.getElementById('dashboard-branch-locked');
        el.yearSelect = document.getElementById('dashboard-year-select');
        el.btnRefresh = document.getElementById('btn-dashboard-refresh');
        el.btnExport = document.getElementById('btn-dashboard-export');
        el.btnFullscreen = document.getElementById('btn-dashboard-fullscreen');
        el.fsBranchLabel = document.getElementById('dashboard-fs-branch-label');
        el.matrixCard = document.getElementById('dashboard-matrix-card');
        el.searchInput = document.getElementById('dashboard-search-input');
        el.rowFilterSelect = document.getElementById('dashboard-row-filter');
        el.presetButtons = document.querySelectorAll('[data-col-preset]');
        el.topScroll = document.getElementById('dashboard-top-scroll');
        el.topScrollSpacer = document.getElementById('dashboard-top-scroll-spacer');
        el.tableWrapper = document.getElementById('dashboard-table-scroll');
        el.thead = document.getElementById('dashboard-table-head');
        el.tbody = document.getElementById('dashboard-table-body');
        el.loadingOverlay = document.getElementById('dashboard-loading');
        el.errorBanner = document.getElementById('dashboard-error-banner');
        el.metaStrip = document.getElementById('dashboard-meta-strip');
        el.rowCountBadge = document.getElementById('dashboard-row-count');
    }

    function readConfig() {
        if (!el.configEl) return {};
        try {
            return JSON.parse(el.configEl.textContent || '{}');
        } catch (e) {
            return {};
        }
    }

    function formatNum2(val) {
        const num = Number(val || 0);
        const rounded = Math.round((num + Number.EPSILON) * 100) / 100;
        const safeVal = Math.abs(rounded) < 0.005 ? 0 : rounded;
        return safeVal.toLocaleString('en-US', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function getSelectedBranch() {
        if (el.branchLockedInput) {
            return (el.branchLockedInput.value || '').trim();
        }
        if (state.branchSelectInstance) {
            return (state.branchSelectInstance.getValue() || '').trim();
        }
        if (el.branchSelect) {
            return (el.branchSelect.value || '').trim();
        }
        return '';
    }

    function getSelectedYear() {
        return el.yearSelect ? (el.yearSelect.value || '').trim() : '';
    }

    function setLoading(isLoading) {
        const selectedBranch = getSelectedBranch();
        if (el.loadingOverlay) {
            el.loadingOverlay.classList.toggle('d-none', !isLoading);
        }
        if (el.btnRefresh) el.btnRefresh.disabled = isLoading || !selectedBranch;
        if (el.btnExport) el.btnExport.disabled = isLoading || !selectedBranch || !state.hasLoaded;
    }

    function showError(message) {
        if (!el.errorBanner) return;
        if (!message) {
            el.errorBanner.classList.add('d-none');
            el.errorBanner.textContent = '';
            return;
        }
        el.errorBanner.textContent = message;
        el.errorBanner.classList.remove('d-none');
    }

    function initBranchDropdown(config) {
        if (!el.branchSelect) return;
        const previousVal = config.selected_branch || '';
        if (typeof window.TomSelect === 'undefined') {
            el.branchSelect.addEventListener('change', function () {
                if (getSelectedBranch()) loadDashboardData();
            });
            return;
        }
        state.branchSelectInstance = new window.TomSelect(el.branchSelect, {
            allowEmptyOption: false,
            create: false,
            maxItems: 1,
            // Preserve server ordering so 'ALL' remains Option #1 above TLPH branch codes
            sortField: [{ field: '$score' }, { field: '$order' }],
            placeholder: '-- กรุณาเลือกสาขา --',
            onChange: function (value) {
                if (!value) {
                    const fallback = this._lastValidBranch || previousVal;
                    if (fallback) this.setValue(fallback, true);
                    return;
                }
                this._lastValidBranch = value;
                loadDashboardData();
            },
        });
        state.branchSelectInstance._lastValidBranch = previousVal;
    }

    function renderTableHeader() {
        if (!el.thead) return;
        const monthShort = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        const pctLabels = ['pct_jan', 'pct_feb', 'pct_mar', 'pct_apr', 'pct_may', 'pct_jun', 'pct_jul', 'pct_aug', 'pct_sep', 'pct_oct', 'pct_nov', 'pct_dec'];

        let groupRow = '<tr class="hdr-group">';
        groupRow += '<th colspan="3" class="grp-identity sticky-col-span-3">โครงสร้าง P&amp;L (GL Template)</th>';
        groupRow += '<th colspan="5" class="grp-actual">GL Actual Baseline</th>';
        groupRow += '<th colspan="13" class="grp-budget col-monthly">Budget รายเดือน (บาท)</th>';
        groupRow += '<th colspan="12" class="grp-pct col-pct">สัดส่วน % ในหมวดย่อย (Query)</th>';
        groupRow += '<th colspan="2" class="grp-compare col-compare-only">สรุปเทียบ Actual (12M)</th>';
        groupRow += '</tr>';

        let colRow = '<tr class="hdr-cols">';
        colRow += '<th class="sticky-col-1">ลำดับ</th>';
        colRow += '<th class="sticky-col-2">GL Code</th>';
        colRow += '<th class="sticky-col-3">รายการ</th>';
        colRow += '<th>Act จริง</th>';
        colRow += '<th>ต่อเดือน</th>';
        colRow += '<th>12</th>';
        colRow += '<th>สัดส่วน/ยอดขาย</th>';
        colRow += '<th>% การโต</th>';

        monthShort.forEach(function (m) {
            colRow += '<th class="col-monthly">' + m + '</th>';
        });
        colRow += '<th class="col-monthly">Total</th>';

        pctLabels.forEach(function (p) {
            colRow += '<th class="col-pct">' + p + '</th>';
        });

        colRow += '<th class="col-compare-only">Budget Total</th>';
        colRow += '<th class="col-compare-only">Diff (Budget - x12)</th>';
        colRow += '</tr>';

        el.thead.innerHTML = groupRow + colRow;
        syncTopScrollBar();
    }

    function numCellHtml(value, extraClass) {
        const num = Number(value || 0);
        const classes = ['num-cell'];
        if (extraClass) classes.push(extraClass);
        if (Math.abs(num) < 0.005) {
            classes.push('val-zero');
        } else if (num < 0) {
            classes.push('val-negative');
        }
        return '<td class="' + classes.join(' ') + '">' + formatNum2(num) + '</td>';
    }

    function pctCellHtml(value) {
        const num = Number(value || 0);
        const classes = ['pct-cell', 'col-pct'];
        if (Math.abs(num) < 0.005) {
            classes.push('val-zero');
        } else if (num < 0) {
            classes.push('val-negative');
        }
        return '<td class="' + classes.join(' ') + '">' + formatNum2(num) + '%</td>';
    }

    function rowCssClass(row) {
        if (row.general_ledger_code === 'FH8') return 'row-net-profit';
        if (row.is_pnl_summary) return 'row-pnl-major';
        if (row.row_type === 'subtotal') return 'row-subtotal';
        if (row.row_type === 'header') return 'row-header';
        return 'row-gl';
    }

    function getFilteredRows() {
        const term = (state.searchTerm || '').trim().toLowerCase();
        return (state.rows || []).filter(function (r) {
            if (state.rowFilter === 'nonzero' && r.row_type === 'gl' && !r.has_nonzero) {
                return false;
            }
            if (state.rowFilter === 'summary' && r.row_type === 'gl' && !r.is_pnl_summary) {
                return false;
            }
            if (term) {
                const hay = (r.general_ledger_code + ' ' + r.gl_name).toLowerCase();
                if (hay.indexOf(term) === -1) return false;
            }
            return true;
        });
    }

    function renderIdleState() {
        state.hasLoaded = false;
        state.rows = [];
        state.payload = null;

        const lockedBranch = el.branchLockedInput ? getSelectedBranch() : '';
        if (el.rowCountBadge) {
            el.rowCountBadge.textContent = lockedBranch ? 'ยังไม่โหลดข้อมูล' : 'รอเลือกสาขา';
        }
        if (el.fsBranchLabel) {
            el.fsBranchLabel.textContent = '';
            el.fsBranchLabel.classList.add('d-none');
        }
        if (el.metaStrip) {
            if (lockedBranch) {
                el.metaStrip.innerHTML = '<span class="badge bg-light text-dark border">กดปุ่ม &quot;แสดงข้อมูลตาราง&quot; เพื่อโหลดข้อมูลสาขา</span>';
            } else if (!el.branchSelect) {
                el.metaStrip.innerHTML = '<span class="badge bg-warning text-dark">ไม่พบสาขา TLPH ที่มีสิทธิ์เข้าดูข้อมูล</span>';
            } else {
                el.metaStrip.innerHTML = '<span class="badge bg-light text-dark border">กรุณาเลือกสาขาเพื่อโหลดข้อมูล GL Actual และงบประมาณ</span>';
            }
        }
        if (el.tbody) {
            let bannerHtml = '';
            if (lockedBranch) {
                const branchLabel = (el.branchLockedInput.getAttribute('data-branch-label') || lockedBranch);
                bannerHtml = '<div class="dashboard-idle-banner">' +
                    '<div class="fw-semibold text-primary mb-1"><i class="fas fa-hospital-alt me-1"></i>พร้อมแสดงข้อมูลสาขา ' + escapeHtml(branchLabel) + '</div>' +
                    '<div class="small text-muted mb-2">ยังไม่ได้โหลดข้อมูลเพื่อประหยัดเวลาเมื่อเปิดหน้า Dashboard กดปุ่มด้านล่างเพื่อแสดงข้อมูลในตาราง</div>' +
                    '<button type="button" class="btn btn-primary btn-sm fw-semibold" data-action="load-single-branch"><i class="fas fa-table me-1"></i>แสดงข้อมูลตาราง</button>' +
                    '</div>';
            } else if (!el.branchSelect) {
                bannerHtml = '<div class="dashboard-idle-banner text-muted">ไม่พบสาขา TLPH ที่มีสิทธิ์เข้าดูข้อมูล Dashboard</div>';
            } else {
                bannerHtml = '<div class="dashboard-idle-banner">' +
                    '<div class="fw-semibold text-primary mb-1"><i class="fas fa-code-branch me-1"></i>ยังไม่ได้เลือกสาขา</div>' +
                    '<div class="small text-muted">กรุณาเลือกสาขา (TLPH) จากตัวเลือกด้านบนเพื่อโหลดและแสดงข้อมูลในตาราง</div>' +
                    '</div>';
            }
            el.tbody.innerHTML = '<tr><td colspan="35" class="dashboard-idle-cell">' + bannerHtml + '</td></tr>';
        }
        setLoading(false);
        syncTopScrollBar();
    }

    function renderTableBody() {
        if (!el.tbody) return;
        if (!state.hasLoaded) {
            renderIdleState();
            return;
        }
        const rows = getFilteredRows();
        if (el.rowCountBadge) {
            el.rowCountBadge.textContent = 'แสดง ' + rows.length + ' / ' + (state.rows || []).length + ' บรรทัด';
        }

        if (!rows.length) {
            el.tbody.innerHTML = '<tr><td colspan="35" class="text-center py-4 text-muted">ไม่พบรายการที่ตรงกับเงื่อนไขการค้นหา</td></tr>';
            syncTopScrollBar();
            return;
        }

        const htmlParts = [];
        for (let i = 0; i < rows.length; i++) {
            const r = rows[i];
            let tr = '<tr class="' + rowCssClass(r) + '">';
            tr += '<td class="sticky-col-1">' + escapeHtml(r.row_order) + '</td>';
            tr += '<td class="sticky-col-2"><code>' + escapeHtml(r.general_ledger_code) + '</code></td>';
            tr += '<td class="sticky-col-3" title="' + escapeHtml(r.gl_name) + '">' + escapeHtml(r.gl_name) + '</td>';

            tr += numCellHtml(r.actual_value);
            tr += numCellHtml(r.per_month_value);
            tr += numCellHtml(r.annualized_value);
            tr += numCellHtml(r.sales_ratio);
            tr += numCellHtml(r.growth_rate);

            for (let m = 0; m < MONTH_KEYS.length; m++) {
                tr += numCellHtml(r[MONTH_KEYS[m]], 'col-monthly');
            }
            tr += numCellHtml(r.total, 'col-monthly fw-bold');

            for (let p = 0; p < PCT_KEYS.length; p++) {
                tr += pctCellHtml(r[PCT_KEYS[p]]);
            }

            tr += numCellHtml(r.total, 'col-compare-only fw-bold');
            tr += numCellHtml(r.diff_vs_actual, 'col-compare-only');
            tr += '</tr>';
            htmlParts.push(tr);
        }
        el.tbody.innerHTML = htmlParts.join('');
        syncTopScrollBar();
    }

    function renderMetaStrip(payload) {
        const branch = (payload && payload.branch) || {};
        const doc = payload && payload.gl_actual_document;
        const year = (payload && payload.budget_year) || getSelectedYear();

        const branchLabel = branch.is_all
            ? (branch.name || 'ทุกสาขา (TLPH ทั้งหมด)')
            : ((branch.code || '') + ' — ' + (branch.name || ''));

        if (el.fsBranchLabel) {
            el.fsBranchLabel.textContent = branchLabel + ' (ปี ' + year + ')';
            el.fsBranchLabel.classList.toggle('d-none', !state.isFullscreen);
        }

        if (!el.metaStrip) return;
        const branchText = '<span class="badge bg-primary me-2">สาขา: ' +
            escapeHtml(branchLabel) + '</span>' +
            '<span class="badge bg-secondary me-2">ปีงบประมาณ: ' + escapeHtml(year) + '</span>';

        if (!doc) {
            el.metaStrip.innerHTML = branchText +
                '<span class="badge bg-warning text-dark">GL Actual Template: ยังไม่พบข้อมูลปี ' + escapeHtml(year) + '</span>';
            return;
        }

        el.metaStrip.innerHTML = branchText +
            '<span class="badge bg-info text-dark me-2">GL Actual: ' + escapeHtml(doc.document_no) + '</span>' +
            '<span class="badge bg-light text-dark border me-2">Actual: ' + escapeHtml(doc.actual_month_count) + ' เดือน</span>' +
            '<span class="badge bg-light text-dark border">%โต 1/2/3: ' +
            formatNum2(doc.growth_pct_1) + '% / ' + formatNum2(doc.growth_pct_2) + '% / ' + formatNum2(doc.growth_pct_3) + '%</span>';
    }

    async function loadDashboardData() {
        const config = readConfig();
        const branch = getSelectedBranch();
        const year = getSelectedYear();
        if (!branch || !config.data_api_url) {
            setLoading(false);
            showError('ไม่พบสาขาที่มีสิทธิ์เข้าดูข้อมูล Dashboard');
            return;
        }

        showError('');
        setLoading(true);
        try {
            const url = new URL(config.data_api_url, window.location.origin);
            url.searchParams.set('branch', branch);
            if (year) url.searchParams.set('year', year);

            const resp = await fetch(url.toString(), {
                method: 'GET',
                credentials: 'same-origin',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json',
                },
            });
            const data = await window.handleFetchApiResponse(resp);
            state.hasLoaded = true;
            state.payload = data;
            state.rows = data.rows || [];
            renderMetaStrip(data);
            renderTableBody();
        } catch (err) {
            if (err && err.message !== 'SESSION_EXPIRED') {
                showError((err && err.message) || 'ไม่สามารถโหลดข้อมูล Dashboard ได้');
                if (typeof window.handleFetchApiError === 'function') {
                    window.handleFetchApiError(err, 'เกิดข้อผิดพลาดในการโหลดข้อมูล Dashboard');
                }
            }
        } finally {
            setLoading(false);
        }
    }

    async function exportDashboardExcel() {
        const config = readConfig();
        const branch = getSelectedBranch();
        const year = getSelectedYear();
        if (!branch || !config.export_api_url) return;

        const origHtml = el.btnExport ? el.btnExport.innerHTML : '';
        if (el.btnExport) {
            el.btnExport.disabled = true;
            el.btnExport.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>กำลังสร้าง Excel...';
        }

        try {
            const url = new URL(config.export_api_url, window.location.origin);
            url.searchParams.set('branch', branch);
            if (year) url.searchParams.set('year', year);

            const resp = await fetch(url.toString(), {
                method: 'GET',
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });

            if (resp.status === 401 || resp.redirected) {
                await window.handleFetchApiResponse(resp);
                return;
            }
            if (!resp.ok) {
                let errMsg = 'ไม่สามารถ Export Excel ได้';
                try {
                    const errJson = await resp.json();
                    errMsg = errJson.message || errMsg;
                } catch (_) { /* ignore non-json error body */ }
                throw new Error(errMsg);
            }

            const blob = await resp.blob();
            let filename = 'Dashboard_' + branch + '_' + year + '.xlsx';
            const disposition = resp.headers.get('Content-Disposition') || '';
            const match = /filename="?([^";]+)"?/i.exec(disposition);
            if (match && match[1]) filename = match[1];

            const blobUrl = URL.createObjectURL(blob);
            const anchor = document.createElement('a');
            anchor.href = blobUrl;
            anchor.download = filename;
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
            setTimeout(function () { URL.revokeObjectURL(blobUrl); }, 2000);
        } catch (err) {
            if (err && err.message !== 'SESSION_EXPIRED' && typeof window.handleFetchApiError === 'function') {
                window.handleFetchApiError(err, 'เกิดข้อผิดพลาดในการ Export Excel');
            }
        } finally {
            if (el.btnExport) {
                el.btnExport.disabled = false;
                el.btnExport.innerHTML = origHtml;
            }
        }
    }

    function syncTopScrollBar() {
        if (!el.topScroll || !el.topScrollSpacer || !el.tableWrapper) return;
        const table = el.tableWrapper.querySelector('table');
        const contentWidth = table ? table.scrollWidth : el.tableWrapper.scrollWidth;
        const viewportWidth = el.tableWrapper.clientWidth;
        const needsHorizontalScroll = contentWidth > viewportWidth + 1;

        el.topScroll.classList.toggle('d-none', !needsHorizontalScroll);
        if (!needsHorizontalScroll) {
            el.topScrollSpacer.style.width = '0px';
            return;
        }

        // Offset by vertical scrollbar width inside #dashboard-table-scroll so top & bottom max scrollLeft align 1:1
        const extraWidth = Math.max(0, el.topScroll.clientWidth - viewportWidth);
        el.topScrollSpacer.style.width = (contentWidth + extraWidth) + 'px';
        el.topScroll.scrollLeft = el.tableWrapper.scrollLeft;
    }

    function bindHorizontalScrollSync() {
        if (!el.topScroll || !el.tableWrapper) return;
        let skipTop = false;
        let skipBottom = false;

        function linkPane(source, target, shouldSkip, setOtherSkip) {
            source.addEventListener('scroll', function () {
                if (shouldSkip()) return;
                const nextLeft = source.scrollLeft;
                if (Math.abs(target.scrollLeft - nextLeft) < 1) return;
                setOtherSkip(true);
                target.scrollLeft = nextLeft;
                window.requestAnimationFrame(function () {
                    setOtherSkip(false);
                });
            });
        }

        linkPane(el.topScroll, el.tableWrapper, function () { return skipTop; }, function (v) { skipBottom = v; });
        linkPane(el.tableWrapper, el.topScroll, function () { return skipBottom; }, function (v) { skipTop = v; });

        window.addEventListener('resize', syncTopScrollBar);
        if (typeof window.ResizeObserver === 'function') {
            const ro = new window.ResizeObserver(syncTopScrollBar);
            const tableEl = el.tableWrapper.querySelector('table');
            if (tableEl) ro.observe(tableEl);
            ro.observe(el.tableWrapper);
        }
    }

    function setColumnPreset(preset) {
        state.columnPreset = preset;
        if (el.tableWrapper) {
            el.tableWrapper.classList.remove('preset-full', 'preset-no-pct', 'preset-compare');
            el.tableWrapper.classList.add('preset-' + preset);
        }
        el.presetButtons.forEach(function (btn) {
            const active = btn.getAttribute('data-col-preset') === preset;
            btn.classList.toggle('btn-primary', active);
            btn.classList.toggle('btn-outline-secondary', !active);
        });
        syncTopScrollBar();
    }

    function setFullscreen(enabled) {
        state.isFullscreen = Boolean(enabled);
        if (el.matrixCard) {
            el.matrixCard.classList.toggle('is-fullscreen', state.isFullscreen);
        }
        if (document.body && document.body.classList) {
            document.body.classList.toggle('dashboard-fullscreen-open', state.isFullscreen);
        }
        if (el.btnFullscreen) {
            el.btnFullscreen.classList.toggle('btn-primary', state.isFullscreen);
            el.btnFullscreen.classList.toggle('btn-outline-primary', !state.isFullscreen);
            el.btnFullscreen.setAttribute('aria-pressed', state.isFullscreen ? 'true' : 'false');
            el.btnFullscreen.setAttribute('title', state.isFullscreen ? 'ย่อหน้าจอกลับปกติ (Esc)' : 'เปิดดูตารางแบบเต็มหน้าจอ');
            const enterEl = el.btnFullscreen.querySelector('[data-fs-label="enter"]');
            const exitEl = el.btnFullscreen.querySelector('[data-fs-label="exit"]');
            if (enterEl) enterEl.classList.toggle('d-none', state.isFullscreen);
            if (exitEl) exitEl.classList.toggle('d-none', !state.isFullscreen);
        }
        if (el.fsBranchLabel) {
            el.fsBranchLabel.classList.toggle('d-none', !state.isFullscreen || !state.hasLoaded);
        }
        syncTopScrollBar();
        if (typeof window.requestAnimationFrame === 'function') {
            window.requestAnimationFrame(syncTopScrollBar);
        }
    }

    function bindEvents() {
        bindHorizontalScrollSync();
        if (el.yearSelect) {
            el.yearSelect.addEventListener('change', function () {
                const branch = getSelectedBranch();
                if (!branch) return;
                if (!state.hasLoaded && el.branchLockedInput) return;
                loadDashboardData();
            });
        }
        if (el.btnRefresh) {
            el.btnRefresh.addEventListener('click', function () {
                if (getSelectedBranch()) {
                    loadDashboardData();
                }
            });
        }
        if (el.btnExport) {
            el.btnExport.addEventListener('click', exportDashboardExcel);
        }
        if (el.btnFullscreen) {
            el.btnFullscreen.addEventListener('click', function () {
                setFullscreen(!state.isFullscreen);
            });
        }
        if (el.tbody) {
            el.tbody.addEventListener('click', function (evt) {
                const trigger = evt.target && evt.target.closest ? evt.target.closest('[data-action="load-single-branch"]') : null;
                if (trigger && getSelectedBranch()) {
                    loadDashboardData();
                }
            });
        }
        document.addEventListener('keydown', function (evt) {
            if (evt.key === 'Escape' && state.isFullscreen) {
                setFullscreen(false);
            }
        });
        if (el.rowFilterSelect) {
            el.rowFilterSelect.addEventListener('change', function () {
                state.rowFilter = el.rowFilterSelect.value || 'all';
                renderTableBody();
            });
        }
        if (el.searchInput) {
            el.searchInput.addEventListener('input', function () {
                state.searchTerm = el.searchInput.value || '';
                renderTableBody();
            });
        }
        el.presetButtons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                setColumnPreset(btn.getAttribute('data-col-preset') || 'full');
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        cacheElements();
        const config = readConfig();
        initBranchDropdown(config);
        renderTableHeader();
        setColumnPreset('full');
        bindEvents();
        if (config.selected_branch && String(config.selected_branch).trim()) {
            loadDashboardData();
        } else {
            renderIdleState();
        }
    });
})();

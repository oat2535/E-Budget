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
        el.searchInput = document.getElementById('dashboard-search-input');
        el.rowFilterSelect = document.getElementById('dashboard-row-filter');
        el.presetButtons = document.querySelectorAll('[data-col-preset]');
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
        if (el.loadingOverlay) {
            el.loadingOverlay.classList.toggle('d-none', !isLoading);
        }
        if (el.btnRefresh) el.btnRefresh.disabled = isLoading;
        if (el.btnExport) el.btnExport.disabled = isLoading || !getSelectedBranch();
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
        if (!el.branchSelect || typeof window.TomSelect === 'undefined') return;
        const previousVal = config.selected_branch || '';
        state.branchSelectInstance = new window.TomSelect(el.branchSelect, {
            allowEmptyOption: false,
            create: false,
            maxItems: 1,
            sortField: { field: 'text', direction: 'asc' },
            placeholder: 'เลือกสาขา (1 สาขา)...',
            onChange: function (value) {
                // Strictly prevent clearing to blank ("all branches" is forbidden)
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

    function renderTableBody() {
        if (!el.tbody) return;
        const rows = getFilteredRows();
        if (el.rowCountBadge) {
            el.rowCountBadge.textContent = 'แสดง ' + rows.length + ' / ' + (state.rows || []).length + ' บรรทัด';
        }

        if (!rows.length) {
            el.tbody.innerHTML = '<tr><td colspan="35" class="text-center py-4 text-muted">ไม่พบรายการที่ตรงกับเงื่อนไขการค้นหา</td></tr>';
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
    }

    function setKpiText(id, val, suffix) {
        const node = document.getElementById(id);
        if (!node) return;
        const num = Number(val || 0);
        node.textContent = formatNum2(num) + (suffix || '');
        node.classList.toggle('text-danger', num < 0);
    }

    function renderKpis(payload) {
        const kpis = (payload && payload.kpis) || {};
        const rev = kpis.revenue || {};
        const exp = kpis.expense || {};
        const ebitda = kpis.ebitda || {};
        const net = kpis.net_profit || {};

        setKpiText('kpi-rev-budget', rev.budget_total, '');
        setKpiText('kpi-rev-actual', rev.actual_annualized, '');
        setKpiText('kpi-rev-pct', rev.change_pct, '%');

        setKpiText('kpi-exp-budget', exp.budget_total, '');
        setKpiText('kpi-exp-actual', exp.actual_annualized, '');
        setKpiText('kpi-exp-pct', exp.pct_of_sales, '%');

        setKpiText('kpi-ebitda-budget', ebitda.budget_total, '');
        setKpiText('kpi-ebitda-actual', ebitda.actual_annualized, '');
        setKpiText('kpi-ebitda-pct', ebitda.margin_pct, '%');

        setKpiText('kpi-net-budget', net.budget_total, '');
        setKpiText('kpi-net-actual', net.actual_annualized, '');
        setKpiText('kpi-net-pct', net.margin_pct, '%');
    }

    function renderMetaStrip(payload) {
        if (!el.metaStrip) return;
        const branch = (payload && payload.branch) || {};
        const doc = payload && payload.gl_actual_document;
        const year = (payload && payload.budget_year) || getSelectedYear();

        const branchText = '<span class="badge bg-primary me-2">สาขา: ' +
            escapeHtml(branch.code) + ' — ' + escapeHtml(branch.name) + '</span>' +
            '<span class="badge bg-secondary me-2">ปีงบประมาณ: ' + escapeHtml(year) + '</span>';

        if (!doc) {
            el.metaStrip.innerHTML = branchText +
                '<span class="badge bg-warning text-dark">GL Actual Template: ยังไม่พบข้อมูลปี ' + escapeHtml(year) + '</span>';
            return;
        }

        el.metaStrip.innerHTML = branchText +
            '<span class="badge bg-info text-dark me-2">GL Actual: ' + escapeHtml(doc.document_no) + ' (' + escapeHtml(doc.status) + ')</span>' +
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
            state.payload = data;
            state.rows = data.rows || [];
            renderKpis(data);
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
    }

    function bindEvents() {
        if (el.yearSelect) {
            el.yearSelect.addEventListener('change', loadDashboardData);
        }
        if (el.btnRefresh) {
            el.btnRefresh.addEventListener('click', loadDashboardData);
        }
        if (el.btnExport) {
            el.btnExport.addEventListener('click', exportDashboardExcel);
        }
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
        if (getSelectedBranch()) {
            loadDashboardData();
        } else {
            setLoading(false);
        }
    });
})();

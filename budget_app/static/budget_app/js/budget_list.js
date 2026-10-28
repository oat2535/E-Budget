const BudgetApp = (function() {
    // SweetAlert2 defaults to heightAuto: true, which recalculates
    // document.body's height on every open/close — a forced reflow of the
    // whole page. On this page specifically (two jspreadsheet grids, many
    // columns, hundreds of cells) that reflow is expensive enough to show
    // up as a slow, non-smooth popup (measured INP 224ms, over Chrome's
    // 200ms "good" threshold) on every Swal.fire() call — save, approve,
    // and cancel confirms alike, since none of them are otherwise related.
    // Shadows the global Swal for the rest of this module so every
    // existing Swal.fire() call site gets the fix for free. Assigned
    // lazily below (not here) — sweetalert2 loads via <script defer> in
    // <head>, but this file is a classic script that runs earlier, during
    // parsing, so window.Swal doesn't exist yet at this point.
    let Swal;

    // ---- Private State ----
    let dataTable = null;
    let fetchController = null;
    let detailModalInstance = null;
    let glModalInstance = null;
    let glDetailTables = [];
    let isGlEditMode = false;
    let currentGlDocNo = '';
    let currentGlDocType = '';
    let currentGlCostCenterName = '';
    let currentGlBranchCode = '';
    let modalTable1 = null;
    let modalTable2 = null;
    let isEditMode = false;
    let currentDocNo = '';
    let currentDocType = '';
    let currentCostCenterName = '';
    let currentBranchCode = '';
    let isUpdating = false;
    let currentCategoryData = [];

    let adjModalInstance = null;
    let adjTable1 = null, adjTable2 = null, adjTable3 = null;
    let isAdjEditMode = false;
    let currentAdjDocNo = '';
    let currentAdjCostCenterName = '';
    let currentAdjBranchCode = '';
    let isAdjUpdating = false;

    let glatModalInstance = null;
    let glatTable = null;
    let isGlatEditMode = false;
    let currentGlatDocNo = '';
    let currentGlatBranchCode = '';
    let currentGlatMonthCount = null;
    let currentGlatGrowthPct1 = 0, currentGlatGrowthPct2 = 0, currentGlatGrowthPct3 = 0;

    // Wait for DOM
    document.addEventListener('DOMContentLoaded', () => {
        // By now every deferred <script> (including sweetalert2) has run —
        // safe to read window.Swal here, unlike at module-load time above.
        Swal = window.Swal.mixin({ heightAuto: false });

        const modalSheetEl = document.getElementById('modalSpreadsheet1');
        if (modalSheetEl) {
            modalSheetEl.addEventListener('keydown', function(e) {
                if (modalTable1 && modalTable1.selectedCell && isEditMode) {
                    const x = modalTable1.selectedCell[0];
                    const isNonVet = currentDocType === 'NON VET';
                    const isMed = currentDocType === 'Medical Equipment';
                    const isComp = currentDocType === 'Computer Equipment';
                    const isFurniture = currentDocType === 'Furniture';
                    const isTools = currentDocType === 'Tools & Equipment';
                    const isCar = currentDocType === 'CAR';
                    const isRenovate = currentDocType === 'Renovate';
                    const isSoftware = currentDocType === 'Software';
                    const isEquipment = isMed || isComp || isFurniture || isTools || isCar || isRenovate || isSoftware;
                    const isVet = currentDocType === 'VET';
                    if (isEquipment || isVet || isNonVet) {
                        const hasDetailCol = isEquipment || isVet || isNonVet;
                        const priceCol = hasDetailCol ? 2 : 1;
                        const startCol = priceCol + 1 + (isNonVet ? 1 : 0);
                        const endCol = startCol + 11;
                        if (x >= startCol && x <= endCol) {
                            if (e.key === '.' || e.key === ',' || e.keyCode === 190 || e.keyCode === 110 || e.key === '-' || e.keyCode === 189) {
                                e.preventDefault();
                            }
                        }
                    }
                }
            }, true);

            modalSheetEl.addEventListener('input', function(e) {
                if (modalTable1 && modalTable1.selectedCell && isEditMode) {
                    const x = modalTable1.selectedCell[0];
                    const isNonVet = currentDocType === 'NON VET';
                    const isMed = currentDocType === 'Medical Equipment';
                    const isComp = currentDocType === 'Computer Equipment';
                    const isFurniture = currentDocType === 'Furniture';
                    const isTools = currentDocType === 'Tools & Equipment';
                    const isCar = currentDocType === 'CAR';
                    const isRenovate = currentDocType === 'Renovate';
                    const isSoftware = currentDocType === 'Software';
                    const isEquipment = isMed || isComp || isFurniture || isTools || isCar || isRenovate || isSoftware;
                    const isVet = currentDocType === 'VET';
                    if (isEquipment || isVet || isNonVet) {
                        const hasDetailCol = isEquipment || isVet || isNonVet;
                        const priceCol = hasDetailCol ? 2 : 1;
                        const startCol = priceCol + 1 + (isNonVet ? 1 : 0);
                        const endCol = startCol + 11;
                        if (x >= startCol && x <= endCol && e.target && e.target.classList.contains('jexcel_editor')) {
                            if (e.target.value) {
                                let clean = e.target.value.replace(/[^0-9]/g, '');
                                clean = clean.replace(/^0+(?=\d)/, '');
                                if (clean !== e.target.value) {
                                    e.target.value = clean;
                                }
                            }
                        }
                    }
                }
            }, true);
        }

        const adjModalSheetEl = document.getElementById('adjModalSpreadsheet1');
        if (adjModalSheetEl) {
            adjModalSheetEl.addEventListener('keydown', function(e) {
                if (adjTable1 && adjTable1.selectedCell && isAdjEditMode) {
                    const x = adjTable1.selectedCell[0];
                    if (x >= 13 && x <= 24) {
                        if (e.key === '.' || e.key === ',' || e.keyCode === 190 || e.keyCode === 110 || e.key === '-' || e.keyCode === 189) {
                            e.preventDefault();
                        }
                    }
                }
            }, true);

            adjModalSheetEl.addEventListener('input', function(e) {
                if (adjTable1 && adjTable1.selectedCell && isAdjEditMode) {
                    const x = adjTable1.selectedCell[0];
                    if (x >= 13 && x <= 24 && e.target && e.target.classList.contains('jexcel_editor')) {
                        if (e.target.value) {
                            let clean = e.target.value.replace(/[^0-9]/g, '');
                            clean = clean.replace(/^0+(?=\d)/, '');
                            if (clean !== e.target.value) {
                                e.target.value = clean;
                            }
                        }
                    }
                }
            }, true);
        }
    });

    const vetItems = JSON.parse(document.getElementById('vet-items-data').textContent);
    const nonVetItems = JSON.parse(document.getElementById('nonvet-items-data').textContent);
    const medItems = document.getElementById('med-items-data') ? JSON.parse(document.getElementById('med-items-data').textContent) : [];
    const compItems = document.getElementById('comp-items-data') ? JSON.parse(document.getElementById('comp-items-data').textContent) : [];
    const furnitureItems = document.getElementById('furniture-items-data') ? JSON.parse(document.getElementById('furniture-items-data').textContent) : [];
    const toolsItems = document.getElementById('tools-items-data') ? JSON.parse(document.getElementById('tools-items-data').textContent) : [];
    const carItems = document.getElementById('car-items-data') ? JSON.parse(document.getElementById('car-items-data').textContent) : [];
    const renovateItems = document.getElementById('renovate-items-data') ? JSON.parse(document.getElementById('renovate-items-data').textContent) : [];
    const softwareItems = document.getElementById('software-items-data') ? JSON.parse(document.getElementById('software-items-data').textContent) : [];

    // Fixed 181-row P&L outline + the static 22-branch list for GL Actual
    // Template — unrelated to needsBranchSelection/branchOptions above,
    // which are the CURRENT USER's own imedx branch(es) and don't apply to
    // this doc_type's plain "pick any branch" dropdown.
    const glatTemplateRows = document.getElementById('glat-template-rows-data') ? JSON.parse(document.getElementById('glat-template-rows-data').textContent) : [];
    const glatBranches = document.getElementById('glat-branches-data') ? JSON.parse(document.getElementById('glat-branches-data').textContent) : [];

    // Cost Center / branch dropdown sources for edit mode — same data the
    // add-budget pages use (get_cost_centers_json / get_branch_selection_context
    // in views.py), embedded once here and shared across all 3 modals since
    // only one is ever open at a time.
    const costCenters = JSON.parse(document.getElementById('cost-centers-data').textContent);
    const branchOptions = document.getElementById('branch-options-data') ? JSON.parse(document.getElementById('branch-options-data').textContent) : [];
    const needsBranchSelection = !!(window.APP_CONFIG && window.APP_CONFIG.needsBranchSelection);

    // Swaps a doc-info <td> from plain text to a TomSelect <select>,
    // pre-selected to the document's current value. Shared by all 3
    // modals' edit-mode toggles (Cost Center always; branch only when
    // needsBranchSelection — single-branch users have nothing to pick,
    // same as the add-budget pages never showing that dropdown for them).
    function buildCostCenterSelect(cellId, currentValue, onChange) {
        const cell = document.getElementById(cellId);
        if (!cell) return;
        const selectId = cellId + 'Select';
        cell.innerHTML = `<select id="${selectId}" class="form-select form-select-sm"></select>`;
        const ts = new TomSelect(`#${selectId}`, {
            options: costCenters.map(cc => ({ value: cc.cost_center_name, text: `${cc.cost_center_code}: ${cc.cost_center_name}` })),
            valueField: 'value',
            labelField: 'text',
            searchField: ['text', 'value'],
            create: false,
            placeholder: '-- เลือก Cost Center --',
            onChange: onChange,
            // This <td> lives inside a .table-responsive wrapper, which per
            // the CSS overflow spec forces overflow-y:auto the moment
            // overflow-x is anything but visible — clipping the dropdown
            // panel no matter what we set on the container directly.
            // Rendering the panel into <body> instead sidesteps that
            // entirely. Must be the literal string 'body', not
            // document.body — TomSelect's positionDropdown() only computes
            // and applies the control-relative top/left/width when it sees
            // the exact string "body" (`if ("body" === this.settings.
            // dropdownParent)`); passed the element itself, that check
            // silently fails, the dropdown never gets positioned at all,
            // and it falls back to plain CSS (position:absolute; top:100%)
            // relative to <body> as a whole — landing near the bottom of
            // the page instead of under the control, with no error to
            // reveal why.
            dropdownParent: 'body',
        });
        if (currentValue) ts.setValue(currentValue, true);
    }

    function buildBranchSelect(cellId, currentValue, onChange) {
        if (!needsBranchSelection) return;
        const cell = document.getElementById(cellId);
        if (!cell) return;
        const selectId = cellId + 'Select';
        cell.innerHTML = `<select id="${selectId}" class="form-select form-select-sm"></select>`;
        const ts = new TomSelect(`#${selectId}`, {
            options: branchOptions.map(b => ({ value: b.code, text: `${b.code} - ${b.name}` })),
            valueField: 'value',
            labelField: 'text',
            searchField: ['text', 'value'],
            create: false,
            placeholder: '-- เลือกสาขา --',
            onChange: onChange,
            dropdownParent: 'body', // see buildCostCenterSelect above — must be the string 'body', not document.body
        });
        if (currentValue) ts.setValue(currentValue, true);
    }

    // GL dropdown source for editing GL Entry/Budget Plan documents — same
    // gl_name-displayed/gl_code-stored pattern as budget_add_gl_entry.html.
    // Fetched lazily (not embedded in the page) since it's only ever needed
    // once a document's GL edit mode is actually entered (toggleGlEditMode
    // below) — the full GL master table doesn't belong in every landing-page
    // load. generalLedgersPromise dedupes concurrent callers so a rapid
    // double-toggle of edit mode doesn't fire the fetch twice.
    let generalLedgers = null;
    let glNames = [];
    let generalLedgersPromise = null;
    function ensureGeneralLedgersLoaded() {
        if (generalLedgers !== null) return Promise.resolve();
        if (!generalLedgersPromise) {
            generalLedgersPromise = fetch(window.APP_CONFIG.urls.apiGeneralLedgers)
                .then(handleApiResponse)
                .then(data => {
                    generalLedgers = data.general_ledgers;
                    // Sorted once here (not inside the dropdown's per-click
                    // rebuild, which jspreadsheet/jSuites always re-sorts
                    // internally regardless — pre-sorting lets that repeated
                    // internal sort do less work).
                    glNames = generalLedgers.map(g => g.gl_name).sort((a, b) => a.localeCompare(b, 'th'));
                });
        }
        return generalLedgersPromise;
    }
    const getGlCode = (name) => {
        const match = (generalLedgers || []).find(g => g.gl_name === name);
        return match ? match.gl_code : null;
    };

    const getNum = (val) => parseFloat(String(val).replace(/,/g, '')) || 0;

    // Carry-forward budget: every month's cost is the running headcount/diff
    // total (everything entered so far this year) times the rate, not just
    // that month's own entry — headcount (or a position change) keeps
    // costing money in every month after it takes effect, including the
    // month it started in. Copied verbatim from budget_add.html /
    // budget_add_non_vet.html / budget_add_adjustment.html so the add and
    // edit flows compute identically — used by onSpreadsheetChange (VET/NON
    // VET only) and onAdjSpreadsheetChange below.
    const computeMonthlyBudget = (monthCounts, rate) => {
        let cumulative = 0;
        return monthCounts.map((count) => {
            cumulative += count;
            return { count, cost: cumulative * rate };
        });
    };

    // Set server-side on <body> (see base.html) — the edit button for a
    // document-detail modal only exists in the DOM at all for users who
    // can edit *something* (can_edit_own_documents in budget_list.html:
    // ALL_BRANCH_USERNAMES or a MANAGER-tier employee), but a MANAGER-tier
    // user may only edit documents they created themselves — checked here,
    // per document, every time one is opened, since the same button
    // element is reused across different documents' creators.
    const currentUsername = document.body.dataset.username || '';
    const isPrivilegedUser = document.body.dataset.privileged === 'true';

    // status is included here (not just ownership) because APPROVED and
    // CANCELLED are both terminal, locked for everyone including privileged
    // users — without this, Edit would stay visible and only fail once Save
    // is clicked (see the matching lock check in update_document_api).
    function applyEditButtonVisibility(btnEl, createEid, status) {
        if (!btnEl) return;
        const ownsOrPrivileged = isPrivilegedUser || (createEid && currentUsername && createEid.toLowerCase() === currentUsername.toLowerCase());
        btnEl.style.display = (ownsOrPrivileged && status !== 'APPROVED' && status !== 'CANCELLED') ? '' : 'none';
    }

    // Approve is privileged-only, gated server-side (the button isn't even
    // in the DOM otherwise — see is_privileged_user in budget_list.html),
    // so only the status needs checking client-side.
    function applyApproveButtonVisibility(btnEl, status) {
        if (!btnEl) return;
        btnEl.style.display = (status === 'PENDING') ? '' : 'none';
    }

    // Cancel allows creators or privileged users to cancel documents in PENDING state
    function applyCancelButtonVisibility(btnEl, createEid, status) {
        if (!btnEl) return;
        const ownsOrPrivileged = isPrivilegedUser || (createEid && currentUsername && createEid.toLowerCase() === currentUsername.toLowerCase());
        btnEl.style.display = (ownsOrPrivileged && status === 'PENDING') ? '' : 'none';
    }

    // Shared across the list table and all 3 modals' doc-info cell — a pure
    // display-string helper, not per-modal state, so unlike the view/save
    // functions it doesn't need triplicating.
    function statusBadge(status) {
        // Custom hex, not Bootstrap's bg-success/bg-warning: those exact
        // classes are already used by the Medical Equipment / Computer
        // Equipment document-type badges elsewhere on this page, and a
        // status badge reading as the same color as an unrelated type
        // badge defeats the point of either one.
        if (status === 'APPROVED') {
            return '<span class="badge d-flex align-items-center px-2 py-1" style="background-color:#047857; color:#fff; width:fit-content;"><i data-feather="check-circle" style="width:14px;height:14px;" class="me-1"></i>อนุมัติแล้ว</span>';
        }
        if (status === 'CANCELLED') {
            return '<span class="badge bg-danger d-flex align-items-center px-2 py-1" style="width:fit-content;"><i data-feather="x-circle" style="width:14px;height:14px;" class="me-1"></i>ยกเลิก</span>';
        }
        return '<span class="badge d-flex align-items-center px-2 py-1" style="background-color:#daa520; color:#212529; width:fit-content;"><i data-feather="clock" style="width:14px;height:14px;" class="me-1"></i>รออนุมัติ</span>';
    }

    // In document detail modals, only show the status column if the document is CANCELLED.
    // If not cancelled (PENDING, APPROVED, etc.), keep the column hidden.
    function renderModalDocStatus(thEl, tdEl, status) {
        if (!thEl && !tdEl) return;
        if (status === 'CANCELLED') {
            if (thEl) thEl.style.display = '';
            if (tdEl) {
                tdEl.style.display = '';
                tdEl.innerHTML = statusBadge('CANCELLED');
            }
        } else {
            if (thEl) thEl.style.display = 'none';
            if (tdEl) {
                tdEl.style.display = 'none';
                tdEl.innerHTML = '';
            }
        }
    }

    // Shared response handler for every fetch() call in this module: an
    // expired session comes back as HTTP 401 JSON (see login_required_json
    // in views.py) rather than a redirect to the login page HTML, which
    // response.json() cannot parse. Catch it here once instead of at every
    // call site, and send the user to log in again.
    const SESSION_EXPIRED = 'SESSION_EXPIRED';
    let sessionExpiredDialogShown = false;
    function handleApiResponse(response) {
        if (response.status === 401) {
            if (!sessionExpiredDialogShown) {
                sessionExpiredDialogShown = true;
                Swal.fire({
                    icon: 'warning',
                    title: 'เซสชันหมดอายุ',
                    text: 'คุณไม่ได้ใช้งานระบบเกิน 30 นาที กรุณาเข้าสู่ระบบใหม่อีกครั้ง',
                    confirmButtonText: 'เข้าสู่ระบบ',
                    allowOutsideClick: false,
                    allowEscapeKey: false
                }).then(() => {
                    window.location.href = '/login/';
                });
            }
            return Promise.reject(new Error(SESSION_EXPIRED));
        }
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json();
    }

    // Bootstrap's own modal-open transition (.modal-dialog transform 0.3s +
    // backdrop fade 0.15s, both in styles.css) starts the instant .show()
    // is called — a separate animation from any custom fade-in applied to
    // a modal's own content later. Every "view details" popup waits on
    // this before doing its heavy jspreadsheet construction, so that work
    // can never block the main thread while either animation is still
    // playing (visible stutter) — not just the custom fade-in, which was
    // the only thing accounted for previously.
    function waitForModalShown(modalEl) {
        // Bootstrap's .show() is a no-op when the modal is already open (e.g.
        // reloading data after "ยกเลิกการแก้ไข" while the modal never closed),
        // so shown.bs.modal never fires again — waiting for it here would
        // hang forever. Already open means already settled: resolve now.
        if (modalEl.classList.contains('show')) {
            return Promise.resolve();
        }
        return new Promise(resolve => {
            modalEl.addEventListener('shown.bs.modal', resolve, { once: true });
        });
    }

    const onSpreadsheetChange = function(instance, cell, x, y, value) {
        if (!modalTable1 || !modalTable2 || isUpdating || !isEditMode) return;
        isUpdating = true;

        try {
            x = parseInt(x);
            y = parseInt(y);

            // modalTable1's row count can only get ahead of modalTable2's
            // through the oninsertrow hook below, which keeps them synced
            // regardless of how the row was added — but guard here too in
            // case a future jspreadsheet interaction (e.g. paste) slips a
            // row past it.
            if (y >= modalTable2.rows.length) return;

            const isNonVet = currentDocType === 'NON VET';
            const isMed = currentDocType === 'Medical Equipment';
            const isComp = currentDocType === 'Computer Equipment';
            const isFurniture = currentDocType === 'Furniture';
            const isTools = currentDocType === 'Tools & Equipment';
            const isCar = currentDocType === 'CAR';
            const isRenovate = currentDocType === 'Renovate';
            const isSoftware = currentDocType === 'Software';
            const isEquipment = isMed || isComp || isFurniture || isTools || isCar || isRenovate || isSoftware;
            const isVet = currentDocType === 'VET';
            let itemsList = vetItems;
            if (isNonVet) itemsList = nonVetItems;
            if (isMed) itemsList = medItems;
            else if (isComp) itemsList = compItems;
            else if (isFurniture) itemsList = furnitureItems;
            else if (isTools) itemsList = toolsItems;
            else if (isCar) itemsList = carItems;
            else if (isRenovate) itemsList = renovateItems;
            else if (isSoftware) itemsList = softwareItems;
            // Every type reaching this function now has a "รายละเอียด" text
            // column right after the item/position dropdown (col 0) —
            // Equipment and VET insert one more column before months
            // (price/salary), NON VET inserts two (salary, then its own
            // ค่าวัดระดับ/ตำแหน่ง allowance) — priceCol/allowanceCol/
            // startCol/endCol below are computed from that, not hardcoded,
            // since there are now 3 different widths instead of a binary
            // shifted/unshifted split.
            const hasDetailCol = isEquipment || isVet || isNonVet;
            const priceCol = hasDetailCol ? 2 : 1;
            const allowanceCol = priceCol + 1; // only meaningful when isNonVet
            const startCol = priceCol + 1 + (isNonVet ? 1 : 0);
            const endCol = startCol + 11;

            // If position changed, update salary
            if (x === 0) {
                const trimmedVal = (value || '').trim();
                const match = trimmedVal !== '' ? itemsList.find(i => i.name === trimmedVal) : null;
                if (match) {
                    const salary = isEquipment ? match.purchase_price : match.salary;
                    modalTable1.setValueFromCoords(priceCol, y, salary, true);
                    if (isNonVet) {
                        modalTable1.setValueFromCoords(allowanceCol, y, match.position_allowance || 0, true);
                    }
                } else {
                    if (trimmedVal !== '') {
                        modalTable1.setValueFromCoords(0, y, '', true);
                    }
                    modalTable1.setValueFromCoords(priceCol, y, 0, true);
                    if (isNonVet) {
                        modalTable1.setValueFromCoords(allowanceCol, y, 0, true);
                    }
                    if (trimmedVal !== '') {
                        const label = isEquipment ? 'รายการ' : 'ตำแหน่ง';
                        Swal.fire({
                            icon: 'warning',
                            title: 'แจ้งเตือน',
                            text: `ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือก${label}จากรายการ Dropdown เท่านั้น ("${trimmedVal}" ไม่มีอยู่ในรายการตัวเลือก)`,
                            timer: 3000,
                            showConfirmButton: false,
                            toast: true,
                            position: 'top-end'
                        });
                    }
                }
            }

            // Enforce integer headcount/quantity without leading zeros in month columns
            if (x >= startCol && x <= endCol) {
                const rawVal = String(value || '').trim();
                if (rawVal !== '') {
                    const cleanStr = rawVal.replace(/,/g, '');
                    const hasLeadingZero = /^0\d+/.test(cleanStr);
                    const num = parseFloat(cleanStr);
                    const isDecimal = !isNaN(num) && !Number.isInteger(num);

                    if (isDecimal || hasLeadingZero) {
                        const intVal = isNaN(num) ? 0 : Math.floor(num);
                        modalTable1.setValueFromCoords(x, y, intVal, false);
                        let warnMsg = (isEquipment ? 'จำนวนรายการ' : 'จำนวนคน') + 'ต้องเป็นตัวเลขจำนวนเต็มเท่านั้น ไม่อนุญาตให้กรอกเลขทศนิยม';
                        if (hasLeadingZero) {
                            warnMsg = 'ไม่อนุญาตให้กรอกตัวเลขที่มี 0 นำหน้า (เช่น 03, 04) ระบบปรับเป็น ' + intVal + ' ให้เรียบร้อยแล้ว';
                        }
                        Swal.fire({
                            icon: 'warning',
                            title: 'แจ้งเตือน',
                            text: warnMsg,
                            timer: 2500,
                            showConfirmButton: false,
                            toast: true,
                            position: 'top-end'
                        });
                    }
                }
            }

            // Calculate total for this row in table1
            const rowData1 = modalTable1.getRowData(y);
            let sum1 = 0;

            for(let i = startCol; i <= endCol; i++) {
                sum1 += getNum(rowData1[i]);
            }
            modalTable1.setValueFromCoords(endCol + 1, y, sum1, true);

            // Sync with table2
            const pos = rowData1[0];
            const desc = hasDetailCol ? rowData1[1] : undefined;
            const sal = getNum(rowData1[priceCol]);

            modalTable2.setValueFromCoords(0, y, pos, true);
            if (hasDetailCol) {
                modalTable2.setValueFromCoords(1, y, desc, true);
            }
            modalTable2.setValueFromCoords(priceCol, y, sal, true);

            let total_sal = sal;
            if (isNonVet) {
                const allow = getNum(rowData1[allowanceCol]);
                modalTable2.setValueFromCoords(allowanceCol, y, allow, true);
                total_sal += allow;
            }

            let sum2 = 0;
            if (isEquipment) {
                // Equipment is a one-off purchase per month, not a
                // recurring cost — stays a plain per-month multiply,
                // matching budget_add_medical_equipment.html etc.
                for(let i = startCol; i <= endCol; i++) {
                    const count = getNum(rowData1[i]);
                    const cost = count * total_sal;
                    modalTable2.setValueFromCoords(i, y, cost, true);
                    sum2 += cost;
                }
            } else {
                const monthCounts = [];
                for(let i = startCol; i <= endCol; i++) {
                    monthCounts.push(getNum(rowData1[i]));
                }
                computeMonthlyBudget(monthCounts, total_sal).forEach((m, idx) => {
                    modalTable2.setValueFromCoords(startCol + idx, y, m.cost, true);
                    sum2 += m.cost;
                });
            }
            modalTable2.setValueFromCoords(endCol + 1, y, sum2, true);
        } finally {
            // Always clear the guard, even if something above throws —
            // otherwise every future edit silently no-ops forever (the bug
            // behind "table freezes until you refresh the page").
            isUpdating = false;
        }
    };

     // Store raw data for fast client-side filtering

    function renderDataTable(dataArray) {
        if (dataTable) {
            try {
                dataTable.destroy();
            } catch (error) {
                console.warn('Datatable destroy skipped due to state mismatch:', error);
            }
            dataTable = null;
        }
        
        const container = document.getElementById('tableContainer');
        container.innerHTML = `
            <table id="datatablesSimple" class="table">
                <thead>
                    <tr>
                        <th>Document No</th>
                        <th>Type</th>
                        <th>Branch</th>
                        <th>Budget Year</th>
                        <th>Total Budget</th>
                        <th>Date Created</th>
                        <th>Created By</th>
                        <!-- <th>สถานะ</th> -->
                        <th class="text-center text-nowrap" style="width: 80px;">Action</th>
                    </tr>
                </thead>
                <tbody id="tableBody"></tbody>
            </table>
        `;
        const tbody = document.getElementById('tableBody');
        
        if (dataArray && dataArray.length > 0) {
            let rowsHtml = '';
            dataArray.forEach(doc => {
                const catBadge = doc.type === 'VET' ?
                    '<span class="badge bg-primary">VET</span>' :
                    doc.type === 'Position Adjustment' ? '<span class="badge bg-info">Position Adjustment</span>' :
                    doc.type === 'Medical Equipment' ? '<span class="badge bg-success">Medical Equipment</span>' :
                    doc.type === 'Computer Equipment' ? '<span class="badge bg-warning text-dark">Computer Equipment</span>' :
                    doc.type === 'Furniture' ? '<span class="badge bg-secondary">Furniture</span>' :
                    doc.type === 'Tools & Equipment' ? '<span class="badge bg-dark">Tools & Equipment</span>' :
                    doc.type === 'CAR' ? '<span class="badge" style="background-color: #fd7e14;">CAR</span>' :
                    doc.type === 'Renovate' ? '<span class="badge" style="background-color: #d63384;">Renovate</span>' :
                    doc.type === 'Software' ? '<span class="badge" style="background-color: #0ea5e9;">Software</span>' :
                    doc.type === 'GL Entry' ? '<span class="badge" style="background-color: #0dcaf0;">EXPENSE</span>' :
                    doc.type === 'Revenue' ? '<span class="badge" style="background-color: #84cc16;">Revenue</span>' :
                    doc.type === 'Budget Plan' ? '<span class="badge" style="background-color: #20c997;">Budget Plan</span>' :
                    doc.type === 'GL Actual Template' ? '<span class="badge" style="background-color: #6f42c1;">GL Actual Template</span>' :
                    '<span class="badge" style="background-color: #6610f2;">NON VET</span>';
                const isGeneralLedgerDoc = doc.type === 'GL Entry' || doc.type === 'Revenue' || doc.type === 'Budget Plan';
                const isGlatDoc = doc.type === 'GL Actual Template';
                const actionUrl = isGlatDoc ?
                    `javascript:viewGlatDocumentDetails('${doc.document_no}')` :
                    isGeneralLedgerDoc ?
                    `javascript:viewGeneralLedgerDocumentDetails('${doc.document_no}', '${doc.type}')` :
                    `javascript:viewDocumentDetails('${doc.document_no}', '${doc.type}')`;

                const isCancelled = doc.status === 'CANCELLED';

                const docNoCell = isCancelled ? `
                    <div class="d-inline-flex align-items-center flex-wrap gap-2">
                        <span class="fw-semibold text-dark">${doc.document_no}</span>
                        <span class="badge d-inline-flex align-items-center px-2 py-0.5" style="background-color: #fee2e2; color: #dc2626; border: 1px solid #fecaca; font-size: 0.72rem; font-weight: 600; border-radius: 9999px; letter-spacing: 0.2px;" title="รายการนี้ถูกยกเลิกแล้ว">
                            <i data-feather="x-circle" style="width: 11px; height: 11px; stroke-width: 2.5;" class="me-1"></i>ยกเลิก
                        </span>
                    </div>
                ` : `${doc.document_no}`;

                // Per-row stagger delay is handled entirely in CSS via
                // nth-child (see polish.css) — simple-datatables rebuilds
                // this markup on init and drops any inline style we'd set
                // here, so a JS-computed animation-delay would be discarded.
                rowsHtml += `
                    <tr class="${isCancelled ? 'table-light' : ''}">
                        <td>${docNoCell}</td>
                        <td>${catBadge}</td>
                        <td>${doc.base_branch_id || '-'}</td>
                        <td>${doc.budget_year}</td>
                        <td>${isCancelled ? `<span class="text-decoration-line-through text-muted" title="ยอดงบประมาณที่ยกเลิก">${Number(doc.total_budget || 0).toLocaleString('en-US', {maximumFractionDigits: 0})}</span>` : Number(doc.total_budget || 0).toLocaleString('en-US', {maximumFractionDigits: 0})}</td>
                        <td>${doc.create_date}</td>
                        <td>${doc.create_eid}</td>
                        <!-- <td>${statusBadge(doc.status)}</td> -->
                        <td class="text-center text-nowrap">
                            <a class="btn btn-datatable btn-icon btn-transparent-dark" href="${actionUrl}" title="ดูรายละเอียด"><i data-feather="eye"></i></a>
                        </td>
                    </tr>
                `;
            });
            tbody.innerHTML = rowsHtml;
            // Feather icons need an explicit replace() after being inserted
            // dynamically (unlike Font Awesome's auto-scanning MutationObserver).
            if (typeof feather !== 'undefined') feather.replace();
        }

        // Retrigger the fade-in each render: #tableContainer persists across
        // renders (only its innerHTML changes), so the class must be removed
        // and re-added with a forced reflow for the CSS animation to replay.
        container.classList.remove('table-fade-in');
        void container.offsetWidth;
        container.classList.add('table-fade-in');
        document.getElementById('tableContainer').style.display = 'block';

        dataTable = new simpleDatatables.DataTable("#datatablesSimple", {
            perPage: 10,
            searchable: true,
            labels: {
                placeholder: "ค้นหา...",
                perPage: "รายการต่อหน้า",
                noRows: "ไม่มีข้อมูล",
                info: "แสดงรายการที่ {start} ถึง {end} จากทั้งหมด {rows} รายการ"
            }
        });

        // Ensure feather icons are rendered on any pagination, sort, search, or init
        const reRenderFeather = () => { if (typeof feather !== 'undefined') feather.replace(); };
        dataTable.on('datatable.init', reRenderFeather);
        dataTable.on('datatable.page', reRenderFeather);
        dataTable.on('datatable.sort', reRenderFeather);
        dataTable.on('datatable.search', reRenderFeather);

        // Best Practice: Handle the native 'search' and 'input' events for the browser's clear (X) button
        setTimeout(() => {
            const container = document.getElementById('tableContainer');
            const searchInput = container.querySelector('.dataTable-input');
            if (searchInput) {
                const triggerClear = function() {
                    if (searchInput.value === '') {
                        // Force a complete UI refresh to guarantee stability
                        applyFilters();
                    }
                };
                searchInput.addEventListener('search', triggerClear);
                // Also catch manual clears that might not trigger 'search'
                searchInput.addEventListener('input', triggerClear);
            }
        }, 100);
    }

    // filterCreateName/filterBranch/filterCostCenter only exist in the DOM
    // for is_privileged_user (see budget_list.html) — getElementById returns
    // null for everyone else, so each read below falls back to 'ALL' (no
    // constraint) rather than throwing.
    function applyFilters() {
        const selectedType = document.getElementById('docTypeFilter').value;
        const createNameEl = document.getElementById('filterCreateName');
        const branchEl = document.getElementById('filterBranch');
        const costCenterEl = document.getElementById('filterCostCenter');

        // GL Actual Template documents do not have a cost center (cost_center_name is '-').
        // If the user selects GL Actual Template while a specific cost center was chosen,
        // reset cost center to 'ALL' to avoid returning an unintentionally empty list.
        if (selectedType === 'GL Actual Template' && costCenterEl && costCenterEl.value !== 'ALL') {
            costCenterEl.value = 'ALL';
        }

        const selectedCreateName = createNameEl ? createNameEl.value : 'ALL';
        const selectedBranch = branchEl ? branchEl.value : 'ALL';
        const selectedCostCenter = costCenterEl ? costCenterEl.value : 'ALL';

        const filteredData = currentCategoryData.filter(doc => {
            if (selectedType !== 'ALL' && doc.type !== selectedType) return false;
            if (selectedCreateName !== 'ALL' && doc.create_eid !== selectedCreateName) return false;
            if (selectedBranch !== 'ALL' && doc.base_branch_id !== selectedBranch) return false;
            if (selectedCostCenter !== 'ALL' && doc.cost_center_name !== selectedCostCenter) return false;
            return true;
        });
        renderDataTable(filteredData);
    }

    // Rebuilds the 3 privileged-only filter dropdowns' options from whatever
    // values actually appear in this category's freshly-fetched data (same
    // "derive from loaded data" convention docTypeFilter's C01/C02 options
    // already use) — skipped entirely when the elements aren't in the DOM.
    function populateExtraFilters(data) {
        const createNameEl = document.getElementById('filterCreateName');
        const branchEl = document.getElementById('filterBranch');
        const costCenterEl = document.getElementById('filterCostCenter');
        if (!createNameEl && !branchEl && !costCenterEl) return;

        const buildOptions = (el, values, allLabel) => {
            if (!el) return;
            const unique = [...new Set(values.filter(v => v && v !== '-'))].sort((a, b) => a.localeCompare(b, 'th'));
            el.innerHTML = `<option value="ALL">${allLabel}</option>` + unique.map(v => `<option value="${v}">${v}</option>`).join('');
            el.value = 'ALL';
        };
        buildOptions(createNameEl, data.map(d => d.create_eid), 'ผู้สร้างทั้งหมด');
        buildOptions(branchEl, data.map(d => d.base_branch_id), 'ทุกสาขา');
        buildOptions(costCenterEl, data.map(d => d.cost_center_name), 'ทุก Cost Center');
    }

    // Patches the one row's status in the already-fetched list data and
    // re-renders locally (via applyFilters, which respects whatever filters
    // are currently selected) — cheaper than re-fetching the whole
    // category, and doesn't reset the user's filters back to "ALL" the way
    // calling fetchDocuments() again would.
    function updateListRowStatus(docNo, newStatus) {
        const doc = currentCategoryData.find(d => d.document_no === docNo);
        if (doc) {
            doc.status = newStatus;
            applyFilters();
        }
    }

    // Sums a save payload's monthly costs — costKey is 'cost' for
    // VET/NON VET/equipment/Position Adjustment or 'amount' for GL
    // Entry/Budget Plan (see get_budget_documents_api's same split in
    // views.py). Computed from the payload that's actually being POSTed,
    // not re-derived some other way, so it can never drift from what
    // actually gets persisted.
    function sumMonthlyDataTotal(dataToSave, costKey) {
        let total = 0;
        dataToSave.forEach(row => {
            Object.values(row.monthly_data || {}).forEach(m => { total += Number(m[costKey]) || 0; });
        });
        return total;
    }

    // Same idea as updateListRowStatus, for the Total Budget column — keeps
    // the background list in sync after an edit-save without waiting for
    // the user to reopen the category.
    function updateListRowTotalBudget(docNo, newTotal) {
        const doc = currentCategoryData.find(d => d.document_no === docNo);
        if (doc) {
            doc.total_budget = newTotal;
            applyFilters();
        }
    }

    function fetchDocuments(categoryCode) {
        if (fetchController) {
            fetchController.abort(); // Cancel previous request if user clicks quickly
        }
        fetchController = new AbortController();
        
        const filterSelect = document.getElementById('docTypeFilter');
        filterSelect.innerHTML = '<option value="ALL">ทั้งหมด (All Types)</option>';
        if (categoryCode === 'C01') {
            filterSelect.innerHTML += `
                <option value="VET">VET Manpower</option>
                <option value="NON VET">NON VET Manpower</option>
                <option value="Position Adjustment">Position Adjustment</option>
            `;
        } else if (categoryCode === 'C02') {
            filterSelect.innerHTML += `
                <option value="Medical Equipment">Medical Equipment</option>
                <option value="Computer Equipment">Computer Equipment</option>
                <option value="Furniture">Furniture</option>
                <option value="Tools & Equipment">Tools & Equipment</option>
                <option value="CAR">CAR</option>
                <option value="Renovate">Renovate</option>
                <option value="Software">Software</option>
            `;
        } else if (categoryCode === 'C03') {
            filterSelect.innerHTML += `
                <option value="GL Entry">EXPENSE</option>
                <option value="Revenue">Revenue</option>
                <option value="GL Actual Template">GL Actual Template</option>
            `;
        }
        
        const urlTemplate = window.APP_CONFIG.urls.apiGetDocuments;
        const url = urlTemplate.replace('DUMMY', categoryCode);

        // filterCreateName/filterBranch/filterCostCenter only exist for
        // is_privileged_user — each toggle is a no-op (skipped) otherwise.
        const setExtraFiltersDisplay = (value) => {
            ['filterCreateName', 'filterBranch', 'filterCostCenter'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.style.display = value;
            });
        };

        document.getElementById('placeholderText').style.display = 'none';
        document.getElementById('tableContainer').style.display = 'none';
        document.getElementById('loadingSpinner').style.display = 'block';
        document.getElementById('docTypeFilter').style.display = 'none';
        setExtraFiltersDisplay('none');

        fetch(url, { signal: fetchController.signal })
            .then(handleApiResponse)
            .then(result => {
                document.getElementById('loadingSpinner').style.display = 'none';

                if (result.status === 'success' && result.data && result.data.length > 0) {
                    currentCategoryData = result.data;
                    document.getElementById('docTypeFilter').style.display = 'inline-block';
                    document.getElementById('docTypeFilter').value = 'ALL';
                    populateExtraFilters(currentCategoryData);
                    setExtraFiltersDisplay('inline-block');
                    renderDataTable(currentCategoryData);
                } else {
                    currentCategoryData = [];
                    renderDataTable([]);
                }
            })
            .catch(error => {
                if (error.name === 'AbortError') {
                    console.log('Fetch aborted due to rapid user clicks.');
                    return; // Gracefully exit without showing error
                }
                if (error.message === SESSION_EXPIRED) {
                    return; // Already handled by handleApiResponse
                }
                console.error('Error fetching documents:', error);
                document.getElementById('loadingSpinner').style.display = 'none';
                document.getElementById('tableContainer').style.display = 'none';
                document.getElementById('docTypeFilter').style.display = 'none';
                setExtraFiltersDisplay('none');
                document.getElementById('placeholderText').style.display = 'block';
                document.getElementById('placeholderText').innerText = 'ยังไม่มีรายการเอกสารสำหรับหมวดหมู่นี้ หรือเซิร์ฟเวอร์ไม่สามารถตอบสนองได้';
                document.getElementById('placeholderText').className = 'text-muted'; // Remove text-danger if previously added
            });
    }

    function viewDocumentDetails(docNo, docType) {
        if (docType === 'Position Adjustment') {
            viewAdjustmentDetails(docNo);
            return;
        }
        currentDocNo = docNo;
        currentDocType = docType;
        isEditMode = false;
        
        const btnEdit = document.getElementById('btnEditMode');
        if (btnEdit) {
            btnEdit.innerHTML = '<i data-feather="edit-2" class="me-1"></i> แก้ไขข้อมูล';
            btnEdit.classList.remove('btn-outline-danger');
            btnEdit.classList.add('btn-primary');
        }
        const btnAddRow = document.getElementById('btnAddRow');
        const btnSave = document.getElementById('btnSaveDocument');
        const btnClose = document.getElementById('btnCloseModal');
        
        if(btnAddRow) btnAddRow.style.display = 'none';
        if(btnSave) btnSave.style.display = 'none';
        if(btnClose) btnClose.style.display = 'inline-block';

        const modalEl = document.getElementById('documentDetailModal');
        if (!detailModalInstance) {
            detailModalInstance = new bootstrap.Modal(modalEl);
        }
        const shownPromise = waitForModalShown(modalEl);
        detailModalInstance.show();

        document.getElementById('modalContent').style.display = 'none';
        document.getElementById('modalLoadingSpinner').style.display = 'block';

        const urlTemplate = window.APP_CONFIG.urls.apiDocumentDetail;
        const url = urlTemplate.replace('TYPE', encodeURIComponent(docType)).replace('DOCNO', encodeURIComponent(docNo));

        // Spinner stays up until BOTH the fetch and Bootstrap's own modal
        // transition are done — not just the fetch — so there's no gap
        // where the spinner has vanished but the modal is still visibly
        // animating open with nothing shown yet.
        Promise.all([fetch(url).then(handleApiResponse), shownPromise])
            .then(([result]) => {
                document.getElementById('modalLoadingSpinner').style.display = 'none';

                if (result.status === 'success') {
                    // Populate Doc Info
                    document.getElementById('modalDocNo').innerText = result.doc_info.document_no;
                    document.getElementById('modalDocType').innerHTML = result.doc_info.type === 'VET' ? '<span class="badge bg-primary">VET</span>' : result.doc_info.type === 'Medical Equipment' ? '<span class="badge bg-success">Medical Equipment</span>' : result.doc_info.type === 'Computer Equipment' ? '<span class="badge bg-warning text-dark">Computer Equipment</span>' : result.doc_info.type === 'Furniture' ? '<span class="badge bg-secondary">Furniture</span>' : result.doc_info.type === 'Tools & Equipment' ? '<span class="badge bg-dark">Tools & Equipment</span>' : '<span class="badge" style="background-color: #6610f2;">NON VET</span>';
                    document.getElementById('modalDocBranch').innerText = result.doc_info.base_branch_id;
                    currentBranchCode = result.doc_info.base_branch_id || '';
                    currentCostCenterName = result.doc_info.cost_center_name || '';
                    document.getElementById('modalDocCostCenter').innerText = result.doc_info.cost_center_name || '-';
                    document.getElementById('modalDocBudgetYear').innerText = result.doc_info.budget_year;
                    document.getElementById('modalDocCreator').innerText = result.doc_info.create_eid;
                    applyEditButtonVisibility(document.getElementById('btnEditMode'), result.doc_info.create_eid, result.doc_info.status);
                    applyApproveButtonVisibility(document.getElementById('btnApproveDocument'), result.doc_info.status);
                    applyCancelButtonVisibility(document.getElementById('btnCancelDocument'), result.doc_info.create_eid, result.doc_info.status);
                    renderModalDocStatus(document.getElementById('modalDocStatusTh'), document.getElementById('modalDocStatus'), result.doc_info.status);
                    const reasonAlert = document.getElementById('modalCancelReasonAlert');
                    const reasonText = document.getElementById('modalCancelReasonText');
                    if (reasonAlert && reasonText) {
                        if (result.doc_info.status === 'CANCELLED' && result.doc_info.cancel_reason) {
                            reasonText.innerText = result.doc_info.cancel_reason;
                            reasonAlert.style.display = 'block';
                        } else {
                            reasonAlert.style.display = 'none';
                        }
                    }
                    if (typeof feather !== 'undefined') feather.replace();
                    document.getElementById('modalDocDate').innerText = result.doc_info.create_date;

                    // Laid out but not painted — jspreadsheet reads real
                    // dimensions from the container below (getBoundingClientRect
                    // forces layout on demand regardless of paint state), but
                    // nothing is visible yet, so building two full jspreadsheet
                    // grids (real DOM per cell, no virtualization — the same
                    // jexcel characteristic behind the dropdown-open slowness
                    // fixed earlier) can't drop frames on an animation the user
                    // can see. The fade-in animation only starts once
                    // everything is actually ready to show, instead of racing
                    // this construction work (previously scheduled via a
                    // setTimeout(fn, 50) that fired mid-animation and caused
                    // the reported stutter).
                    const modalContentEl = document.getElementById('modalContent');
                    modalContentEl.style.display = 'block';
                    modalContentEl.style.visibility = 'hidden';

                    if (modalTable1) {
                        modalTable1.destroy();
                        modalTable1 = null;
                    }
                    if (modalTable2) {
                        modalTable2.destroy();
                        modalTable2 = null;
                    }
                    document.getElementById('modalSpreadsheet1').innerHTML = '';
                    document.getElementById('modalSpreadsheet2').innerHTML = '';

                    const isNonVet = result.doc_info.type === 'NON VET';
                    const isMed = result.doc_info.type === 'Medical Equipment';
                    const isComp = result.doc_info.type === 'Computer Equipment';
                    const isFurniture = result.doc_info.type === 'Furniture';
                    const isTools = result.doc_info.type === 'Tools & Equipment';
                    const isCar = result.doc_info.type === 'CAR';
                    const isRenovate = result.doc_info.type === 'Renovate';
                    const isSoftware = result.doc_info.type === 'Software';
                    const isEquipment = isMed || isComp || isFurniture || isTools || isCar || isRenovate || isSoftware;
                    const isVet = result.doc_info.type === 'VET';

                    // Columns setup
                    const columns = [
                        { type: 'text', align: 'left', title: isEquipment ? 'เครื่องมือ' : 'ตำแหน่ง', width: 250, readOnly: true }
                    ];
                    if (isEquipment || isVet || isNonVet) {
                        columns.push({ type: 'text', align: 'left', title: 'รายละเอียด', width: 200, readOnly: true });
                    }
                    columns.push({ type: 'numeric', title: isEquipment ? 'ราคาซื้อ' : 'เงินเดือน', width: 100, readOnly: true, mask: '#,##0' });
                    if (isNonVet) {
                        columns.push({ type: 'numeric', title: 'ค่าวัดระดับ/ตำแหน่ง', width: 150, readOnly: true, mask: '#,##0' });
                    }
                    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                    months.forEach(m => {
                        columns.push({ type: 'numeric', title: m, width: 85, readOnly: true, mask: '#,##0' });
                    });
                    columns.push({ type: 'numeric', title: 'รวม', width: 100, readOnly: true, mask: '#,##0' });

                    let data1 = [];
                    let data2 = [];

                    result.manpower_list.forEach(item => {
                        let m = item.monthly_data || {};
                        let row1 = [item.position_name || item.item_name];
                        let row2 = [item.position_name || item.item_name];
                        if (isEquipment || isVet || isNonVet) {
                            row1.push(item.description || '');
                            row2.push(item.description || '');
                        }
                        row1.push(item.salary || item.purchase_price);
                        row2.push(item.salary || item.purchase_price);

                        if (isNonVet) {
                            row1.push(item.position_allowance || 0);
                            row2.push(item.position_allowance || 0);
                        }

                        let sumCount = 0;
                        let sumCost = 0;
                        const mKeys = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
                        mKeys.forEach(k => {
                            let mData = m[k] || {headcount: 0, cost: 0};
                            let hc = parseFloat(mData.headcount) || 0;
                            let ct = parseFloat(mData.cost) || 0;
                            row1.push(hc);
                            row2.push(ct);
                            sumCount += hc;
                            sumCost += ct;
                        });
                        row1.push(sumCount);
                        row2.push(sumCost);

                        data1.push(row1);
                        data2.push(row2);
                    });

                    if (data1.length === 0) {
                        let emptyRow = new Array(columns.length).fill(0);
                        emptyRow[0] = '';
                        if (isEquipment || isVet || isNonVet) emptyRow[1] = '';
                        data1.push([...emptyRow]);
                        data2.push([...emptyRow]);
                    }

                    // Building both grids now is safe from here on: the
                    // container has real layout (display:block above) and
                    // shownPromise already guarantees Bootstrap's own modal
                    // transition has fully finished, so this synchronous
                    // work has no animation left to race.
                    modalTable1 = jspreadsheet(document.getElementById('modalSpreadsheet1'), {
                        data: data1,
                        columns: columns,
                        allowInsertRow: false,
                        allowDeleteRow: false,
                        allowInsertColumn: false,
                        allowManualInsertColumn: false,
                        allowDeleteColumn: false,
                        tableOverflow: true,
                        contextMenu: function() { return false; }
                    });

                    modalTable2 = jspreadsheet(document.getElementById('modalSpreadsheet2'), {
                        data: data2,
                        columns: columns,
                        allowInsertRow: false,
                        allowDeleteRow: false,
                        allowInsertColumn: false,
                        allowManualInsertColumn: false,
                        allowDeleteColumn: false,
                        tableOverflow: true,
                        contextMenu: function() { return false; }
                    });

                    modalContentEl.style.visibility = 'visible';
                    modalContentEl.classList.remove('modal-content-fade-in');
                    void modalContentEl.offsetWidth;
                    modalContentEl.classList.add('modal-content-fade-in');
                } else {
                    if (typeof Swal !== 'undefined') {
                        Swal.fire('เกิดข้อผิดพลาด', result.message, 'error');
                    } else {
                        alert(result.message);
                    }
                    detailModalInstance.hide();
                }
            })
            .catch(err => {
                if (err.message === SESSION_EXPIRED) return;
                console.error(err);
                document.getElementById('modalLoadingSpinner').style.display = 'none';
                if (typeof Swal !== 'undefined') {
                    Swal.fire('เกิดข้อผิดพลาด', 'ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้', 'error');
                } else {
                    alert('ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้');
                }
                detailModalInstance.hide();
            });
    }

    function toggleEditMode() {
        if (!modalTable1 || !modalTable2) return;
        
        isEditMode = !isEditMode;
        
        const btnEdit = document.getElementById('btnEditMode');
        const btnAddRow = document.getElementById('btnAddRow');
        const btnSave = document.getElementById('btnSaveDocument');
        const btnClose = document.getElementById('btnCloseModal');
        
        const isNonVet = currentDocType === 'NON VET';
        const isMed = currentDocType === 'Medical Equipment';
        const isComp = currentDocType === 'Computer Equipment';
        const isFurniture = currentDocType === 'Furniture';
        const isTools = currentDocType === 'Tools & Equipment';
        const isCar = currentDocType === 'CAR';
        const isRenovate = currentDocType === 'Renovate';
        const isSoftware = currentDocType === 'Software';
        const isEquipment = isMed || isComp || isFurniture || isTools || isCar || isRenovate || isSoftware;
        const isVet = currentDocType === 'VET';
        let itemsList = vetItems;
        if (isNonVet) itemsList = nonVetItems;
        if (isMed) itemsList = medItems;
        else if (isComp) itemsList = compItems;
        else if (isFurniture) itemsList = furnitureItems;
        else if (isTools) itemsList = toolsItems;
        else if (isCar) itemsList = carItems;
        else if (isRenovate) itemsList = renovateItems;
        else if (isSoftware) itemsList = softwareItems;
        // Sorted once here (not inside the dropdown's per-click rebuild,
        // which jspreadsheet/jSuites always re-sorts internally regardless —
        // pre-sorting lets that repeated internal sort do less work).
        const itemNames = itemsList.map(i => i.name).sort((a, b) => a.localeCompare(b, 'th'));
        
        if (isEditMode) {
            btnEdit.innerHTML = '<i data-feather="x" class="me-1"></i> ยกเลิกการแก้ไข';
            btnEdit.classList.remove('btn-primary');
            btnEdit.classList.add('btn-outline-danger');
            btnAddRow.style.display = 'block';
            btnSave.style.display = 'inline-block';
            if (btnClose) btnClose.style.display = 'none';
            const btnCancel = document.getElementById('btnCancelDocument');
            if (btnCancel) btnCancel.style.display = 'none';

            buildCostCenterSelect('modalDocCostCenter', currentCostCenterName, (value) => { currentCostCenterName = value; });
            buildBranchSelect('modalDocBranch', currentBranchCode, (value) => { currentBranchCode = value; });

            // Re-create Table 1 for Edit
            let col0;
            if (isEquipment || isVet || isNonVet) {
                let datalistId = 'modal-equipment-item-datalist';
                if (isVet) datalistId = 'modal-vet-position-datalist';
                else if (isNonVet) datalistId = 'modal-non-vet-position-datalist';

                let itemDatalist = document.getElementById(datalistId);
                if (!itemDatalist) {
                    itemDatalist = document.createElement('datalist');
                    itemDatalist.id = datalistId;
                    document.body.appendChild(itemDatalist);
                }
                itemDatalist.innerHTML = '';
                itemNames.forEach(name => {
                    const opt = document.createElement('option');
                    opt.value = name;
                    itemDatalist.appendChild(opt);
                });
                const modalItemEditor = {
                    createCell: function(cell) {
                        cell.classList.add('eb-dropdown-cell');
                        return cell;
                    },
                    updateCell: function(cell, value) {
                        cell.classList.add('eb-dropdown-cell');
                        cell.innerText = value || '';
                        return value;
                    },
                    setValue: function(cell, value) {
                        cell.classList.add('eb-dropdown-cell');
                        cell.innerText = value || '';
                    },
                    openEditor: function(cell, el, empty) {
                        const rect = cell.getBoundingClientRect();
                        const input = document.createElement('input');
                        input.setAttribute('list', datalistId);
                        input.className = 'jexcel_editor eb-dropdown-input';
                        input.style.width = rect.width + 'px';
                        input.style.height = (rect.height - 2) + 'px';
                        input.style.minHeight = (rect.height - 2) + 'px';
                        input.style.boxSizing = 'border-box';
                        input.style.border = 'none';
                        input.style.outline = 'none';
                        input.style.padding = '0 4px';
                        input.style.font = 'inherit';
                        input.value = empty ? '' : (cell.innerText || '');
                        cell.classList.add('editor');
                        cell.innerHTML = '';
                        cell.appendChild(input);
                        input.focus();
                        try {
                            if (typeof input.showPicker === 'function') {
                                input.showPicker();
                            }
                        } catch (e) {}
                        input.onkeydown = function(e) {
                            if (e.which === 13 || e.key === 'Enter') {
                                if (modalTable1 && modalTable1.edition) modalTable1.closeEditor(cell, true);
                            } else if (e.which === 27 || e.key === 'Escape') {
                                if (modalTable1 && modalTable1.edition) modalTable1.closeEditor(cell, false);
                            }
                        };
                        input.onchange = function() {
                            if (modalTable1 && modalTable1.edition) modalTable1.closeEditor(cell, true);
                        };
                        input.onblur = function() {
                            if (modalTable1 && modalTable1.edition) modalTable1.closeEditor(cell, true);
                        };
                    },
                    closeEditor: function(cell) {
                        const input = cell.querySelector('input');
                        const val = (input ? input.value : (cell.innerText || '')).trim();
                        if (val !== '' && !itemsList.some(i => i.name === val)) {
                            const label = isEquipment ? 'รายการ' : 'ตำแหน่ง';
                            Swal.fire({
                                icon: 'warning',
                                title: 'แจ้งเตือน',
                                text: `ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือก${label}จากรายการ Dropdown เท่านั้น ("${val}" ไม่มีอยู่ในรายการตัวเลือก)`,
                                timer: 3000,
                                showConfirmButton: false,
                                toast: true,
                                position: 'top-end'
                            });
                            return '';
                        }
                        return val;
                    }
                };
                let colTitle = 'ตำแหน่ง';
                if (isCar) colTitle = 'รถยนต์';
                else if (isRenovate) colTitle = 'ปรับปรุง';
                else if (isSoftware) colTitle = 'Software';
                else if (isEquipment) colTitle = 'เครื่องมือ';

                col0 = { type: 'text', align: 'left', title: colTitle, width: 250, editor: modalItemEditor };
            } else {
                col0 = { type: 'dropdown', align: 'left', title: 'ตำแหน่ง', width: 250, source: itemNames, autocomplete: true };
            }
            let columns = [col0];
            if (isEquipment || isVet || isNonVet) {
                columns.push({ type: 'text', align: 'left', title: 'รายละเอียด', width: 200 });
            }
            columns.push({ type: 'numeric', title: isEquipment ? 'ราคาซื้อ' : 'เงินเดือน', width: 100, mask: '#,##0' });
            if (isNonVet) {
                columns.push({ type: 'numeric', title: 'ค่าวัดระดับ/ตำแหน่ง', width: 150, mask: '#,##0' });
            }
            const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
            months.forEach(m => {
                columns.push({ type: 'numeric', title: m, width: 85, readOnly: false, mask: '#,##0' });
            });
            columns.push({ type: 'numeric', title: 'รวม', width: 100, readOnly: true, mask: '#,##0' });
            
            const currentData = modalTable1.getData();
            modalTable1.destroy();
            
            modalTable1 = jspreadsheet(document.getElementById('modalSpreadsheet1'), {
                data: currentData,
                columns: columns,
                allowInsertRow: true,
                allowDeleteRow: true,
                allowInsertColumn: false,
                allowManualInsertColumn: false,
                allowDeleteColumn: false,
                tableOverflow: true,
                onchange: onSpreadsheetChange,
                onselection: function(el, x1, y1, x2, y2, origin) {
                    const sheet = (el && el.jexcel) || modalTable1;
                    if (!sheet || typeof sheet.getCellFromCoords !== 'function') return;
                    if (x1 === 0 && x2 === 0 && y1 === y2) {
                        const cell = sheet.getCellFromCoords(0, y1);
                        if (cell && !sheet.edition) {
                            sheet.openEditor(cell, false);
                        }
                    }
                },
                contextMenu: function() { return true; },
                // modalTable1 can gain a row through more than just the
                // "เพิ่มรายการ" button — e.g. pressing Enter on its last row —
                // and modalTable2 must always mirror it row-for-row or
                // onSpreadsheetChange's cross-table writes land on a row that
                // doesn't exist yet and throw, wedging isUpdating stuck true.
                oninsertrow: function(el, rowNumber, numOfRows, rowRecords, insertBefore) {
                    if (modalTable2) modalTable2.insertRow(numOfRows, rowNumber, insertBefore);
                },
                // Mirrors modalTable1's own deletion (e.g. via its
                // right-click context menu, enabled above) into
                // modalTable2 — same reasoning as oninsertrow: without
                // this, table2's row count drifts out of sync with
                // table1's and onSpreadsheetChange's per-row cross-writes
                // land on the wrong row.
                ondeleterow: function(el, rowNumber, numOfRows) {
                    if (modalTable2) modalTable2.deleteRow(rowNumber, numOfRows);
                },
            });

            // modalTable2 was still stuck with allowInsertRow/allowDeleteRow
            // false from viewDocumentDetails' read-only init — jexcel's
            // insertRow()/deleteRow() are guarded no-ops (even called
            // programmatically) when those flags are false, so
            // modalTable1's oninsertrow hook above was silently failing to
            // mirror new rows into table2. Rebuild table2 the same way as
            // table1, reusing the identical `columns` shape (view-mode init
            // already uses the same columns array for both tables — see
            // viewDocumentDetails).
            const currentData2 = modalTable2.getData();
            modalTable2.destroy();

            modalTable2 = jspreadsheet(document.getElementById('modalSpreadsheet2'), {
                data: currentData2,
                columns: columns,
                allowInsertRow: true,
                allowDeleteRow: true,
                allowInsertColumn: false,
                allowManualInsertColumn: false,
                allowDeleteColumn: false,
                tableOverflow: true,
                // Still no direct editing of table2 itself — it must stay
                // driven by table1 (via onSpreadsheetChange and the
                // insert/delete mirrors above) to keep their rows 1:1.
                contextMenu: function() { return false; },
            });

            // Brief highlight so switching into edit mode reads as a
            // deliberate state change, not a silent DOM swap.
            const sheetContainer = document.getElementById('modalSpreadsheet1');
            sheetContainer.classList.remove('eb-edit-flash');
            void sheetContainer.offsetWidth;
            sheetContainer.classList.add('eb-edit-flash');

        } else {
            // Cancel Edit -> Reload document details
            viewDocumentDetails(currentDocNo, currentDocType);
        }
        if (typeof feather !== 'undefined') feather.replace();
    }

    function addSpreadsheetRow() {
        // modalTable1's oninsertrow hook mirrors this into modalTable2, so
        // it isn't done here too (that would double-insert).
        if (isEditMode && modalTable1 && modalTable2) {
            modalTable1.insertRow();
        }
    }

    function saveDocument() {
        if (!modalTable1 || !isEditMode) return;
        if (modalTable1.edition) {
            modalTable1.closeEditor(modalTable1.edition[0], true);
        }

        const costCenterName = currentCostCenterName;
        if (!costCenterName) {
            Swal.fire('แจ้งเตือน', 'กรุณาเลือก Cost Center', 'warning');
            return;
        }
        const branchCode = currentBranchCode;

        const isNonVet = currentDocType === 'NON VET';
        const isMed = currentDocType === 'Medical Equipment';
        const isComp = currentDocType === 'Computer Equipment';
        const isFurniture = currentDocType === 'Furniture';
        const isTools = currentDocType === 'Tools & Equipment';
        const isCar = currentDocType === 'CAR';
        const isRenovate = currentDocType === 'Renovate';
        const isSoftware = currentDocType === 'Software';
        const isEquipment = isMed || isComp || isFurniture || isTools || isCar || isRenovate || isSoftware;
        const isVet = currentDocType === 'VET';
        const hasDetailCol = isEquipment || isVet || isNonVet;
        const priceCol = hasDetailCol ? 2 : 1;
        const allowanceCol = priceCol + 1; // only meaningful when isNonVet
        const startCol = priceCol + 1 + (isNonVet ? 1 : 0);

        let itemsList = vetItems;
        if (isNonVet) itemsList = nonVetItems;
        else if (isMed) itemsList = medItems;
        else if (isComp) itemsList = compItems;
        else if (isFurniture) itemsList = furnitureItems;
        else if (isTools) itemsList = toolsItems;
        else if (isCar) itemsList = carItems;
        else if (isRenovate) itemsList = renovateItems;
        else if (isSoftware) itemsList = softwareItems;

        let rows = modalTable1.getData();
        let dataToSave = [];

        for (let i = 0; i < rows.length; i++) {
            let row = rows[i];
            let position = (row[0] || '').trim();
            let description = hasDetailCol ? row[1] : undefined;
            let salary = getNum(row[priceCol]);
            let allowance = isNonVet ? getNum(row[allowanceCol]) : 0;

            if (position) {
                if (isEquipment || isVet || isNonVet) {
                    const isItemInMaster = itemsList.some(it => it.name === position);
                    if (!isItemInMaster) {
                        const label = isEquipment ? 'รายการ' : 'ตำแหน่ง';
                        Swal.fire('แจ้งเตือน', `ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือก${label}จากรายการ Dropdown เท่านั้น\n(แถวที่ ${i + 1}: "${position}" ไม่มีอยู่ในรายการตัวเลือก)`, 'warning');
                        return;
                    }
                }

                if (isEquipment && salary <= 0) {
                    Swal.fire('แจ้งเตือน', `กรุณาระบุราคาซื้อสำหรับ "${position}" (แถวที่ ${i + 1})`, 'warning');
                    return;
                }
                if (isEquipment && salary < 5000) {
                    Swal.fire('แจ้งเตือน', `ราคาซื้อในหมวดสินทรัพย์ถาวร (Fix Asset) ต้องมีมูลค่าตั้งแต่ 5,000 บาทขึ้นไป กรุณาตรวจสอบราคาสำหรับ "${position}" (แถวที่ ${i + 1})`, 'warning');
                    return;
                }
                if (!isEquipment && salary <= 0 && allowance <= 0) {
                    continue;
                }
                const monthKeys = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
                const monthCounts = [];
                for (let c = startCol; c <= startCol + 11; c++) monthCounts.push(getNum(row[c]));

                const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
                for (let c = 0; c < 12; c++) {
                    const cellVal = row[startCol + c];
                    const rawStr = String(cellVal !== null && cellVal !== undefined ? cellVal : '').trim().replace(/,/g, '');
                    if (rawStr !== '' && /^0\d+/.test(rawStr)) {
                        Swal.fire('แจ้งเตือน', `จำนวนในเดือน ${monthNames[c]} ไม่อนุญาตให้กรอกรูปแบบที่มีเลข 0 นำหน้า เช่น "${rawStr}" (แถวที่ ${i + 1}: ${position}) กรุณาระบุเป็นตัวเลขจำนวนเต็มปกติ`, 'warning');
                        return;
                    }
                    if (monthCounts[c] % 1 !== 0 || monthCounts[c] < 0) {
                        Swal.fire('แจ้งเตือน', `จำนวนในเดือน ${monthNames[c]} ต้องเป็นตัวเลขจำนวนเต็มเท่านั้น ไม่อนุญาตให้กรอกเลขทศนิยม (แถวที่ ${i + 1}: ${position})`, 'warning');
                        return;
                    }
                }

                // Cost must match whatever modalTable2 showed the user before
                // they hit Save — equipment is a flat one-off purchase per
                // month, but VET/NON VET accumulate ("ขั้นบันได") via the same
                // computeMonthlyBudget() the create/edit-preview paths use.
                // (Previously this recomputed cost as a flat count*rate here
                // regardless of type, silently saving the wrong — non-cumulative
                // — numbers for VET/NON VET even though the on-screen preview
                // was correct.)
                let monthlyData = {};
                if (isEquipment) {
                    monthKeys.forEach((key, idx) => {
                        monthlyData[key] = { headcount: monthCounts[idx], cost: monthCounts[idx] * salary };
                    });
                } else {
                    const monthlyBudget = computeMonthlyBudget(monthCounts, salary + allowance);
                    monthKeys.forEach((key, idx) => {
                        monthlyData[key] = { headcount: monthCounts[idx], cost: monthlyBudget[idx].cost };
                    });
                }

                let rowData = {};
                if (isEquipment) {
                    rowData = {
                        'item_name': position,
                        'description': description,
                        'purchase_price': salary,
                        'cost_center_name': costCenterName,
                        'branch_code': branchCode,
                        'monthly_data': monthlyData
                    };
                } else {
                    rowData = {
                        'position_name': position,
                        'salary': salary,
                        'cost_center_name': costCenterName,
                        'branch_code': branchCode,
                        'monthly_data': monthlyData
                    };
                    if (isNonVet) {
                        rowData['position_allowance'] = allowance;
                    }
                    if (isVet || isNonVet) {
                        rowData['description'] = description;
                    }
                }
                dataToSave.push(rowData);
            }
        }
        
        if (dataToSave.length === 0) {
            Swal.fire('แจ้งเตือน', 'กรุณาระบุข้อมูลอย่างน้อย 1 ตำแหน่ง', 'warning');
            return;
        }
        
        Swal.fire({
            title: 'ยืนยันการอัปเดตข้อมูล?',
            text: "คุณตรวจสอบข้อมูลครบถ้วนและต้องการบันทึกการแก้ไขใช่หรือไม่?",
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#0061f2',
            cancelButtonColor: '#e81500',
            confirmButtonText: 'บันทึก',
            cancelButtonText: 'ยกเลิก'
        }).then((result) => {
            if (result.isConfirmed) {
                Swal.fire({ title: 'กำลังบันทึกข้อมูล...', allowOutsideClick: false, didOpen: () => { Swal.showLoading(); }});
                
                const urlTemplate = window.APP_CONFIG.urls.apiDocumentUpdate;
                const url = urlTemplate.replace('TYPE', encodeURIComponent(currentDocType)).replace('DOCNO', encodeURIComponent(currentDocNo));
                
                fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': window.APP_CONFIG.csrfToken
                    },
                    body: JSON.stringify(dataToSave)
                })
                .then(handleApiResponse)
                .then(data => {
                    if (data.status === 'success') {
                        updateListRowTotalBudget(currentDocNo, sumMonthlyDataTotal(dataToSave, 'cost'));
                        Swal.fire('สำเร็จ!', 'อัปเดตข้อมูลเรียบร้อยแล้ว', 'success').then(() => {
                            viewDocumentDetails(currentDocNo, currentDocType);
                        });
                    } else {
                        Swal.fire('ข้อผิดพลาด', 'ไม่สามารถบันทึกได้: ' + data.message, 'error');
                    }
                })
                .catch(error => {
                    if (error.message === SESSION_EXPIRED) return;
                    console.error(error);
                    Swal.fire('ข้อผิดพลาด', 'เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error');
                });
            }
        });
    }

    function approveDocument() {
        Swal.fire({
            title: 'ยืนยันการอนุมัติเอกสาร?',
            text: 'เอกสารนี้จะถูกล็อกและไม่สามารถแก้ไขได้อีกหลังจากอนุมัติ',
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: '#28a745',
            cancelButtonColor: '#6c757d',
            confirmButtonText: 'อนุมัติ',
            cancelButtonText: 'ยกเลิก'
        }).then((result) => {
            if (!result.isConfirmed) return;
            Swal.fire({ title: 'กำลังบันทึกข้อมูล...', allowOutsideClick: false, didOpen: () => { Swal.showLoading(); }});

            const urlTemplate = window.APP_CONFIG.urls.apiDocumentApprove;
            const url = urlTemplate.replace('TYPE', encodeURIComponent(currentDocType)).replace('DOCNO', encodeURIComponent(currentDocNo));

            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.APP_CONFIG.csrfToken },
                body: JSON.stringify({})
            })
            .then(handleApiResponse)
            .then(data => {
                if (data.status === 'success') {
                    updateListRowStatus(currentDocNo, 'APPROVED');
                    Swal.fire('สำเร็จ!', 'อนุมัติเอกสารเรียบร้อยแล้ว', 'success').then(() => {
                        viewDocumentDetails(currentDocNo, currentDocType);
                    });
                } else {
                    Swal.fire('ข้อผิดพลาด', 'ไม่สามารถอนุมัติได้: ' + data.message, 'error');
                }
            })
            .catch(error => {
                if (error.message === SESSION_EXPIRED) return;
                console.error(error);
                Swal.fire('ข้อผิดพลาด', 'เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error');
            });
        });
    }

    function cancelDocument() {
        Swal.fire({
            title: 'ยืนยันการยกเลิกรายการ?',
            input: 'textarea',
            inputLabel: 'เหตุผลการยกเลิก',
            inputPlaceholder: 'กรุณาระบุเหตุผล...',
            inputValidator: (value) => (!value || !value.trim()) ? 'กรุณาระบุเหตุผลการยกเลิก' : undefined,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#dc3545',
            cancelButtonColor: '#6c757d',
            confirmButtonText: 'ยกเลิกรายการ',
            cancelButtonText: 'ปิด',
            // Bootstrap's modal focus trap keeps yanking focus back into
            // #documentDetailModal (still open underneath) since Swal mounts
            // its popup on document.body, outside that modal's DOM subtree —
            // without this, the textarea below is completely untypable.
            didOpen: () => { detailModalInstance?._focustrap?.deactivate?.(); },
            didClose: () => { detailModalInstance?._focustrap?.activate?.(); },
        }).then((result) => {
            if (!result.isConfirmed) return;
            Swal.fire({ title: 'กำลังบันทึกข้อมูล...', allowOutsideClick: false, didOpen: () => { Swal.showLoading(); }});

            const urlTemplate = window.APP_CONFIG.urls.apiDocumentCancel;
            const url = urlTemplate.replace('TYPE', encodeURIComponent(currentDocType)).replace('DOCNO', encodeURIComponent(currentDocNo));

            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.APP_CONFIG.csrfToken },
                body: JSON.stringify({ cancel_reason: result.value.trim() })
            })
            .then(handleApiResponse)
            .then(data => {
                if (data.status === 'success') {
                    updateListRowStatus(currentDocNo, 'CANCELLED');
                    Swal.fire('สำเร็จ!', 'ยกเลิกรายการเรียบร้อยแล้ว', 'success').then(() => {
                        viewDocumentDetails(currentDocNo, currentDocType);
                    });
                } else {
                    Swal.fire('ข้อผิดพลาด', 'ไม่สามารถยกเลิกได้: ' + data.message, 'error');
                }
            })
            .catch(error => {
                if (error.message === SESSION_EXPIRED) return;
                console.error(error);
                Swal.fire('ข้อผิดพลาด', 'เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error');
            });
        });
    }

    // ==========================================
    // JS Logic for General Ledger Document Detail Modal (GL Entry / Budget Plan)
    // ==========================================
    // Renders via jspreadsheet with freezeColumns (same library/technique as
    // budget_add_gl_entry.html/budget_add_budget_plan.html and every other
    // detail modal on this page) — a plain HTML table with hand-rolled CSS
    // sticky columns was tried first but proved unreliable (ghosting/overlap
    // while scrolling); freezeColumns renders frozen columns as a genuinely
    // separate panel, not CSS position:sticky. View mode uses readOnly
    // columns; edit mode (gated by is_privileged_user, same as every other
    // modal here) swaps in editable/dropdown columns and an onchange total
    // recompute, mirroring toggleAdjEditMode's destroy-and-rebuild pattern.

    const monthTitlesShort = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const monthKeysShort = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
    let isGlDetailUpdating = false;

    function sumMonthlyData(monthlyData) {
        return monthKeysShort.reduce((total, key) => total + getNum((monthlyData[key] || {}).amount), 0);
    }

    // Mirrors budget_add_budget_plan.html's 4 sections exactly (same order as
    // ebudget_budget_plan_item.BUDGET_CATEGORY_CHOICES) — the add page splits
    // Budget Plan documents into 4 tables by category, so the view here does
    // the same instead of one combined table with a "หมวด" column.
    const BUDGET_PLAN_SECTIONS = [
        { category: 'EXTRA_REVENUE', columnLabel: '3. รายได้เพิ่ม ที่ไม่ใช่จากการขายปกติ (ค่าสนับสนุน commission ส่วนแบ่ง)', heading: 'รายได้เพิ่ม ที่ไม่ใช่จากการขายปกติ (ค่าสนับสนุน commission ส่วนแบ่ง)' },
        { category: 'ACTIVITY', columnLabel: '3. กิจกรรมที่จะทำ (ทั้งหมด ทั้งที่เคยทำและจะทำเพิ่ม)', heading: 'กิจกรรมที่จะทำ (ทั้งหมด ทั้งที่เคยทำและจะทำเพิ่ม)' },
        { category: 'PERSONNEL', columnLabel: '3. ค่าจ้างบุคคลากร (เพิ่ม)', heading: 'ค่าจ้างบุคคลากร (เพิ่ม)' },
        { category: 'ASSET', columnLabel: '3. ทรัพย์สินย์และ Software (>5,000 บาท)', heading: 'ทรัพย์สินย์และ Software (>5,000 บาท)' },
    ];

    function glCommonTableOptions(editable) {
        return {
            tableOverflow: true,
            allowInsertRow: editable,
            allowDeleteRow: editable,
            allowInsertColumn: false,
            allowDeleteColumn: false,
            allowManualInsertColumn: false,
            columnDrag: false,
            contextMenu: function() { return editable; },
        };
    }

    // "รวม" = SUM(Jan:Dec) for the row, recomputed live in edit mode — same
    // guarded-onchange pattern as budget_add_budget_plan.html.
    function makeGlOnchange(getTable, monthStartCol, totalCol) {
        return function() {
            const table = getTable();
            if (!table || isGlDetailUpdating) return;
            isGlDetailUpdating = true;
            for (let y = 0; y < table.getData().length; y++) {
                const rowData = table.getRowData(y);
                let total = 0;
                for (let m = 0; m < 12; m++) total += getNum(rowData[monthStartCol + m]);
                table.setValueFromCoords(totalCol, y, total, true);
            }
            isGlDetailUpdating = false;
        };
    }

    function ensureModalGlDatalist() {
        let dl = document.getElementById('modal-gl-item-datalist');
        if (!dl) {
            dl = document.createElement('datalist');
            dl.id = 'modal-gl-item-datalist';
            document.body.appendChild(dl);
        }
        dl.innerHTML = '';
        glNames.forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            dl.appendChild(opt);
        });
        return dl;
    }

    const modalGlEditor = {
        createCell: function(cell) {
            cell.classList.add('eb-dropdown-cell');
            return cell;
        },
        updateCell: function(cell, value) {
            cell.classList.add('eb-dropdown-cell');
            cell.innerText = value || '';
            return value;
        },
        setValue: function(cell, value) {
            cell.classList.add('eb-dropdown-cell');
            cell.innerText = value || '';
        },
        openEditor: function(cell, el, empty) {
            ensureModalGlDatalist();
            const rect = cell.getBoundingClientRect();
            const input = document.createElement('input');
            input.setAttribute('list', 'modal-gl-item-datalist');
            input.className = 'jexcel_editor eb-dropdown-input';
            input.style.width = rect.width + 'px';
            input.style.height = (rect.height - 2) + 'px';
            input.style.minHeight = (rect.height - 2) + 'px';
            input.style.boxSizing = 'border-box';
            input.style.border = 'none';
            input.style.outline = 'none';
            input.style.padding = '0 4px';
            input.style.font = 'inherit';
            input.value = empty ? '' : (cell.innerText || '');
            cell.classList.add('editor');
            cell.innerHTML = '';
            cell.appendChild(input);
            input.focus();
            try {
                if (typeof input.showPicker === 'function') {
                    input.showPicker();
                }
            } catch (e) {}
            input.onkeydown = function(e) {
                if (e.which === 13) {
                    if (glDetailTables[0] && glDetailTables[0].edition) glDetailTables[0].closeEditor(cell, true);
                } else if (e.which === 27) {
                    if (glDetailTables[0] && glDetailTables[0].edition) glDetailTables[0].closeEditor(cell, false);
                }
            };
            input.onblur = function() {
                if (glDetailTables[0] && glDetailTables[0].edition) glDetailTables[0].closeEditor(cell, true);
            };
        },
        closeEditor: function(cell) {
            const input = cell.querySelector('input');
            const val = input ? input.value.trim() : (cell.innerText || '').trim();
            if (!val) return '';
            const match = generalLedgers.find(g => g.gl_name === val);
            if (match) return match.gl_name;
            const ciMatch = generalLedgers.find(g => g.gl_name.toLowerCase() === val.toLowerCase());
            if (ciMatch) return ciMatch.gl_name;
            if (typeof Swal !== 'undefined') {
                Swal.fire({
                    toast: true,
                    position: 'top-end',
                    icon: 'warning',
                    title: 'กรุณาเลือกรายการ GL จาก Master ที่กำหนดเท่านั้น',
                    showConfirmButton: false,
                    timer: 2500
                });
            }
            return '';
        }
    };

    function glEntryColumns(editable) {
        const monthColumns = monthTitlesShort.map(m => ({ type: 'numeric', title: m, width: 100, readOnly: !editable, mask: '#,##0' }));
        return [
            editable
                ? { type: 'text', align: 'left', title: 'GL', width: 220, editor: modalGlEditor }
                : { type: 'text', align: 'left', title: 'GL', width: 220, readOnly: true },
            { type: 'text', align: 'left', title: 'รายละเอียด', width: 150, readOnly: !editable },
            ...monthColumns,
            { type: 'numeric', title: 'รวม', width: 110, readOnly: true, mask: '#,##0' },
        ];
    }

    function glEntryRowData(item) {
        const monthValues = monthKeysShort.map(key => getNum((item.monthly_data[key] || {}).amount));
        const total = sumMonthlyData(item.monthly_data);
        const glName = item.general_ledger_name && item.general_ledger_name !== '-' ? item.general_ledger_name : '';
        return [glName, item.detail_note || '', ...monthValues, total];
    }

    // ยอดรวมแต่ละเดือน (column sum ข้ามทุกแถว) สำหรับ popup รายละเอียดเอกสาร
    // EXPENSE/Revenue (table shape เดียวกัน, ดู docType !== 'Budget Plan'
    // ใน renderGlDetailSpreadsheet) — มิเรอร์ updateMonthlyTotals()/injection
    // logic ของ budget_add_revenue.html/budget_add_gl_entry.html ทุกประการ
    // (แถวนอก jexcel data model, ไม่หลุดเข้า getData()/saveGlDocument() เลย)
    // ต่างแค่ต้อง inject ใหม่ทุกครั้งที่ renderGlDetailSpreadsheet() ถูกเรียก
    // เพราะตารางนี้ destroy+rebuild ทั้งก้อนทุกครั้ง (เปิดดูครั้งแรก และตอน
    // เข้า/ออก edit mode)
    function injectGlEntryMonthlyTotalsRow(mountEl, columns) {
        const theadEl = mountEl.querySelector('table.jexcel thead');
        if (!theadEl) return;
        const headerRow = theadEl.querySelector('tr');
        if (!headerRow) return;
        const headerCells = Array.from(headerRow.children);

        // หัวคอลัมน์จริงของตารางนี้ไม่เคย sticky มาก่อน (ต่างจากหน้า Add
        // Revenue ที่ thead sticky เป็นทุนเดิม) — set ตรงๆ ผ่าน inline style
        // เฉพาะ table instance นี้ ไม่ใช้ CSS selector กว้างๆ ที่จะกระทบ
        // ตาราง GL Entry/Budget Plan ซึ่งใช้ modal เดียวกัน
        headerCells.forEach(td => {
            td.style.position = 'sticky';
            td.style.top = '0';
            td.style.zIndex = '2';
            td.style.backgroundColor = '#f5f5f5';
        });

        const totalsRow = document.createElement('tr');
        totalsRow.className = 'monthly-totals-row';

        // คอลัมน์เลขแถว (corner, headerCells[0]) ไม่ได้ freeze จริงใน jexcel
        // เอง (updateFreezePosition ตั้ง left ให้แค่ obj.headers[t],
        // t=0..freezeColumns-1 ซึ่งคือ GL/รายละเอียด ไม่รวม corner) — เลื่อน
        // หายไปตามปกติเหมือนเนื้อหาอื่น จึงไม่ set left ให้ cell นี้เช่นกัน
        const cornerTd = document.createElement('td');
        cornerTd.style.top = `${headerRow.offsetHeight}px`;
        totalsRow.appendChild(cornerTd);

        // GL/รายละเอียด แต่ละตัว sticky left ของตัวเอง (0px / ความกว้าง GL)
        // ตรงกับที่ updateFreezePosition ตั้งให้ obj.headers[0]/[1] จริง —
        // ใช้ 2 cell เดี่ยวแทน cell เดียว colspan=2 เพราะ position:sticky
        // บน <td colspan> มีพฤติกรรมไม่แน่นอนข้าม browser (sticky containing
        // block คำนวณผิด ทำให้ตำแหน่งเพี้ยนและซ้อนทับแถวข้อมูลด้านล่าง) ส่วน
        // เซลล์หัวคอลัมน์จริงของ jexcel เป็น <td> เดี่ยวไม่มี colspan เลย —
        // ความกว้างใช้ค่าจาก columns config ตรงๆ (source of truth เดียวกับ
        // ที่ jexcel เองใช้คำนวณ freeze) ไม่พึ่ง DOM measurement
        const glSumTd = document.createElement('td');
        glSumTd.textContent = 'ยอดรวมแต่ละเดือน';
        glSumTd.classList.add('monthly-totals-label');
        glSumTd.style.left = '0px';
        glSumTd.style.top = `${headerRow.offsetHeight}px`;
        totalsRow.appendChild(glSumTd);

        const detailSumTd = document.createElement('td');
        detailSumTd.classList.add('monthly-totals-label');
        detailSumTd.style.left = `${columns[0].width}px`;
        detailSumTd.style.top = `${headerRow.offsetHeight}px`;
        totalsRow.appendChild(detailSumTd);

        for (let m = 0; m < 12; m++) {
            const td = document.createElement('td');
            td.id = `glEntryMonthlyTotal-${m}`;
            td.textContent = '0';
            td.style.top = `${headerRow.offsetHeight}px`;
            totalsRow.appendChild(td);
        }

        const totalTd = document.createElement('td'); // คอลัมน์ "รวม" — ยอดรวมทั้งหมดของทุกเดือน
        totalTd.id = 'glEntryMonthlyTotal-grand';
        totalTd.textContent = '0';
        totalTd.style.top = `${headerRow.offsetHeight}px`;
        totalsRow.appendChild(totalTd);

        theadEl.appendChild(totalsRow);
    }

    function updateGlEntryMonthlyTotals() {
        const table = glDetailTables[0];
        if (!table) return;
        const rows = table.getData();
        let grandTotal = 0;
        for (let m = 0; m < 12; m++) {
            let sum = 0;
            for (let i = 0; i < rows.length; i++) sum += getNum(rows[i][2 + m]);
            const cell = document.getElementById(`glEntryMonthlyTotal-${m}`);
            if (cell) cell.textContent = sum.toLocaleString('en-US', { maximumFractionDigits: 2 });
            grandTotal += sum;
        }
        const grandCell = document.getElementById('glEntryMonthlyTotal-grand');
        if (grandCell) grandCell.textContent = grandTotal.toLocaleString('en-US', { maximumFractionDigits: 2 });
    }

    function buildBudgetPlanViewColumns(columnLabel, editable) {
        const monthColumns = monthTitlesShort.map(m => ({ type: 'numeric', title: m, width: 100, readOnly: !editable, mask: '#,##0' }));
        return [
            editable
                ? { type: 'dropdown', align: 'left', title: '1. การลงงบ', width: 220, source: glNames, autocomplete: true }
                : { type: 'text', align: 'left', title: '1. การลงงบ', width: 220, readOnly: true },
            { type: 'text', align: 'left', title: '#', width: 90, readOnly: !editable },
            { type: 'text', align: 'left', title: columnLabel, width: 260, readOnly: !editable },
            ...monthColumns,
            { type: 'numeric', title: 'รวม', width: 110, readOnly: true, mask: '#,##0' },
        ];
    }

    function budgetPlanRowData(item) {
        const monthValues = monthKeysShort.map(key => getNum((item.monthly_data[key] || {}).amount));
        const total = sumMonthlyData(item.monthly_data);
        const glName = item.general_ledger_name && item.general_ledger_name !== '-' ? item.general_ledger_name : '';
        const itemCode = item.item_code && item.item_code !== '-' ? item.item_code : '';
        const description = item.description && item.description !== '-' ? item.description : '';
        return [glName, itemCode, description, ...monthValues, total];
    }

    // Converts a jspreadsheet row already on screen back into the API's item
    // shape, so entering edit mode can reuse renderGlDetailSpreadsheet against
    // the data already loaded instead of an extra round trip to the server.
    function glEntryGridRowToItem(row) {
        const monthly_data = {};
        monthKeysShort.forEach((key, m) => { monthly_data[key] = { amount: row[2 + m] }; });
        return { general_ledger_name: row[0], detail_note: row[1], monthly_data };
    }

    function budgetPlanGridRowToItem(row, category) {
        const monthly_data = {};
        monthKeysShort.forEach((key, m) => { monthly_data[key] = { amount: row[3 + m] }; });
        return { budget_category: category, general_ledger_name: row[0], item_code: row[1], description: row[2], monthly_data };
    }

    function addGlRowButton(table) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-sm btn-primary';
        btn.innerHTML = '<i data-feather="plus" class="me-1"></i>เพิ่มรายการ';
        btn.addEventListener('click', () => table.insertRow());
        return btn;
    }

    function addGlSpreadsheetRow() {
        // GL Entry's own "เพิ่มรายการ" button lives in the card-header next
        // to the table (see #btnGlAddRow in budget_list.html), same fixed
        // position as VET's #btnAddRow — unlike Budget Plan's per-section
        // add buttons below, which addGlRowButton still builds dynamically
        // since each section needs its own.
        if (isGlEditMode && glDetailTables[0]) {
            glDetailTables[0].insertRow();
        }
    }

    function renderGlDetailSpreadsheet(docType, items, editable) {
        const container = document.getElementById('glDetailTableContainer');
        container.dataset.docType = docType;

        glDetailTables.forEach(table => table && table.destroy());
        glDetailTables = [];
        container.innerHTML = '';

        if ((!items || items.length === 0) && !editable) {
            container.innerHTML = '<p class="text-muted text-center py-4 mb-0">ไม่มีรายการ</p>';
            return;
        }

        // Revenue/EXPENSE share GL Entry's exact table shape — only Budget
        // Plan's 3-section layout differs. Monthly-totals row applies to
        // both (ยอดรวมแต่ละเดือน requested for EXPENSE's Budget List popup
        // to match Revenue's, already shipped in an earlier round).
        if (docType !== 'Budget Plan') {
            const columns = glEntryColumns(editable);
            const data = (items && items.length > 0) ? items.map(glEntryRowData) : [Array(columns.length).fill('')];

            const mountEl = document.createElement('div');
            mountEl.className = 'gl-single-table-mount';
            container.appendChild(mountEl);

            // คง onchange เดิม (คำนวณ "รวม" ต่อแถว ตอน editable) ไว้ครบ แค่
            // compose เรียก updateGlEntryMonthlyTotals() ต่อท้าย — view mode
            // ไม่มี onchange เดิมอยู่แล้วจึงแค่ใส่ของเราเข้าไป. oninsertrow/
            // ondeleterow ไม่เคยมีมาก่อนในตารางนี้เลย (ไม่เคยต้องคำนวณอะไร
            // ตอนแถวเปลี่ยนจำนวน) เพิ่มใหม่เฉพาะที่นี่.
            const extraOptions = editable ? {
                minDimensions: [columns.length, 1],
                onchange: makeGlOnchange(() => glDetailTables[0], 2, 14),
                onselection: function(el, x1, y1, x2, y2, origin) {
                    const sheet = (el && el.jexcel) || (glDetailTables && glDetailTables[0]);
                    if (!sheet || typeof sheet.getCellFromCoords !== 'function') return;
                    if (x1 === 0 && x2 === 0 && y1 === y2) {
                        const cell = sheet.getCellFromCoords(0, y1);
                        if (cell && !sheet.edition) {
                            sheet.openEditor(cell, false);
                        }
                    }
                }
            } : {};
            const baseOnchange = extraOptions.onchange;
            extraOptions.onchange = baseOnchange
                ? function() { baseOnchange(); updateGlEntryMonthlyTotals(); }
                : updateGlEntryMonthlyTotals;
            extraOptions.oninsertrow = updateGlEntryMonthlyTotals;
            extraOptions.ondeleterow = updateGlEntryMonthlyTotals;

            const table = jspreadsheet(mountEl, Object.assign({}, glCommonTableOptions(editable), {
                data: data,
                columns: columns,
                tableHeight: '100%',
                freezeColumns: 2,
            }, extraOptions));
            glDetailTables[0] = table;

            injectGlEntryMonthlyTotalsRow(mountEl, columns);
            updateGlEntryMonthlyTotals();

            // Fixed-position button in the card-header (#btnGlAddRow) —
            // matches every other add-budget table's "เพิ่มรายการ" button
            // placement instead of floating one above the grid each render.
            const btnGlAddRow = document.getElementById('btnGlAddRow');
            if (btnGlAddRow) btnGlAddRow.style.display = editable ? 'inline-block' : 'none';
            if (editable && typeof feather !== 'undefined') feather.replace();
            return;
        }

        // Budget Plan: one table per category, same as the add page. Every
        // section always shows its heading (even with zero items) — only
        // whether a table gets mounted for it differs by mode.
        BUDGET_PLAN_SECTIONS.forEach((section, idx) => {
            const sectionItems = (items || []).filter(item => item.budget_category === section.category);

            const sectionEl = document.createElement('div');
            sectionEl.className = idx > 0 ? 'mt-4' : '';
            const headerEl = document.createElement('div');
            headerEl.className = 'd-flex justify-content-between align-items-center mb-2';
            headerEl.innerHTML = `<h6 class="text-primary mb-0">${section.heading}</h6>`;
            const mountEl = document.createElement('div');
            sectionEl.appendChild(headerEl);
            sectionEl.appendChild(mountEl);
            container.appendChild(sectionEl);

            if (sectionItems.length === 0 && !editable) {
                mountEl.innerHTML = '<p class="text-muted small mb-0">ไม่มีรายการ</p>';
                glDetailTables[idx] = null;
                return;
            }

            const columns = buildBudgetPlanViewColumns(section.columnLabel, editable);
            const data = sectionItems.length > 0 ? sectionItems.map(budgetPlanRowData) : [Array(columns.length).fill('')];

            const extraOptions = editable ? { minDimensions: [columns.length, 1], onchange: makeGlOnchange(() => glDetailTables[idx], 3, 15) } : {};
            const table = jspreadsheet(mountEl, Object.assign({}, glCommonTableOptions(editable), {
                data: data,
                columns: columns,
                freezeColumns: 3,
            }, extraOptions));
            glDetailTables[idx] = table;

            if (editable) {
                headerEl.appendChild(addGlRowButton(table));
            }
        });

        if (editable && typeof feather !== 'undefined') feather.replace();
    }

    function resetGlEditButtons() {
        const btnGlEdit = document.getElementById('btnGlEditMode');
        if (btnGlEdit) {
            btnGlEdit.innerHTML = '<i data-feather="edit-2" class="me-1"></i> แก้ไขข้อมูล';
            btnGlEdit.classList.remove('btn-outline-danger');
            btnGlEdit.classList.add('btn-primary');
        }
        const btnGlSave = document.getElementById('btnGlSaveDocument');
        if (btnGlSave) btnGlSave.style.display = 'none';
        const btnGlClose = document.getElementById('btnGlCloseModal');
        if (btnGlClose) btnGlClose.style.display = 'inline-block';
        const btnGlAddRow = document.getElementById('btnGlAddRow');
        if (btnGlAddRow) btnGlAddRow.style.display = 'none';
    }

    function viewGeneralLedgerDocumentDetails(docNo, docType) {
        currentGlDocNo = docNo;
        currentGlDocType = docType;
        isGlEditMode = false;
        resetGlEditButtons();

        const glModalEl = document.getElementById('glDocumentDetailModal');
        if (!glModalInstance) {
            glModalInstance = new bootstrap.Modal(glModalEl);
        }
        const glShownPromise = waitForModalShown(glModalEl);
        glModalInstance.show();

        document.getElementById('glModalContent').style.display = 'none';
        document.getElementById('glModalLoadingSpinner').style.display = 'block';

        const urlTemplate = window.APP_CONFIG.urls.apiDocumentDetail;
        const url = urlTemplate.replace('TYPE', encodeURIComponent(docType)).replace('DOCNO', encodeURIComponent(docNo));

        Promise.all([fetch(url).then(handleApiResponse), glShownPromise])
            .then(([result]) => {
                document.getElementById('glModalLoadingSpinner').style.display = 'none';

                if (result.status === 'success') {
                    document.getElementById('glModalDocNo').innerText = result.doc_info.document_no;
                    document.getElementById('glModalDocType').innerHTML = result.doc_info.type === 'GL Entry' ?
                        '<span class="badge" style="background-color: #0dcaf0;">EXPENSE</span>' :
                        result.doc_info.type === 'Revenue' ?
                        '<span class="badge" style="background-color: #84cc16;">Revenue</span>' :
                        '<span class="badge" style="background-color: #20c997;">Budget Plan</span>';
                    document.getElementById('glModalDocBranch').innerText = result.doc_info.base_branch_id;
                    currentGlBranchCode = result.doc_info.base_branch_id || '';
                    currentGlCostCenterName = result.doc_info.cost_center_name || '';
                    document.getElementById('glModalDocCostCenter').innerText = result.doc_info.cost_center_name || '-';
                    document.getElementById('glModalDocBudgetYear').innerText = result.doc_info.budget_year;
                    document.getElementById('glModalDocCreator').innerText = result.doc_info.create_eid;
                    applyEditButtonVisibility(document.getElementById('btnGlEditMode'), result.doc_info.create_eid, result.doc_info.status);
                    applyApproveButtonVisibility(document.getElementById('btnGlApproveDocument'), result.doc_info.status);
                    applyCancelButtonVisibility(document.getElementById('btnGlCancelDocument'), result.doc_info.create_eid, result.doc_info.status);
                    renderModalDocStatus(document.getElementById('glModalDocStatusTh'), document.getElementById('glModalDocStatus'), result.doc_info.status);
                    const glReasonAlert = document.getElementById('glModalCancelReasonAlert');
                    const glReasonText = document.getElementById('glModalCancelReasonText');
                    if (glReasonAlert && glReasonText) {
                        if (result.doc_info.status === 'CANCELLED' && result.doc_info.cancel_reason) {
                            glReasonText.innerText = result.doc_info.cancel_reason;
                            glReasonAlert.style.display = 'block';
                        } else {
                            glReasonAlert.style.display = 'none';
                        }
                    }
                    if (typeof feather !== 'undefined') feather.replace();
                    document.getElementById('glModalDocDate').innerText = result.doc_info.create_date;

                    // display:block (with visibility:hidden so nothing is
                    // painted yet) before building the grid, not after —
                    // jspreadsheet was previously initializing while this
                    // container was still display:none (no layout box at
                    // all), which risks it reading 0-width dimensions.
                    const modalContentEl = document.getElementById('glModalContent');
                    modalContentEl.style.display = 'flex';
                    modalContentEl.style.visibility = 'hidden';

                    renderGlDetailSpreadsheet(docType, result.manpower_list, false);

                    modalContentEl.style.visibility = 'visible';
                    modalContentEl.classList.remove('modal-content-fade-in');
                    void modalContentEl.offsetWidth;
                    modalContentEl.classList.add('modal-content-fade-in');
                } else {
                    Swal.fire('ข้อผิดพลาด', result.message || 'ไม่พบเอกสารนี้', 'error');
                    glModalInstance.hide();
                }
            })
            .catch(error => {
                if (error.message === SESSION_EXPIRED) return;
                document.getElementById('glModalLoadingSpinner').style.display = 'none';
                console.error(error);
                Swal.fire('ข้อผิดพลาด', 'เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error');
                glModalInstance.hide();
            });
    }

    async function toggleGlEditMode() {
        isGlEditMode = !isGlEditMode;
        const btnGlEdit = document.getElementById('btnGlEditMode');
        const btnGlSave = document.getElementById('btnGlSaveDocument');
        const btnGlClose = document.getElementById('btnGlCloseModal');

        if (isGlEditMode) {
            if (btnGlEdit) {
                btnGlEdit.innerHTML = '<i data-feather="x" class="me-1"></i> ยกเลิกการแก้ไข';
                btnGlEdit.classList.remove('btn-primary');
                btnGlEdit.classList.add('btn-outline-danger');
            }
            if (btnGlSave) btnGlSave.style.display = 'inline-block';
            if (btnGlClose) btnGlClose.style.display = 'none';
            const btnGlCancel = document.getElementById('btnGlCancelDocument');
            if (btnGlCancel) btnGlCancel.style.display = 'none';
            buildCostCenterSelect('glModalDocCostCenter', currentGlCostCenterName, (value) => { currentGlCostCenterName = value; });
            buildBranchSelect('glModalDocBranch', currentGlBranchCode, (value) => { currentGlBranchCode = value; });

            // Rebuild from the data already on screen (no extra fetch),
            // same as toggleAdjEditMode's currentData = table.getData() step.
            let items;
            if (currentGlDocType !== 'Budget Plan') {
                const table = glDetailTables[0];
                items = table ? table.getData().filter(row => row[0]).map(glEntryGridRowToItem) : [];
            } else {
                items = [];
                BUDGET_PLAN_SECTIONS.forEach((section, idx) => {
                    const table = glDetailTables[idx];
                    if (!table) return;
                    table.getData().forEach(row => {
                        if (row[0] || row[1] || row[2]) items.push(budgetPlanGridRowToItem(row, section.category));
                    });
                });
            }
            await ensureGeneralLedgersLoaded();
            renderGlDetailSpreadsheet(currentGlDocType, items, true);

            const containerEl = document.getElementById('glDetailTableContainer');
            containerEl.classList.remove('eb-edit-flash');
            void containerEl.offsetWidth;
            containerEl.classList.add('eb-edit-flash');
        } else {
            // Cancel edit -> reload document details from the server.
            viewGeneralLedgerDocumentDetails(currentGlDocNo, currentGlDocType);
        }
        if (typeof feather !== 'undefined') feather.replace();
    }

    function saveGlDocument() {
        const costCenterName = currentGlCostCenterName;
        if (!costCenterName) {
            Swal.fire('แจ้งเตือน', 'กรุณาเลือก Cost Center ก่อนบันทึก', 'warning');
            return;
        }
        const branchCode = currentGlBranchCode;

        const dataToSave = [];

        if (currentGlDocType !== 'Budget Plan') {
            const table = glDetailTables[0];
            const rows = table ? table.getData() : [];
            rows.forEach(row => {
                const glName = row[0];
                if (!glName) return;
                const monthlyData = {};
                monthKeysShort.forEach((key, m) => { monthlyData[key] = { amount: getNum(row[2 + m]) }; });
                dataToSave.push({
                    general_ledger_code: getGlCode(glName),
                    detail_note: row[1] || '',
                    cost_center_name: costCenterName,
                    branch_code: branchCode,
                    monthly_data: monthlyData,
                });
            });
        } else {
            BUDGET_PLAN_SECTIONS.forEach((section, idx) => {
                const table = glDetailTables[idx];
                if (!table) return;
                table.getData().forEach(row => {
                    const glName = row[0];
                    const itemCode = row[1];
                    const description = row[2];
                    if (!glName && !itemCode && !description) return;
                    const monthlyData = {};
                    monthKeysShort.forEach((key, m) => { monthlyData[key] = { amount: getNum(row[3 + m]) }; });
                    dataToSave.push({
                        budget_category: section.category,
                        item_code: itemCode || '',
                        general_ledger_code: getGlCode(glName) || '',
                        description: description || '',
                        cost_center_name: costCenterName,
                        branch_code: branchCode,
                        monthly_data: monthlyData,
                    });
                });
            });
        }

        if (dataToSave.length === 0) {
            Swal.fire('แจ้งเตือน', 'ไม่มีข้อมูลสำหรับบันทึก', 'warning');
            return;
        }

        Swal.fire({
            title: 'ยืนยันการบันทึกข้อมูล?',
            text: 'คุณตรวจสอบข้อมูลครบถ้วนและต้องการบันทึกใช่หรือไม่?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: '#0061f2',
            cancelButtonColor: '#e81500',
            confirmButtonText: 'ยืนยัน',
            cancelButtonText: 'ยกเลิก'
        }).then((result) => {
            if (!result.isConfirmed) return;

            Swal.fire({ title: 'กำลังบันทึกข้อมูล...', allowOutsideClick: false, didOpen: () => { Swal.showLoading(); } });

            const urlTemplate = window.APP_CONFIG.urls.apiDocumentUpdate;
            const url = urlTemplate.replace('TYPE', encodeURIComponent(currentGlDocType)).replace('DOCNO', encodeURIComponent(currentGlDocNo));

            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.APP_CONFIG.csrfToken },
                body: JSON.stringify(dataToSave)
            })
            .then(handleApiResponse)
            .then(data => {
                if (data.status === 'success') {
                    updateListRowTotalBudget(currentGlDocNo, sumMonthlyDataTotal(dataToSave, 'amount'));
                    Swal.fire('สำเร็จ!', 'บันทึกข้อมูลเรียบร้อยแล้ว', 'success').then(() => {
                        isGlEditMode = false;
                        viewGeneralLedgerDocumentDetails(currentGlDocNo, currentGlDocType);
                    });
                } else {
                    Swal.fire('ข้อผิดพลาด', 'ไม่สามารถบันทึกได้: ' + data.message, 'error');
                }
            })
            .catch(error => {
                if (error.message === SESSION_EXPIRED) return;
                console.error(error);
                Swal.fire('ข้อผิดพลาด', 'เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error');
            });
        });
    }

    function approveGlDocument() {
        Swal.fire({
            title: 'ยืนยันการอนุมัติเอกสาร?',
            text: 'เอกสารนี้จะถูกล็อกและไม่สามารถแก้ไขได้อีกหลังจากอนุมัติ',
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: '#28a745',
            cancelButtonColor: '#6c757d',
            confirmButtonText: 'อนุมัติ',
            cancelButtonText: 'ยกเลิก'
        }).then((result) => {
            if (!result.isConfirmed) return;
            Swal.fire({ title: 'กำลังบันทึกข้อมูล...', allowOutsideClick: false, didOpen: () => { Swal.showLoading(); }});

            const urlTemplate = window.APP_CONFIG.urls.apiDocumentApprove;
            const url = urlTemplate.replace('TYPE', encodeURIComponent(currentGlDocType)).replace('DOCNO', encodeURIComponent(currentGlDocNo));

            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.APP_CONFIG.csrfToken },
                body: JSON.stringify({})
            })
            .then(handleApiResponse)
            .then(data => {
                if (data.status === 'success') {
                    updateListRowStatus(currentGlDocNo, 'APPROVED');
                    Swal.fire('สำเร็จ!', 'อนุมัติเอกสารเรียบร้อยแล้ว', 'success').then(() => {
                        viewGeneralLedgerDocumentDetails(currentGlDocNo, currentGlDocType);
                    });
                } else {
                    Swal.fire('ข้อผิดพลาด', 'ไม่สามารถอนุมัติได้: ' + data.message, 'error');
                }
            })
            .catch(error => {
                if (error.message === SESSION_EXPIRED) return;
                console.error(error);
                Swal.fire('ข้อผิดพลาด', 'เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error');
            });
        });
    }

    function cancelGlDocument() {
        Swal.fire({
            title: 'ยืนยันการยกเลิกรายการ?',
            input: 'textarea',
            inputLabel: 'เหตุผลการยกเลิก',
            inputPlaceholder: 'กรุณาระบุเหตุผล...',
            inputValidator: (value) => (!value || !value.trim()) ? 'กรุณาระบุเหตุผลการยกเลิก' : undefined,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#dc3545',
            cancelButtonColor: '#6c757d',
            confirmButtonText: 'ยกเลิกรายการ',
            cancelButtonText: 'ปิด',
            didOpen: () => { glModalInstance?._focustrap?.deactivate?.(); },
            didClose: () => { glModalInstance?._focustrap?.activate?.(); },
        }).then((result) => {
            if (!result.isConfirmed) return;
            Swal.fire({ title: 'กำลังบันทึกข้อมูล...', allowOutsideClick: false, didOpen: () => { Swal.showLoading(); }});

            const urlTemplate = window.APP_CONFIG.urls.apiDocumentCancel;
            const url = urlTemplate.replace('TYPE', encodeURIComponent(currentGlDocType)).replace('DOCNO', encodeURIComponent(currentGlDocNo));

            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.APP_CONFIG.csrfToken },
                body: JSON.stringify({ cancel_reason: result.value.trim() })
            })
            .then(handleApiResponse)
            .then(data => {
                if (data.status === 'success') {
                    updateListRowStatus(currentGlDocNo, 'CANCELLED');
                    Swal.fire('สำเร็จ!', 'ยกเลิกรายการเรียบร้อยแล้ว', 'success').then(() => {
                        viewGeneralLedgerDocumentDetails(currentGlDocNo, currentGlDocType);
                    });
                } else {
                    Swal.fire('ข้อผิดพลาด', 'ไม่สามารถยกเลิกได้: ' + data.message, 'error');
                }
            })
            .catch(error => {
                if (error.message === SESSION_EXPIRED) return;
                console.error(error);
                Swal.fire('ข้อผิดพลาด', 'เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error');
            });
        });
    }

    // ==========================================
    // JS Logic for Position Adjustment Modal
    // ==========================================


    function viewAdjustmentDetails(docNo) {
        currentAdjDocNo = docNo;
        isAdjEditMode = false;

        const btnEdit = document.getElementById('btnAdjEditMode');
        if (btnEdit) {
            btnEdit.innerHTML = '<i data-feather="edit-2" class="me-1"></i> แก้ไขข้อมูล';
            btnEdit.classList.remove('btn-outline-danger');
            btnEdit.classList.add('btn-primary', 'text-white');
        }
        const btnAddRow = document.getElementById('btnAdjAddRow');
        const btnSave = document.getElementById('btnAdjSaveDocument');
        const btnClose = document.getElementById('btnAdjCloseModal');

        if(btnAddRow) btnAddRow.style.display = 'none';
        if(btnSave) btnSave.style.display = 'none';
        if(btnClose) btnClose.style.display = 'inline-block';

        const adjModalEl = document.getElementById('adjustmentDetailModal');
        if (!adjModalInstance) {
            adjModalInstance = new bootstrap.Modal(adjModalEl);
        }
        const adjShownPromise = waitForModalShown(adjModalEl);
        adjModalInstance.show();

        document.getElementById('adjModalContent').style.display = 'none';
        document.getElementById('adjModalLoadingSpinner').style.display = 'block';

        const urlTemplate = window.APP_CONFIG.urls.apiAdjustmentDetail;
        const url = urlTemplate.replace('DOCNO', encodeURIComponent(docNo));

        Promise.all([fetch(url).then(handleApiResponse), adjShownPromise])
            .then(([result]) => {
                document.getElementById('adjModalLoadingSpinner').style.display = 'none';

                if (result.status === 'success') {
                    document.getElementById('adjModalDocNo').innerText = result.doc_info.document_no;
                    document.getElementById('adjModalDocBranch').innerText = result.doc_info.base_branch_id;
                    currentAdjBranchCode = result.doc_info.base_branch_id || '';
                    currentAdjCostCenterName = result.doc_info.cost_center_name || '';
                    document.getElementById('adjModalDocCostCenter').innerText = result.doc_info.cost_center_name || '-';
                    document.getElementById('adjModalDocBudgetYear').innerText = result.doc_info.budget_year;
                    document.getElementById('adjModalDocCreator').innerText = result.doc_info.create_eid;
                    applyEditButtonVisibility(document.getElementById('btnAdjEditMode'), result.doc_info.create_eid, result.doc_info.status);
                    applyApproveButtonVisibility(document.getElementById('btnAdjApproveDocument'), result.doc_info.status);
                    applyCancelButtonVisibility(document.getElementById('btnAdjCancelDocument'), result.doc_info.create_eid, result.doc_info.status);
                    renderModalDocStatus(document.getElementById('adjModalDocStatusTh'), document.getElementById('adjModalDocStatus'), result.doc_info.status);
                    const adjReasonAlert = document.getElementById('adjModalCancelReasonAlert');
                    const adjReasonText = document.getElementById('adjModalCancelReasonText');
                    if (adjReasonAlert && adjReasonText) {
                        if (result.doc_info.status === 'CANCELLED' && result.doc_info.cancel_reason) {
                            adjReasonText.innerText = result.doc_info.cancel_reason;
                            adjReasonAlert.style.display = 'block';
                        } else {
                            adjReasonAlert.style.display = 'none';
                        }
                    }
                    if (typeof feather !== 'undefined') feather.replace();
                    document.getElementById('adjModalDocDate').innerText = result.doc_info.create_date;

                    // See viewDocumentDetails for why: laid out but not
                    // painted (visibility:hidden, not display:none) so
                    // building 3 jspreadsheet grids (up to 23 columns each,
                    // real DOM per cell) can't stutter an animation the user
                    // can see — the fade-in only starts once everything is
                    // actually ready.
                    const adjModalContentEl = document.getElementById('adjModalContent');
                    adjModalContentEl.style.display = 'block';
                    adjModalContentEl.style.visibility = 'hidden';

                    if (adjTable1) adjTable1.destroy();
                    if (adjTable2) adjTable2.destroy();
                    if (adjTable3) adjTable3.destroy();

                    document.getElementById('adjModalSpreadsheet1').innerHTML = '';
                    document.getElementById('adjModalSpreadsheet2').innerHTML = '';
                    document.getElementById('adjModalSpreadsheet3').innerHTML = '';

                    const getNum = (val) => parseFloat(String(val).replace(/,/g, '')) || 0;
                    
                    const cols1 = [
                        { type: 'text', align: 'left', title: 'ประเภท', width: 100, readOnly: true },
                        { type: 'text', align: 'left', title: 'ตำแหน่งเดิม', width: 200, readOnly: true },
                        { type: 'text', align: 'left', title: 'รายละเอียดตำแหน่งเดิม', width: 180, readOnly: true },
                        { type: 'text', align: 'left', title: 'ตำแหน่งใหม่', width: 200, readOnly: true },
                        { type: 'text', align: 'left', title: 'รายละเอียดตำแหน่งใหม่', width: 180, readOnly: true },
                        { type: 'numeric', title: 'เงินเดือนเดิม', width: 100, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'ค่าตำแหน่งเดิม', width: 120, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'รวมรายได้เดิม', width: 110, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'เงินเดือนใหม่', width: 100, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'ค่าตำแหน่งใหม่', width: 120, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'รวมรายได้ใหม่', width: 110, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'ผลต่างเงินเดือน', width: 110, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'ผลต่างค่าตำแหน่ง', width: 120, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Jan', width: 60, readOnly: true },
                        { type: 'numeric', title: 'Feb', width: 60, readOnly: true },
                        { type: 'numeric', title: 'Mar', width: 60, readOnly: true },
                        { type: 'numeric', title: 'Apr', width: 60, readOnly: true },
                        { type: 'numeric', title: 'May', width: 60, readOnly: true },
                        { type: 'numeric', title: 'Jun', width: 60, readOnly: true },
                        { type: 'numeric', title: 'Jul', width: 60, readOnly: true },
                        { type: 'numeric', title: 'Aug', width: 60, readOnly: true },
                        { type: 'numeric', title: 'Sep', width: 60, readOnly: true },
                        { type: 'numeric', title: 'Oct', width: 60, readOnly: true },
                        { type: 'numeric', title: 'Nov', width: 60, readOnly: true },
                        { type: 'numeric', title: 'Dec', width: 60, readOnly: true },
                        { type: 'numeric', title: 'รวม (คน)', width: 80, readOnly: true, mask: '#,##0' }
                    ];

                    const cols2 = [
                        { type: 'text', align: 'left', title: 'ตำแหน่งเดิม', width: 200, readOnly: true },
                        { type: 'text', align: 'left', title: 'ตำแหน่งใหม่', width: 200, readOnly: true },
                        { type: 'numeric', title: 'ผลต่างเงินเดือน', width: 110, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Jan', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Feb', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Mar', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Apr', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'May', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Jun', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Jul', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Aug', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Sep', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Oct', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Nov', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Dec', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'รวม (เงิน)', width: 110, readOnly: true, mask: '#,##0' }
                    ];

                    const cols3 = [
                        { type: 'text', align: 'left', title: 'ตำแหน่งเดิม', width: 200, readOnly: true },
                        { type: 'text', align: 'left', title: 'ตำแหน่งใหม่', width: 200, readOnly: true },
                        { type: 'numeric', title: 'ผลต่างค่าตำแหน่ง', width: 120, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Jan', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Feb', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Mar', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Apr', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'May', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Jun', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Jul', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Aug', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Sep', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Oct', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Nov', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'Dec', width: 80, readOnly: true, mask: '#,##0' },
                        { type: 'numeric', title: 'รวม (เงิน)', width: 110, readOnly: true, mask: '#,##0' }
                    ];

                    let data1 = [];
                    let data2 = [];
                    let data3 = [];

                    result.manpower_list.forEach(item => {
                        let m = item.monthly_data || {};
                        let diffSal = item.new_salary - item.old_salary;
                        let diffAllow = item.new_allowance - item.old_allowance;
                        
                        let r1 = [
                            item.adjustment_type || '',
                            item.old_position_name, item.old_description || '',
                            item.new_position_name, item.new_description || '',
                            item.old_salary, item.old_allowance, item.old_salary + item.old_allowance,
                            item.new_salary, item.new_allowance, item.new_salary + item.new_allowance,
                            diffSal, diffAllow
                        ];
                        let r2 = [item.old_position_name, item.new_position_name, diffSal];
                        let r3 = [item.old_position_name, item.new_position_name, diffAllow];

                        const mKeys = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
                        const monthHeadcounts = mKeys.map(k => parseFloat((m[k] || {}).headcount) || 0);
                        let sumHC = 0;
                        monthHeadcounts.forEach(hc => { r1.push(hc); sumHC += hc; });
                        r1.push(sumHC);

                        // Carry-forward, same as onAdjSpreadsheetChange/budget_add_adjustment.html
                        // — a position change's cost keeps applying to every month after it
                        // takes effect, not just the month it was entered in.
                        let sumSalCost = 0;
                        computeMonthlyBudget(monthHeadcounts, diffSal).forEach(m => { r2.push(m.cost); sumSalCost += m.cost; });
                        r2.push(sumSalCost);

                        let sumAllowCost = 0;
                        computeMonthlyBudget(monthHeadcounts, diffAllow).forEach(m => { r3.push(m.cost); sumAllowCost += m.cost; });
                        r3.push(sumAllowCost);
                        
                        data1.push(r1);
                        data2.push(r2);
                        data3.push(r3);
                    });

                    adjTable1 = jspreadsheet(document.getElementById('adjModalSpreadsheet1'), {
                        data: data1, columns: cols1, allowInsertRow: false, allowDeleteRow: false,
                        allowInsertColumn: false, allowManualInsertColumn: false, allowDeleteColumn: false,
                        tableOverflow: true, contextMenu: function() { return false; }, freezeColumns: 5
                    });
                    adjTable2 = jspreadsheet(document.getElementById('adjModalSpreadsheet2'), {
                        data: data2, columns: cols2, allowInsertRow: false, allowDeleteRow: false,
                        allowInsertColumn: false, allowManualInsertColumn: false, allowDeleteColumn: false,
                        tableOverflow: true, contextMenu: function() { return false; }
                    });
                    adjTable3 = jspreadsheet(document.getElementById('adjModalSpreadsheet3'), {
                        data: data3, columns: cols3, allowInsertRow: false, allowDeleteRow: false,
                        allowInsertColumn: false, allowManualInsertColumn: false, allowDeleteColumn: false,
                        tableOverflow: true, contextMenu: function() { return false; }
                    });

                    adjModalContentEl.style.visibility = 'visible';
                    adjModalContentEl.classList.remove('modal-content-fade-in');
                    void adjModalContentEl.offsetWidth;
                    adjModalContentEl.classList.add('modal-content-fade-in');
                } else {
                    if (typeof Swal !== 'undefined') Swal.fire('เกิดข้อผิดพลาด', result.message, 'error');
                    adjModalInstance.hide();
                }
            })
            .catch(err => {
                if (err.message === SESSION_EXPIRED) return;
                console.error(err);
                document.getElementById('adjModalLoadingSpinner').style.display = 'none';
                if (typeof Swal !== 'undefined') Swal.fire('เกิดข้อผิดพลาด', 'ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้', 'error');
                adjModalInstance.hide();
            });
    }

    
    const onAdjSpreadsheetChange = function(instance, cell, x, y, value) {
        if (!adjTable1 || !adjTable2 || !adjTable3 || isAdjUpdating || !isAdjEditMode) return;
        isAdjUpdating = true;

        try {
            x = parseInt(x);
            y = parseInt(y);

            // adjTable1's row count can only get ahead of adjTable2/adjTable3's
            // through the oninsertrow hook below, which keeps all three synced
            // regardless of how the row was added — but guard here too in case
            // a future jspreadsheet interaction (e.g. paste) slips a row past it.
            if (y >= adjTable2.rows.length || y >= adjTable3.rows.length) return;

            const allAdjItems = [];
            vetItems.forEach(i => allAdjItems.push({...i, group: 'VET Manpower', position_allowance: 0}));
            nonVetItems.forEach(i => allAdjItems.push({...i, group: 'NON VET Manpower'}));

            const getSalary = (name) => { const m = allAdjItems.find(i => i.name === name); return m ? m.salary : 0; };
            const getAllowance = (name) => { const m = allAdjItems.find(i => i.name === name); return m ? m.position_allowance : 0; };
            const getNum = (val) => parseFloat(String(val).replace(/,/g, '')) || 0;

            let oldSal = getNum(adjTable1.getValueFromCoords(5, y));
            let oldAllow = getNum(adjTable1.getValueFromCoords(6, y));
            let newSal = getNum(adjTable1.getValueFromCoords(8, y));
            let newAllow = getNum(adjTable1.getValueFromCoords(9, y));

            // Type (ประเภท) Changed
            if (x === 0) {
                const trimmedVal = (value || '').trim();
                if (trimmedVal !== '') {
                    const upper = trimmedVal.toUpperCase();
                    if (upper === 'VET') {
                        if (trimmedVal !== 'VET') adjTable1.setValueFromCoords(0, y, 'VET', true);
                    } else if (upper === 'NON VET' || upper === 'NON-VET' || upper === 'NONVET') {
                        if (trimmedVal !== 'NON VET') adjTable1.setValueFromCoords(0, y, 'NON VET', true);
                    } else {
                        adjTable1.setValueFromCoords(0, y, '', true);
                        Swal.fire({
                            icon: 'warning',
                            title: 'แจ้งเตือน',
                            text: `ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือกประเภท (VET หรือ NON VET) จากรายการ Dropdown เท่านั้น ("${trimmedVal}" ไม่ถูกต้อง)`,
                            timer: 3000,
                            showConfirmButton: false,
                            toast: true,
                            position: 'top-end'
                        });
                    }
                }
            }
            if (x === 1) {
                const trimmedVal = (value || '').trim();
                const match = trimmedVal !== '' ? allAdjItems.find(i => i.name === trimmedVal) : null;
                if (match) {
                    oldSal = match.salary || 0;
                    oldAllow = match.position_allowance || 0;
                    adjTable1.setValueFromCoords(5, y, oldSal, true);
                    adjTable1.setValueFromCoords(6, y, oldAllow, true);
                } else {
                    oldSal = 0;
                    oldAllow = 0;
                    if (trimmedVal !== '') {
                        adjTable1.setValueFromCoords(1, y, '', true);
                    }
                    adjTable1.setValueFromCoords(5, y, 0, true);
                    adjTable1.setValueFromCoords(6, y, 0, true);
                    if (trimmedVal !== '') {
                        Swal.fire({
                            icon: 'warning',
                            title: 'แจ้งเตือน',
                            text: `ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือกตำแหน่งเดิมจากรายการ Dropdown เท่านั้น ("${trimmedVal}" ไม่มีอยู่ในรายการตัวเลือก)`,
                            timer: 3000,
                            showConfirmButton: false,
                            toast: true,
                            position: 'top-end'
                        });
                    }
                }
            }
            if (x === 3) {
                const trimmedVal = (value || '').trim();
                const match = trimmedVal !== '' ? allAdjItems.find(i => i.name === trimmedVal) : null;
                if (match) {
                    newSal = match.salary || 0;
                    newAllow = match.position_allowance || 0;
                    adjTable1.setValueFromCoords(8, y, newSal, true);
                    adjTable1.setValueFromCoords(9, y, newAllow, true);
                } else {
                    newSal = 0;
                    newAllow = 0;
                    if (trimmedVal !== '') {
                        adjTable1.setValueFromCoords(3, y, '', true);
                    }
                    adjTable1.setValueFromCoords(8, y, 0, true);
                    adjTable1.setValueFromCoords(9, y, 0, true);
                    if (trimmedVal !== '') {
                        Swal.fire({
                            icon: 'warning',
                            title: 'แจ้งเตือน',
                            text: `ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือกตำแหน่งใหม่จากรายการ Dropdown เท่านั้น ("${trimmedVal}" ไม่มีอยู่ในรายการตัวเลือก)`,
                            timer: 3000,
                            showConfirmButton: false,
                            toast: true,
                            position: 'top-end'
                        });
                    }
                }
            }
            if (x === 5) oldSal = getNum(value);
            if (x === 6) oldAllow = getNum(value);
            if (x === 8) newSal = getNum(value);
            if (x === 9) newAllow = getNum(value);

            if (x === 1 || x === 3 || x === 5 || x === 6 || x === 8 || x === 9) {
                let oldTotal = oldSal + oldAllow;
                let newTotal = newSal + newAllow;
                adjTable1.setValueFromCoords(7, y, oldTotal, true);
                adjTable1.setValueFromCoords(10, y, newTotal, true);

                adjTable1.setValueFromCoords(11, y, newSal - oldSal, true);
                adjTable1.setValueFromCoords(12, y, newAllow - oldAllow, true);
            }

            // Enforce integer headcount without leading zeros in month columns (x = 13 to 24)
            if (x >= 13 && x <= 24) {
                const rawVal = String(value || '').trim();
                if (rawVal !== '') {
                    const cleanStr = rawVal.replace(/,/g, '');
                    const hasLeadingZero = /^0\d+/.test(cleanStr);
                    const num = parseFloat(cleanStr);
                    const isDecimal = !isNaN(num) && !Number.isInteger(num);

                    if (isDecimal || hasLeadingZero) {
                        const intVal = isNaN(num) ? 0 : Math.floor(num);
                        adjTable1.setValueFromCoords(x, y, intVal, false);
                        let warnMsg = 'จำนวนคนต้องเป็นตัวเลขจำนวนเต็มเท่านั้น ไม่อนุญาตให้กรอกเลขทศนิยม';
                        if (hasLeadingZero) {
                            warnMsg = 'ไม่อนุญาตให้กรอกตัวเลขที่มี 0 นำหน้า (เช่น 03, 04) ระบบปรับเป็น ' + intVal + ' ให้เรียบร้อยแล้ว';
                        }
                        Swal.fire({
                            icon: 'warning',
                            title: 'แจ้งเตือน',
                            text: warnMsg,
                            timer: 2500,
                            showConfirmButton: false,
                            toast: true,
                            position: 'top-end'
                        });
                    }
                }
            }

            const rowData1 = adjTable1.getRowData(y);
            const oldPos = rowData1[1];
            const newPos = rowData1[3];
            const diffSal = getNum(rowData1[11]);
            const diffAllow = getNum(rowData1[12]);

            let sumHC = 0;
            for(let i = 13; i <= 24; i++) {
                sumHC += getNum(rowData1[i]);
            }
            adjTable1.setValueFromCoords(25, y, sumHC, true);

            adjTable2.setValueFromCoords(0, y, oldPos, true);
            adjTable2.setValueFromCoords(1, y, newPos, true);
            adjTable2.setValueFromCoords(2, y, diffSal, true);

            const monthHeadcounts = [];
            for(let i = 13; i <= 24; i++) {
                monthHeadcounts.push(getNum(rowData1[i]));
            }

            let sumSalCost = 0;
            computeMonthlyBudget(monthHeadcounts, diffSal).forEach((m, idx) => {
                adjTable2.setValueFromCoords(10 - 7 + idx, y, m.cost, true);
                sumSalCost += m.cost;
            });
            adjTable2.setValueFromCoords(15, y, sumSalCost, true);

            adjTable3.setValueFromCoords(0, y, oldPos, true);
            adjTable3.setValueFromCoords(1, y, newPos, true);
            adjTable3.setValueFromCoords(2, y, diffAllow, true);

            let sumAllowCost = 0;
            computeMonthlyBudget(monthHeadcounts, diffAllow).forEach((m, idx) => {
                adjTable3.setValueFromCoords(10 - 7 + idx, y, m.cost, true);
                sumAllowCost += m.cost;
            });
            adjTable3.setValueFromCoords(15, y, sumAllowCost, true);
        } finally {
            // Always clear the guard, even if something above throws —
            // otherwise every future edit silently no-ops forever (the bug
            // behind "table freezes until you refresh the page").
            isAdjUpdating = false;
        }
    };

    function toggleAdjEditMode() {
        if (!adjTable1 || !adjTable2 || !adjTable3) return;
        
        isAdjEditMode = !isAdjEditMode;
        
        const btnEdit = document.getElementById('btnAdjEditMode');
        const btnAddRow = document.getElementById('btnAdjAddRow');
        const btnSave = document.getElementById('btnAdjSaveDocument');
        const btnClose = document.getElementById('btnAdjCloseModal');
        
        const allAdjItems = [];
        vetItems.forEach(i => allAdjItems.push({...i, group: 'VET Manpower', position_allowance: 0}));
        nonVetItems.forEach(i => allAdjItems.push({...i, group: 'NON VET Manpower'}));
        // Sorted once here (not inside the dropdown's per-click rebuild,
        // which jspreadsheet/jSuites always re-sorts internally regardless —
        // pre-sorting lets that repeated internal sort do less work).
        allAdjItems.sort((a, b) => a.name.localeCompare(b.name, 'th'));

        // ตำแหน่งเดิม/ใหม่ dropdown กรองตามคอลัมน์ "ประเภท" ของแถวตัวเอง —
        // jexcel เรียกฟังก์ชันนี้ใหม่ทุกครั้งที่ cell เข้าโหมดแก้ไข (ไม่ cache)
        // adjTable1 อ้างอิงผ่าน closure เหมือน onAdjSpreadsheetChange ทำอยู่
        // แล้ว ใช้งานได้แม้นิยามก่อน adjTable1 ถูก assign ด้านล่าง เพราะ
        // ฟังก์ชันนี้ไม่ถูกเรียกจนกว่าผู้ใช้จะเปิด dropdown จริง
        const filterAdjPositionsByType = function(el, e, r, n, source) {
            const type = adjTable1.getValueFromCoords(0, n);
            if (type === 'VET') return vetItems;
            if (type === 'NON VET') return nonVetItems;
            return []; // ยังไม่เลือกประเภท — ไม่แสดงตัวเลือกใดๆ จนกว่าจะเลือกประเภทก่อน
        };

        if (isAdjEditMode) {
            btnEdit.innerHTML = '<i data-feather="x" class="me-1"></i> ยกเลิกการแก้ไข';
            btnEdit.classList.remove('btn-primary', 'text-white');
            btnEdit.classList.add('btn-outline-danger');
            btnAddRow.style.display = 'block';
            btnSave.style.display = 'inline-block';
            if (btnClose) btnClose.style.display = 'none';
            const btnAdjCancel = document.getElementById('btnAdjCancelDocument');
            if (btnAdjCancel) btnAdjCancel.style.display = 'none';
            const btnAdjApprove = document.getElementById('btnAdjApproveDocument');
            if (btnAdjApprove) btnAdjApprove.style.display = 'none';

            buildCostCenterSelect('adjModalDocCostCenter', currentAdjCostCenterName, (value) => { currentAdjCostCenterName = value; });
            buildBranchSelect('adjModalDocBranch', currentAdjBranchCode, (value) => { currentAdjBranchCode = value; });

            const createAdjModalDatalist = (id, itemList) => {
                let dl = document.getElementById(id);
                if (!dl) {
                    dl = document.createElement('datalist');
                    dl.id = id;
                    document.body.appendChild(dl);
                }
                dl.innerHTML = '';
                itemList.forEach(item => {
                    const opt = document.createElement('option');
                    opt.value = item.name;
                    dl.appendChild(opt);
                });
                return dl;
            };

            createAdjModalDatalist('modal-adj-vet-positions-datalist', vetItems);
            createAdjModalDatalist('modal-adj-non-vet-positions-datalist', nonVetItems);
            createAdjModalDatalist('modal-adj-all-positions-datalist', allAdjItems);
            createAdjModalDatalist('modal-adj-type-datalist', [{ name: 'VET' }, { name: 'NON VET' }]);

            const modalAdjTypeEditor = {
                createCell: function(cell) {
                    cell.classList.add('eb-dropdown-cell');
                    return cell;
                },
                updateCell: function(cell, value) {
                    cell.classList.add('eb-dropdown-cell');
                    cell.innerText = value || '';
                    return value;
                },
                setValue: function(cell, value) {
                    cell.classList.add('eb-dropdown-cell');
                    cell.innerText = value || '';
                },
                openEditor: function(cell, el, empty) {
                    const rect = cell.getBoundingClientRect();
                    const input = document.createElement('input');

                    input.setAttribute('list', 'modal-adj-type-datalist');
                    input.className = 'jexcel_editor eb-dropdown-input';
                    input.style.width = rect.width + 'px';
                    input.style.height = (rect.height - 2) + 'px';
                    input.style.minHeight = (rect.height - 2) + 'px';
                    input.style.boxSizing = 'border-box';
                    input.style.border = 'none';
                    input.style.outline = 'none';
                    input.style.padding = '0 4px';
                    input.style.font = 'inherit';
                    input.value = empty ? '' : (cell.innerText || '');
                    cell.classList.add('editor');
                    cell.innerHTML = '';
                    cell.appendChild(input);
                    input.focus();
                    try {
                        if (typeof input.showPicker === 'function') {
                            input.showPicker();
                        }
                    } catch (e) {}
                    input.onkeydown = function(e) {
                        if (e.which === 13 || e.key === 'Enter') {
                            if (adjTable1 && adjTable1.edition) adjTable1.closeEditor(cell, true);
                        } else if (e.which === 27 || e.key === 'Escape') {
                            if (adjTable1 && adjTable1.edition) adjTable1.closeEditor(cell, false);
                        }
                    };
                    input.onchange = function() {
                        if (adjTable1 && adjTable1.edition) adjTable1.closeEditor(cell, true);
                    };
                    input.onblur = function() {
                        if (adjTable1 && adjTable1.edition) adjTable1.closeEditor(cell, true);
                    };
                },
                closeEditor: function(cell) {
                    const input = cell.querySelector('input');
                    const val = (input ? input.value : (cell.innerText || '')).trim();
                    if (val !== '') {
                        const upper = val.toUpperCase();
                        if (upper === 'VET') return 'VET';
                        if (upper === 'NON VET' || upper === 'NON-VET' || upper === 'NONVET') return 'NON VET';
                        Swal.fire({
                            icon: 'warning',
                            title: 'แจ้งเตือน',
                            text: `ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือกประเภท (VET หรือ NON VET) จากรายการ Dropdown เท่านั้น ("${val}" ไม่ถูกต้อง)`,
                            timer: 3000,
                            showConfirmButton: false,
                            toast: true,
                            position: 'top-end'
                        });
                        return '';
                    }
                    return '';
                }
            };

            const modalAdjPositionEditor = {
                createCell: function(cell) {
                    cell.classList.add('eb-dropdown-cell');
                    return cell;
                },
                updateCell: function(cell, value) {
                    cell.classList.add('eb-dropdown-cell');
                    cell.innerText = value || '';
                    return value;
                },
                setValue: function(cell, value) {
                    cell.classList.add('eb-dropdown-cell');
                    cell.innerText = value || '';
                },
                openEditor: function(cell, el, empty) {
                    const rect = cell.getBoundingClientRect();
                    const input = document.createElement('input');

                    const y = parseInt(cell.getAttribute('data-y'));
                    const rowType = (!isNaN(y) && adjTable1) ? adjTable1.getValueFromCoords(0, y) : '';
                    let listId = 'modal-adj-all-positions-datalist';
                    if (rowType === 'VET') listId = 'modal-adj-vet-positions-datalist';
                    else if (rowType === 'NON VET') listId = 'modal-adj-non-vet-positions-datalist';

                    input.setAttribute('list', listId);
                    input.className = 'jexcel_editor eb-dropdown-input';
                    input.style.width = rect.width + 'px';
                    input.style.height = (rect.height - 2) + 'px';
                    input.style.minHeight = (rect.height - 2) + 'px';
                    input.style.boxSizing = 'border-box';
                    input.style.border = 'none';
                    input.style.outline = 'none';
                    input.style.padding = '0 4px';
                    input.style.font = 'inherit';
                    input.value = empty ? '' : (cell.innerText || '');
                    cell.classList.add('editor');
                    cell.innerHTML = '';
                    cell.appendChild(input);
                    input.focus();
                    try {
                        if (typeof input.showPicker === 'function') {
                            input.showPicker();
                        }
                    } catch (e) {}
                    input.onkeydown = function(e) {
                        if (e.which === 13 || e.key === 'Enter') {
                            if (adjTable1 && adjTable1.edition) adjTable1.closeEditor(cell, true);
                        } else if (e.which === 27 || e.key === 'Escape') {
                            if (adjTable1 && adjTable1.edition) adjTable1.closeEditor(cell, false);
                        }
                    };
                    input.onchange = function() {
                        if (adjTable1 && adjTable1.edition) adjTable1.closeEditor(cell, true);
                    };
                    input.onblur = function() {
                        if (adjTable1 && adjTable1.edition) adjTable1.closeEditor(cell, true);
                    };
                },
                closeEditor: function(cell) {
                    const input = cell.querySelector('input');
                    const val = (input ? input.value : (cell.innerText || '')).trim();
                    if (val !== '' && !allAdjItems.some(i => i.name === val)) {
                        const x = parseInt(cell.getAttribute('data-x'));
                        const label = x === 1 ? 'ตำแหน่งเดิม' : 'ตำแหน่งใหม่';
                        Swal.fire({
                            icon: 'warning',
                            title: 'แจ้งเตือน',
                            text: `ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือก${label}จากรายการ Dropdown เท่านั้น ("${val}" ไม่มีอยู่ในรายการตัวเลือก)`,
                            timer: 3000,
                            showConfirmButton: false,
                            toast: true,
                            position: 'top-end'
                        });
                        return '';
                    }
                    return val;
                }
            };

            const cols1 = [
                { type: 'text', align: 'left', title: 'ประเภท', width: 100, editor: modalAdjTypeEditor },
                { type: 'text', align: 'left', title: 'ตำแหน่งเดิม', width: 200, editor: modalAdjPositionEditor },
                { type: 'text', align: 'left', title: 'รายละเอียดตำแหน่งเดิม', width: 180 },
                { type: 'text', align: 'left', title: 'ตำแหน่งใหม่', width: 200, editor: modalAdjPositionEditor },
                { type: 'text', align: 'left', title: 'รายละเอียดตำแหน่งใหม่', width: 180 },
                { type: 'numeric', title: 'เงินเดือนเดิม', width: 100, mask: '#,##0' },
                { type: 'numeric', title: 'ค่าตำแหน่งเดิม', width: 120, mask: '#,##0' },
                { type: 'numeric', title: 'รวมรายได้เดิม', width: 110, readOnly: true, mask: '#,##0' },
                { type: 'numeric', title: 'เงินเดือนใหม่', width: 100, mask: '#,##0' },
                { type: 'numeric', title: 'ค่าตำแหน่งใหม่', width: 120, mask: '#,##0' },
                { type: 'numeric', title: 'รวมรายได้ใหม่', width: 110, readOnly: true, mask: '#,##0' },
                { type: 'numeric', title: 'ผลต่างเงินเดือน', width: 110, readOnly: true, mask: '#,##0' },
                { type: 'numeric', title: 'ผลต่างค่าตำแหน่ง', width: 120, readOnly: true, mask: '#,##0' },
                { type: 'numeric', title: 'Jan', width: 60 },
                { type: 'numeric', title: 'Feb', width: 60 },
                { type: 'numeric', title: 'Mar', width: 60 },
                { type: 'numeric', title: 'Apr', width: 60 },
                { type: 'numeric', title: 'May', width: 60 },
                { type: 'numeric', title: 'Jun', width: 60 },
                { type: 'numeric', title: 'Jul', width: 60 },
                { type: 'numeric', title: 'Aug', width: 60 },
                { type: 'numeric', title: 'Sep', width: 60 },
                { type: 'numeric', title: 'Oct', width: 60 },
                { type: 'numeric', title: 'Nov', width: 60 },
                { type: 'numeric', title: 'Dec', width: 60 },
                { type: 'numeric', title: 'รวม (คน)', width: 80, readOnly: true, mask: '#,##0' }
            ];
            
            const currentData = adjTable1.getData();
            adjTable1.destroy();
            
            adjTable1 = jspreadsheet(document.getElementById('adjModalSpreadsheet1'), {
                data: currentData,
                columns: cols1,
                allowInsertRow: true,
                allowDeleteRow: true,
                allowInsertColumn: false,
                allowManualInsertColumn: false,
                allowDeleteColumn: false,
                tableOverflow: true,
                freezeColumns: 5,
                onchange: onAdjSpreadsheetChange,
                onselection: function(el, x1, y1, x2, y2, origin) {
                    const sheet = (el && el.jexcel) || adjTable1;
                    if (!sheet || typeof sheet.getCellFromCoords !== 'function') return;
                    if ((x1 === 0 || x1 === 1 || x1 === 3) && x1 === x2 && y1 === y2) {
                        const cell = sheet.getCellFromCoords(x1, y1);
                        if (cell && !sheet.edition) {
                            sheet.openEditor(cell, false);
                        }
                    }
                },
                contextMenu: function() { return true; },
                // adjTable1 can gain a row through more than just the
                // "เพิ่มรายการ" button — e.g. pressing Enter on its last row —
                // and adjTable2/adjTable3 must always mirror it row-for-row or
                // onAdjSpreadsheetChange's cross-table writes land on a row
                // that doesn't exist yet and throw, wedging isAdjUpdating
                // stuck true.
                oninsertrow: function(el, rowNumber, numOfRows, rowRecords, insertBefore) {
                    if (adjTable2) adjTable2.insertRow(numOfRows, rowNumber, insertBefore);
                    if (adjTable3) adjTable3.insertRow(numOfRows, rowNumber, insertBefore);
                },
            });

            const adjSheetContainer = document.getElementById('adjModalSpreadsheet1');
            adjSheetContainer.classList.remove('eb-edit-flash');
            void adjSheetContainer.offsetWidth;
            adjSheetContainer.classList.add('eb-edit-flash');

        } else {
            viewAdjustmentDetails(currentAdjDocNo);
        }
        if (typeof feather !== 'undefined') feather.replace();
    }

    function addAdjSpreadsheetRow() {
        // adjTable1's oninsertrow hook mirrors this into adjTable2/adjTable3,
        // so it isn't done here too (that would double-insert).
        if (isAdjEditMode && adjTable1 && adjTable2 && adjTable3) {
            adjTable1.insertRow();
        }
    }

    function saveAdjDocument() {
        if (!adjTable1 || !isAdjEditMode) return;
        if (adjTable1.edition) {
            adjTable1.closeEditor(adjTable1.edition[0], true);
        }

        const costCenterName = currentAdjCostCenterName;
        if (!costCenterName) {
            Swal.fire('แจ้งเตือน', 'กรุณาเลือก Cost Center', 'warning');
            return;
        }
        const branchCode = currentAdjBranchCode;

        const getNum = (val) => parseFloat(String(val).replace(/,/g, '')) || 0;
        let rows = adjTable1.getData();
        let dataToSave = [];

        for (let i = 0; i < rows.length; i++) {
            let row = rows[i];
            let adjustmentType = (row[0] || '').trim();
            let oldPos = (row[1] || '').trim();
            let oldDetail = row[2];
            let newPos = (row[3] || '').trim();
            let newDetail = row[4];
            let oldSal = getNum(row[5]);
            let oldAllow = getNum(row[6]);
            let newSal = getNum(row[8]);
            let newAllow = getNum(row[9]);

            // ประเภท/ตำแหน่งเดิม/ตำแหน่งใหม่ บังคับกรอกครบทั้ง 3 ช่อง — ดู
            // เหตุผลเดียวกันใน budget_add_adjustment.html
            const hasAnyIdentityData = adjustmentType || oldPos || newPos;
            const hasAllRequired = adjustmentType && oldPos && newPos;

            if (hasAnyIdentityData && !hasAllRequired) {
                Swal.fire('แจ้งเตือน', `กรุณาเลือกประเภท ตำแหน่งเดิม และตำแหน่งใหม่ให้ครบในแถวที่ ${i + 1} ก่อนบันทึก`, 'warning');
                return;
            }

            if (hasAllRequired) {
                const allAdjItems = [...vetItems, ...nonVetItems];
                if (adjustmentType !== 'VET' && adjustmentType !== 'NON VET') {
                    Swal.fire('แจ้งเตือน', `ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือกประเภท (VET หรือ NON VET) จากรายการ Dropdown เท่านั้น\n(แถวที่ ${i + 1}: "${adjustmentType}" ไม่ถูกต้อง)`, 'warning');
                    return;
                }
                const isOldValid = allAdjItems.some(it => it.name === oldPos);
                if (!isOldValid) {
                    Swal.fire('แจ้งเตือน', `ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือกตำแหน่งเดิมจากรายการ Dropdown เท่านั้น\n(แถวที่ ${i + 1}: "${oldPos}" ไม่มีอยู่ในรายการตัวเลือก)`, 'warning');
                    return;
                }
                const isNewValid = allAdjItems.some(it => it.name === newPos);
                if (!isNewValid) {
                    Swal.fire('แจ้งเตือน', `ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือกตำแหน่งใหม่จากรายการ Dropdown เท่านั้น\n(แถวที่ ${i + 1}: "${newPos}" ไม่มีอยู่ในรายการตัวเลือก)`, 'warning');
                    return;
                }

                let diffSal = newSal - oldSal;
                let diffAllow = newAllow - oldAllow;
                const monthKeys = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
                const monthCounts = [];
                for (let c = 13; c <= 24; c++) monthCounts.push(getNum(row[c]));

                const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
                for (let c = 0; c < 12; c++) {
                    const cellVal = row[13 + c];
                    const rawStr = String(cellVal !== null && cellVal !== undefined ? cellVal : '').trim().replace(/,/g, '');
                    if (rawStr !== '' && /^0\d+/.test(rawStr)) {
                        Swal.fire('แจ้งเตือน', `จำนวนคนในเดือน ${monthNames[c]} ไม่อนุญาตให้กรอกรูปแบบที่มีเลข 0 นำหน้า เช่น "${rawStr}" (แถวที่ ${i + 1}) กรุณาระบุเป็นตัวเลขจำนวนเต็มปกติ`, 'warning');
                        return;
                    }
                    if (monthCounts[c] % 1 !== 0 || monthCounts[c] < 0) {
                        Swal.fire('แจ้งเตือน', `จำนวนคนในเดือน ${monthNames[c]} ต้องเป็นตัวเลขจำนวนเต็มเท่านั้น ไม่อนุญาตให้กรอกเลขทศนิยม (แถวที่ ${i + 1})`, 'warning');
                        return;
                    }
                }
                // Cost must accumulate ("ขั้นบันได") the same way the
                // on-screen preview (adjTable2/adjTable3, via
                // onAdjSpreadsheetChange) and the create-flow save handler
                // (budget_add_adjustment.html) already do — this previously
                // recomputed cost as a flat headcount*diff per month here,
                // silently saving non-cumulative numbers that didn't match
                // what was shown before Save.
                const salaryBudget = computeMonthlyBudget(monthCounts, diffSal);
                const allowanceBudget = computeMonthlyBudget(monthCounts, diffAllow);
                let monthlyData = {};
                monthKeys.forEach((key, idx) => {
                    monthlyData[key] = {
                        headcount: monthCounts[idx],
                        // BudgetMonthlyDetail only has one 'cost' column, so the
                        // two per-month budgets shown on screen are combined
                        // here into the single total that actually gets persisted
                        // (see budget_add_adjustment.html for the same fix on create).
                        cost: salaryBudget[idx].cost + allowanceBudget[idx].cost,
                        salary_diff_cost: salaryBudget[idx].cost,
                        allowance_diff_cost: allowanceBudget[idx].cost,
                    };
                });

                dataToSave.push({
                    'adjustment_type': adjustmentType,
                    'old_position_name': oldPos,
                    'old_description': oldDetail || '',
                    'new_position_name': newPos,
                    'new_description': newDetail || '',
                    'old_salary': oldSal,
                    'old_allowance': oldAllow,
                    'new_salary': newSal,
                    'new_allowance': newAllow,
                    'cost_center_name': costCenterName,
                    'branch_code': branchCode,
                    'monthly_data': monthlyData
                });
            }
        }

        if (dataToSave.length === 0) {
            Swal.fire('แจ้งเตือน', 'กรุณาระบุข้อมูลอย่างน้อย 1 แถว', 'warning');
            return;
        }
        
        Swal.fire({
            title: 'ยืนยันการอัปเดตข้อมูล?',
            text: "คุณตรวจสอบข้อมูลครบถ้วนและต้องการบันทึกการแก้ไขใช่หรือไม่?",
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#0061f2',
            cancelButtonColor: '#e81500',
            confirmButtonText: 'บันทึก',
            cancelButtonText: 'ยกเลิก'
        }).then((result) => {
            if (result.isConfirmed) {
                Swal.fire({ title: 'กำลังบันทึกข้อมูล...', allowOutsideClick: false, didOpen: () => { Swal.showLoading(); }});
                
                const urlTemplate = window.APP_CONFIG.urls.apiAdjustmentUpdate;
                const url = urlTemplate.replace('DOCNO', encodeURIComponent(currentAdjDocNo));
                
                fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.APP_CONFIG.csrfToken },
                    body: JSON.stringify(dataToSave)
                })
                .then(handleApiResponse)
                .then(data => {
                    if (data.status === 'success') {
                        updateListRowTotalBudget(currentAdjDocNo, sumMonthlyDataTotal(dataToSave, 'cost'));
                        Swal.fire('สำเร็จ!', 'อัปเดตข้อมูลเรียบร้อยแล้ว', 'success').then(() => {
                            viewAdjustmentDetails(currentAdjDocNo);
                        });
                    } else {
                        Swal.fire('ข้อผิดพลาด', 'ไม่สามารถบันทึกได้: ' + data.message, 'error');
                    }
                })
                .catch(error => {
                    if (error.message === SESSION_EXPIRED) return;
                    console.error(error);
                    Swal.fire('ข้อผิดพลาด', 'เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error');
                });
            }
        });
    }

    function approveAdjDocument() {
        Swal.fire({
            title: 'ยืนยันการอนุมัติเอกสาร?',
            text: 'เอกสารนี้จะถูกล็อกและไม่สามารถแก้ไขได้อีกหลังจากอนุมัติ',
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: '#28a745',
            cancelButtonColor: '#6c757d',
            confirmButtonText: 'อนุมัติ',
            cancelButtonText: 'ยกเลิก'
        }).then((result) => {
            if (!result.isConfirmed) return;
            Swal.fire({ title: 'กำลังบันทึกข้อมูล...', allowOutsideClick: false, didOpen: () => { Swal.showLoading(); }});

            const urlTemplate = window.APP_CONFIG.urls.apiAdjustmentApprove;
            const url = urlTemplate.replace('DOCNO', encodeURIComponent(currentAdjDocNo));

            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.APP_CONFIG.csrfToken },
                body: JSON.stringify({})
            })
            .then(handleApiResponse)
            .then(data => {
                if (data.status === 'success') {
                    updateListRowStatus(currentAdjDocNo, 'APPROVED');
                    Swal.fire('สำเร็จ!', 'อนุมัติเอกสารเรียบร้อยแล้ว', 'success').then(() => {
                        viewAdjustmentDetails(currentAdjDocNo);
                    });
                } else {
                    Swal.fire('ข้อผิดพลาด', 'ไม่สามารถอนุมัติได้: ' + data.message, 'error');
                }
            })
            .catch(error => {
                if (error.message === SESSION_EXPIRED) return;
                console.error(error);
                Swal.fire('ข้อผิดพลาด', 'เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error');
            });
        });
    }

    function cancelAdjDocument() {
        Swal.fire({
            title: 'ยืนยันการยกเลิกรายการ?',
            input: 'textarea',
            inputLabel: 'เหตุผลการยกเลิก',
            inputPlaceholder: 'กรุณาระบุเหตุผล...',
            inputValidator: (value) => (!value || !value.trim()) ? 'กรุณาระบุเหตุผลการยกเลิก' : undefined,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#dc3545',
            cancelButtonColor: '#6c757d',
            confirmButtonText: 'ยกเลิกรายการ',
            cancelButtonText: 'ปิด',
            didOpen: () => { adjModalInstance?._focustrap?.deactivate?.(); },
            didClose: () => { adjModalInstance?._focustrap?.activate?.(); },
        }).then((result) => {
            if (!result.isConfirmed) return;
            Swal.fire({ title: 'กำลังบันทึกข้อมูล...', allowOutsideClick: false, didOpen: () => { Swal.showLoading(); }});

            const urlTemplate = window.APP_CONFIG.urls.apiAdjustmentCancel;
            const url = urlTemplate.replace('DOCNO', encodeURIComponent(currentAdjDocNo));

            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.APP_CONFIG.csrfToken },
                body: JSON.stringify({ cancel_reason: result.value.trim() })
            })
            .then(handleApiResponse)
            .then(data => {
                if (data.status === 'success') {
                    updateListRowStatus(currentAdjDocNo, 'CANCELLED');
                    Swal.fire('สำเร็จ!', 'ยกเลิกรายการเรียบร้อยแล้ว', 'success').then(() => {
                        viewAdjustmentDetails(currentAdjDocNo);
                        fetchDocuments();
                    });
                } else {
                    Swal.fire('ข้อผิดพลาด', 'ไม่สามารถยกเลิกได้: ' + data.message, 'error');
                }
            })
            .catch(error => {
                if (error.message === SESSION_EXPIRED) return;
                console.error(error);
                Swal.fire('ข้อผิดพลาด', 'เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error');
            });
        });
    }

    // ---- GL Actual Template (fixed 181-row outline, 5 plain numeric
    // columns, no Cost Center, no monthly breakdown — doesn't fit either
    // the generic manpower/equipment modal (headcount/cost twin grids) or
    // the GL-ledger modal (GL dropdown + 12 month columns), so it gets its
    // own dedicated view/edit/save trio, same reasoning as Position
    // Adjustment's adjModalInstance/adjTable* having their own. ----

    function resetGlatEditButtons() {
        const btnEdit = document.getElementById('btnGlatEditMode');
        if (btnEdit) {
            btnEdit.innerHTML = '<i data-feather="edit-2" class="me-1"></i> แก้ไขข้อมูล';
            btnEdit.classList.remove('btn-outline-danger');
            btnEdit.classList.add('btn-primary');
        }
        const btnSave = document.getElementById('btnGlatSaveDocument');
        if (btnSave) btnSave.style.display = 'none';
        const btnClose = document.getElementById('btnGlatCloseModal');
        if (btnClose) btnClose.style.display = 'inline-block';
    }

    // "Act จริง" has no fixed name of its own — it's how many months of
    // real data the number represents, tracked by the document's own
    // actual_month_count (see glatModalMonthCount / its edit-mode input).
    // Same helper as budget_add_gl_actual_template.html's actualColumnLabel.
    const glatActualColumnLabel = (monthCount) => `จำนวนเดือนข้อมูลจริง(${monthCount || '-'})`;

    const glatColumns = [
        { type: 'text', align: 'left', title: 'รหัส', width: 90, readOnly: true },
        { type: 'text', align: 'left', title: 'ชื่อ', width: 280, readOnly: true },
        { type: 'numeric', title: glatActualColumnLabel(), width: 150, mask: '#,##0.00' },
        { type: 'numeric', title: 'ต่อเดือน', width: 120, mask: '#,##0.00' },
        { type: 'numeric', title: 'รายปี (x12)', width: 120, mask: '#,##0.00' },
        { type: 'numeric', title: 'สัดส่วน/ยอดขาย', width: 130, mask: '#,##0.00' },
        { type: 'numeric', title: '% การโต', width: 110, mask: '#,##0.00' },
    ];

    // items: the manpower_list array from get_document_detail_api, already
    // in row_order (same order glatTemplateRows is in — both ultimately
    // come from the same master_data.ebudget_gl_actual_template_row
    // ordering). editable toggles readOnly on the 5 data columns and
    // whether header/subtotal row shading gets (re)applied.
    function renderGlatSpreadsheet(items, editable) {
        const container = document.getElementById('glatDetailTableContainer');
        if (glatTable) {
            glatTable.destroy();
            glatTable = null;
        }
        container.innerHTML = '';

        const columns = glatColumns.map((col, idx) => {
            if (idx < 2) return col;
            return Object.assign({}, col, { readOnly: !editable });
        });

        const data = (items && items.length > 0)
            ? items.map(item => [item.code, item.label, item.actual_value, item.per_month_value, item.annualized_value, item.sales_ratio, item.growth_rate])
            : glatTemplateRows.map(r => [r.code, r.label, 0, 0, 0, 0, 0]);

        // Strip Excel's CSV-quoting from a pasted cell value (see the
        // budget_add_gl_actual_template.html comment for full rationale).
        const sanitizeCell = (val) => {
            if (typeof val !== 'string') return val;
            val = val.trim();
            if (val.length >= 2 && val.charAt(0) === '"' && val.charAt(val.length - 1) === '"') {
                val = val.slice(1, -1).replace(/""/g, '"');
            }
            return val;
        };

        const applyPastedText = (startX, startY, text) => {
            // CRITICAL: jexcel passes x/y as *strings* (e.g. "2", "0").
            // Without parseInt, `startX + c` becomes string concatenation
            // ("2" + 0 = "20") instead of addition (2 + 0 = 2), which
            // immediately breaks the bounds check and writes zero cells.
            const originX = parseInt(startX, 10) || 0;
            const originY = parseInt(startY, 10) || 0;

            const pasteRows = String(text).replace(/\r/g, '').split('\n');
            if (pasteRows.length > 1 && pasteRows[pasteRows.length - 1] === '') pasteRows.pop();

            // Build a brand-new array rather than mutating what getData()
            // returns in place — observed a hang mutating jexcel's own
            // rows directly and feeding them straight back into setData;
            // fresh rows avoid any aliasing with jexcel's live internal
            // state.
            const existing = glatTable.getData();
            const numRows = existing.length;
            const numCols = existing[0] ? existing[0].length : 0;
            const data = existing.map(row => row.slice());
            let pastedCellCount = 0;
            for (let r = 0; r < pasteRows.length; r++) {
                const targetRow = originY + r;
                if (targetRow >= numRows) break;
                const cells = pasteRows[r].split('\t');
                for (let c = 0; c < cells.length; c++) {
                    const targetCol = originX + c;
                    if (targetCol >= numCols) break;
                    if (targetCol < 2) continue; // รหัส/ชื่อ คงที่เสมอ ไม่ให้วางทับ
                    data[targetRow][targetCol] = sanitizeCell(cells[c]);
                    pastedCellCount++;
                }
            }
            glatTable.setData(data);
            return pastedCellCount;
        };

        const onbeforepaste = function(el, pastedText, x, y) {
            Swal.fire({
                title: 'กำลังวางข้อมูลลงตาราง กรุณารอสักครู่...',
                allowOutsideClick: false,
                didOpen: () => { Swal.showLoading(); }
            });
            // SweetAlert2 v11 opens the popup with an inline opacity:0
            // style and only clears it once its show animation finishes.
            // The reliable signal is SweetAlert2's own animation ending,
            // so we wait for that before starting the data fill. A 1s
            // timeout acts as safety net in case the event never fires.
            const popupEl = document.querySelector('.swal2-popup');
            const runPaste = () => {
                try {
                    applyPastedText(x, y, pastedText);
                } finally {
                    Swal.close();
                    // Immediately disarm the SweetAlert2 backdrop and
                    // popup so they can't intercept clicks during the
                    // ~300ms fade-out animation.
                    const container = document.querySelector('.swal2-container');
                    if (container) container.style.pointerEvents = 'none';
                    const swalPopup = document.querySelector('.swal2-popup');
                    if (swalPopup) swalPopup.style.pointerEvents = 'none';
                }
            };
            if (popupEl) {
                let started = false;
                const start = () => {
                    if (started) return;
                    started = true;
                    runPaste();
                };
                popupEl.addEventListener('animationend', start, { once: true });
                popupEl.addEventListener('transitionend', start, { once: true });
                setTimeout(start, 1000);
            } else {
                runPaste();
            }
            return false;
        };

        glatTable = jspreadsheet(container, {
            data: data,
            columns: columns,
            onbeforepaste: onbeforepaste,
            allowInsertColumn: false,
            allowManualInsertColumn: false,
            allowDeleteColumn: false,
            allowInsertRow: false,
            allowDeleteRow: false,
            tableOverflow: true,
            tableHeight: '100%',
            freezeColumns: 2,
            contextMenu: function() { return false; },
        });
        glatTable.setHeader(2, glatActualColumnLabel(currentGlatMonthCount));

        const rowsMeta = (items && items.length > 0)
            ? items.map(item => ({ row_type: item.row_type }))
            : glatTemplateRows;
        rowsMeta.forEach((r, i) => {
            if (r.row_type === 'header' || r.row_type === 'subtotal') {
                const rowEl = container.querySelector(`tbody tr:nth-child(${i + 1})`);
                if (rowEl) rowEl.classList.add(r.row_type === 'header' ? 'gl-actual-row-header' : 'gl-actual-row-subtotal');
            }
        });
    }

    function buildGlatBranchSelect(cellId, currentValue, onChange) {
        const cell = document.getElementById(cellId);
        if (!cell) return;
        const selectId = cellId + 'Select';
        cell.innerHTML = `<select id="${selectId}" class="form-select form-select-sm"></select>`;
        const ts = new TomSelect(`#${selectId}`, {
            options: glatBranches.map(b => ({ value: b.code, text: `${b.code} - ${b.name}` })),
            valueField: 'value',
            labelField: 'text',
            searchField: ['text', 'value'],
            create: false,
            placeholder: '-- เลือกสาขา --',
            onChange: onChange,
            dropdownParent: 'body',
        });
        if (currentValue) ts.setValue(currentValue, true);
    }

    function viewGlatDocumentDetails(docNo) {
        currentGlatDocNo = docNo;
        isGlatEditMode = false;
        resetGlatEditButtons();

        const modalEl = document.getElementById('glatDocumentDetailModal');
        if (!glatModalInstance) {
            glatModalInstance = new bootstrap.Modal(modalEl);
        }
        const shownPromise = waitForModalShown(modalEl);
        glatModalInstance.show();

        document.getElementById('glatModalContent').style.display = 'none';
        document.getElementById('glatModalLoadingSpinner').style.display = 'block';

        const urlTemplate = window.APP_CONFIG.urls.apiDocumentDetail;
        const url = urlTemplate.replace('TYPE', encodeURIComponent('GL Actual Template')).replace('DOCNO', encodeURIComponent(docNo));

        Promise.all([fetch(url).then(handleApiResponse), shownPromise])
            .then(([result]) => {
                document.getElementById('glatModalLoadingSpinner').style.display = 'none';

                if (result.status === 'success') {
                    document.getElementById('glatModalDocNo').innerText = result.doc_info.document_no;
                    document.getElementById('glatModalDocBranch').innerText = result.doc_info.base_branch_id;
                    currentGlatBranchCode = result.doc_info.base_branch_id || '';
                    document.getElementById('glatModalActualYear').innerText = result.doc_info.actual_year;
                    document.getElementById('glatModalDocBudgetYear').innerText = result.doc_info.budget_year;
                    document.getElementById('glatModalMonthCount').innerText = result.doc_info.actual_month_count;
                    currentGlatMonthCount = result.doc_info.actual_month_count;
                    document.getElementById('glatModalGrowthPct').innerText =
                        `${result.doc_info.growth_pct_1} / ${result.doc_info.growth_pct_2} / ${result.doc_info.growth_pct_3}`;
                    currentGlatGrowthPct1 = result.doc_info.growth_pct_1;
                    currentGlatGrowthPct2 = result.doc_info.growth_pct_2;
                    currentGlatGrowthPct3 = result.doc_info.growth_pct_3;
                    document.getElementById('glatModalDocCreator').innerText = result.doc_info.create_eid;
                    applyEditButtonVisibility(document.getElementById('btnGlatEditMode'), result.doc_info.create_eid, result.doc_info.status);
                    applyCancelButtonVisibility(document.getElementById('btnGlatCancelDocument'), result.doc_info.create_eid, result.doc_info.status);
                    renderModalDocStatus(document.getElementById('glatModalDocStatusTh'), document.getElementById('glatModalDocStatus'), result.doc_info.status);
                    const glatReasonAlert = document.getElementById('glatModalCancelReasonAlert');
                    const glatReasonText = document.getElementById('glatModalCancelReasonText');
                    if (glatReasonAlert && glatReasonText) {
                        if (result.doc_info.status === 'CANCELLED' && result.doc_info.cancel_reason) {
                            glatReasonText.innerText = result.doc_info.cancel_reason;
                            glatReasonAlert.style.display = 'block';
                        } else {
                            glatReasonAlert.style.display = 'none';
                        }
                    }
                    if (typeof feather !== 'undefined') feather.replace();
                    document.getElementById('glatModalDocDate').innerText = result.doc_info.create_date;

                    const modalContentEl = document.getElementById('glatModalContent');
                    modalContentEl.style.display = 'flex';
                    modalContentEl.style.visibility = 'hidden';

                    renderGlatSpreadsheet(result.manpower_list, false);

                    modalContentEl.style.visibility = 'visible';
                    modalContentEl.classList.remove('modal-content-fade-in');
                    void modalContentEl.offsetWidth;
                    modalContentEl.classList.add('modal-content-fade-in');
                } else {
                    Swal.fire('ข้อผิดพลาด', result.message || 'ไม่พบเอกสารนี้', 'error');
                    glatModalInstance.hide();
                }
            })
            .catch(error => {
                if (error.message === SESSION_EXPIRED) return;
                document.getElementById('glatModalLoadingSpinner').style.display = 'none';
                console.error(error);
                Swal.fire('ข้อผิดพลาด', 'เกิดข้อผิดพลาดในการเชื่อมต่อ', 'error');
                glatModalInstance.hide();
            });
    }

    function toggleGlatEditMode() {
        isGlatEditMode = !isGlatEditMode;
        const btnEdit = document.getElementById('btnGlatEditMode');
        const btnSave = document.getElementById('btnGlatSaveDocument');
        const btnClose = document.getElementById('btnGlatCloseModal');

        if (isGlatEditMode) {
            if (btnEdit) {
                btnEdit.innerHTML = '<i data-feather="x" class="me-1"></i> ยกเลิกการแก้ไข';
                btnEdit.classList.remove('btn-primary');
                btnEdit.classList.add('btn-outline-danger');
            }
            if (btnSave) btnSave.style.display = 'inline-block';
            if (btnClose) btnClose.style.display = 'none';
            const btnGlatCancel = document.getElementById('btnGlatCancelDocument');
            if (btnGlatCancel) btnGlatCancel.style.display = 'none';
            buildGlatBranchSelect('glatModalDocBranch', currentGlatBranchCode, (value) => { currentGlatBranchCode = value; });

            // Month count / growth % become plain number inputs in place of
            // their <td> text, same swap-in-place pattern as the branch
            // select above.
            const monthCountTd = document.getElementById('glatModalMonthCount');
            monthCountTd.innerHTML = `<input type="number" id="glatMonthCountInput" class="form-control form-control-sm" min="0" max="12" step="1" value="${currentGlatMonthCount || ''}">`;
            document.getElementById('glatMonthCountInput').addEventListener('input', (e) => {
                currentGlatMonthCount = e.target.value;
                if (glatTable) glatTable.setHeader(2, glatActualColumnLabel(currentGlatMonthCount));
            });

            const growthTd = document.getElementById('glatModalGrowthPct');
            growthTd.innerHTML =
                `<input type="number" id="glatGrowthPct1Input" class="form-control form-control-sm d-inline-block" style="width:80px;" step="0.01" value="${currentGlatGrowthPct1 || 0}"> / ` +
                `<input type="number" id="glatGrowthPct2Input" class="form-control form-control-sm d-inline-block" style="width:80px;" step="0.01" value="${currentGlatGrowthPct2 || 0}"> / ` +
                `<input type="number" id="glatGrowthPct3Input" class="form-control form-control-sm d-inline-block" style="width:80px;" step="0.01" value="${currentGlatGrowthPct3 || 0}">`;
            document.getElementById('glatGrowthPct1Input').addEventListener('input', (e) => { currentGlatGrowthPct1 = e.target.value; });
            document.getElementById('glatGrowthPct2Input').addEventListener('input', (e) => { currentGlatGrowthPct2 = e.target.value; });
            document.getElementById('glatGrowthPct3Input').addEventListener('input', (e) => { currentGlatGrowthPct3 = e.target.value; });

            // Rebuilding all 181 rows as an editable jspreadsheet grid is
            // synchronous and heavy enough to look like the page froze —
            // show a loading popup first, then only start the rebuild once
            // SweetAlert2's own show animation has genuinely finished (see
            // onbeforepaste above / budget_add_gl_actual_template.html for
            // why a bare setTimeout or requestAnimationFrame isn't reliable
            // here — verified with a real browser).
            Swal.fire({
                title: 'กำลังโหลดข้อมูลสำหรับแก้ไข กรุณารอสักครู่...',
                allowOutsideClick: false,
                didOpen: () => { Swal.showLoading(); }
            });
            const editPopupEl = document.querySelector('.swal2-popup');
            const runEditRebuild = () => {
                try {
                    // Rebuild from the data already on screen (no extra
                    // fetch) — same as toggleAdjEditMode/toggleGlEditMode.
                    const rows = glatTable ? glatTable.getData() : [];
                    const items = rows.map((row, i) => ({
                        code: row[0],
                        label: row[1],
                        row_type: glatTemplateRows[i] ? glatTemplateRows[i].row_type : 'gl',
                        actual_value: row[2],
                        per_month_value: row[3],
                        annualized_value: row[4],
                        sales_ratio: row[5],
                        growth_rate: row[6],
                    }));
                    renderGlatSpreadsheet(items, true);

                    const containerEl = document.getElementById('glatDetailTableContainer');
                    containerEl.classList.remove('eb-edit-flash');
                    void containerEl.offsetWidth;
                    containerEl.classList.add('eb-edit-flash');
                } finally {
                    Swal.close();
                    // See onbeforepaste above / budget_add_gl_actual_template.html
                    // for the full investigation — drop pointer-events on the
                    // lingering backdrop immediately instead of waiting out
                    // SweetAlert2's own ~1s fade-out, so the rebuilt grid is
                    // clickable right away.
                    const swalContainerEl = document.querySelector('.swal2-container');
                    if (swalContainerEl) swalContainerEl.style.pointerEvents = 'none';
                }
            };
            if (editPopupEl) {
                let editStarted = false;
                const startEdit = () => {
                    if (editStarted) return;
                    editStarted = true;
                    runEditRebuild();
                };
                editPopupEl.addEventListener('animationend', startEdit, { once: true });
                editPopupEl.addEventListener('transitionend', startEdit, { once: true });
                setTimeout(startEdit, 1000);
            } else {
                runEditRebuild();
            }
        } else {
            // Cancel edit -> reload document details from the server.
            viewGlatDocumentDetails(currentGlatDocNo);
        }
        if (typeof feather !== 'undefined') feather.replace();
    }

    function saveGlatDocument() {
        if (!currentGlatBranchCode) {
            Swal.fire('แจ้งเตือน', 'กรุณาเลือกสาขาก่อนบันทึก', 'warning');
            return;
        }

        const rows = glatTable ? glatTable.getData() : [];
        const dataToSave = glatTemplateRows.map((r, i) => {
            const row = rows[i] || [];
            return {
                template_row_id: r.template_row_id,
                row_order: r.row_order,
                code: r.code,
                label: r.label,
                row_type: r.row_type,
                actual_value: getNum(row[2]),
                per_month_value: getNum(row[3]),
                annualized_value: getNum(row[4]),
                sales_ratio: getNum(row[5]),
                growth_rate: getNum(row[6]),
                branch_code: currentGlatBranchCode,
                actual_month_count: currentGlatMonthCount ? parseInt(currentGlatMonthCount, 10) : null,
                growth_pct_1: getNum(currentGlatGrowthPct1),
                growth_pct_2: getNum(currentGlatGrowthPct2),
                growth_pct_3: getNum(currentGlatGrowthPct3),
            };
        });

        Swal.fire({
            title: 'ยืนยันการบันทึกข้อมูล?',
            text: 'คุณตรวจสอบข้อมูลครบถ้วนและต้องการบันทึกใช่หรือไม่?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: '#0061f2',
            cancelButtonColor: '#e81500',
            confirmButtonText: 'ยืนยัน',
            cancelButtonText: 'ยกเลิก'
        }).then((result) => {
            if (!result.isConfirmed) return;

            Swal.fire({
                title: 'กำลังบันทึกข้อมูล...',
                allowOutsideClick: false,
                didOpen: () => { Swal.showLoading(); }
            });

            const urlTemplate = window.APP_CONFIG.urls.apiDocumentUpdate;
            const url = urlTemplate.replace('TYPE', encodeURIComponent('GL Actual Template')).replace('DOCNO', encodeURIComponent(currentGlatDocNo));

            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.APP_CONFIG.csrfToken },
                body: JSON.stringify(dataToSave)
            })
            .then(handleApiResponse)
            .then(data => {
                if (data.status === 'success') {
                    Swal.fire('สำเร็จ!', 'บันทึกข้อมูลเรียบร้อยแล้ว', 'success').then(() => {
                        viewGlatDocumentDetails(currentGlatDocNo);
                        fetchDocuments();
                    });
                } else {
                    Swal.fire('ข้อผิดพลาด', 'ไม่สามารถบันทึกได้: ' + data.message, 'error');
                }
            })
            .catch(error => {
                if (error.message === SESSION_EXPIRED) return;
                console.error(error);
                Swal.fire('ข้อผิดพลาด', 'เกิดข้อผิดพลาดในการเชื่อมต่อเครือข่าย', 'error');
            });
        });
    }

    function cancelGlatDocument() {
        Swal.fire({
            title: 'ยืนยันการยกเลิกรายการ?',
            input: 'textarea',
            inputLabel: 'เหตุผลการยกเลิก',
            inputPlaceholder: 'กรุณาระบุเหตุผล...',
            inputValidator: (value) => (!value || !value.trim()) ? 'กรุณาระบุเหตุผลการยกเลิก' : undefined,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#dc3545',
            cancelButtonColor: '#6c757d',
            confirmButtonText: 'ยกเลิกรายการ',
            cancelButtonText: 'ปิด',
            didOpen: () => { glatModalInstance?._focustrap?.deactivate?.(); },
            didClose: () => { glatModalInstance?._focustrap?.activate?.(); },
        }).then((result) => {
            if (!result.isConfirmed) return;
            Swal.fire({ title: 'กำลังบันทึกข้อมูล...', allowOutsideClick: false, didOpen: () => { Swal.showLoading(); }});

            const urlTemplate = window.APP_CONFIG.urls.apiDocumentCancel;
            const url = urlTemplate.replace('TYPE', encodeURIComponent('GL Actual Template')).replace('DOCNO', encodeURIComponent(currentGlatDocNo));

            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.APP_CONFIG.csrfToken },
                body: JSON.stringify({ cancel_reason: result.value.trim() })
            })
            .then(handleApiResponse)
            .then(data => {
                if (data.status === 'success') {
                    updateListRowStatus(currentGlatDocNo, 'CANCELLED');
                    Swal.fire('สำเร็จ!', 'ยกเลิกรายการเรียบร้อยแล้ว', 'success').then(() => {
                        viewGlatDocumentDetails(currentGlatDocNo);
                        fetchDocuments();
                    });
                } else {
                    Swal.fire('ข้อผิดพลาด', 'ไม่สามารถยกเลิกได้: ' + data.message, 'error');
                }
            })
            .catch(error => {
                if (error.message === SESSION_EXPIRED) return;
                console.error(error);
                Swal.fire('ข้อผิดพลาด', 'เกิดข้อผิดพลาดในการเชื่อมต่อเครือข่าย', 'error');
            });
        });
    }

    // ---- Public API ----
    return {
        fetchDocuments: fetchDocuments,
        applyFilters: applyFilters,
        viewDocumentDetails: viewDocumentDetails,
        viewGeneralLedgerDocumentDetails: viewGeneralLedgerDocumentDetails,
        toggleGlEditMode: toggleGlEditMode,
        addGlSpreadsheetRow: addGlSpreadsheetRow,
        saveGlDocument: saveGlDocument,
        approveGlDocument: approveGlDocument,
        cancelGlDocument: cancelGlDocument,
        toggleEditMode: toggleEditMode,
        addSpreadsheetRow: addSpreadsheetRow,
        saveDocument: saveDocument,
        approveDocument: approveDocument,
        cancelDocument: cancelDocument,
        viewAdjustmentDetails: viewAdjustmentDetails,
        toggleAdjEditMode: toggleAdjEditMode,
        addAdjSpreadsheetRow: addAdjSpreadsheetRow,
        saveAdjDocument: saveAdjDocument,
        approveAdjDocument: approveAdjDocument,
        cancelAdjDocument: cancelAdjDocument,
        viewGlatDocumentDetails: viewGlatDocumentDetails,
        toggleGlatEditMode: toggleGlatEditMode,
        saveGlatDocument: saveGlatDocument,
        cancelGlatDocument: cancelGlatDocument
    };
})();

// Expose to window for inline onclick handlers
window.fetchDocuments = BudgetApp.fetchDocuments;
window.applyFilters = BudgetApp.applyFilters;
window.viewDocumentDetails = BudgetApp.viewDocumentDetails;
window.viewGeneralLedgerDocumentDetails = BudgetApp.viewGeneralLedgerDocumentDetails;
window.toggleGlEditMode = BudgetApp.toggleGlEditMode;
window.addGlSpreadsheetRow = BudgetApp.addGlSpreadsheetRow;
window.saveGlDocument = BudgetApp.saveGlDocument;
window.approveGlDocument = BudgetApp.approveGlDocument;
window.cancelGlDocument = BudgetApp.cancelGlDocument;
window.toggleEditMode = BudgetApp.toggleEditMode;
window.addSpreadsheetRow = BudgetApp.addSpreadsheetRow;
window.saveDocument = BudgetApp.saveDocument;
window.approveDocument = BudgetApp.approveDocument;
window.cancelDocument = BudgetApp.cancelDocument;
window.viewAdjustmentDetails = BudgetApp.viewAdjustmentDetails;
window.toggleAdjEditMode = BudgetApp.toggleAdjEditMode;
window.addAdjSpreadsheetRow = BudgetApp.addAdjSpreadsheetRow;
window.saveAdjDocument = BudgetApp.saveAdjDocument;
window.approveAdjDocument = BudgetApp.approveAdjDocument;
window.cancelAdjDocument = BudgetApp.cancelAdjDocument;
window.viewGlatDocumentDetails = BudgetApp.viewGlatDocumentDetails;
window.toggleGlatEditMode = BudgetApp.toggleGlatEditMode;
window.saveGlatDocument = BudgetApp.saveGlatDocument;
window.cancelGlatDocument = BudgetApp.cancelGlatDocument;

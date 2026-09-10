const BudgetApp = (function() {
    // ---- Private State ----
    let dataTable = null;
    let fetchController = null;
    let detailModalInstance = null;
    let modalTable1 = null;
    let modalTable2 = null;
    let isEditMode = false;
    let currentDocNo = '';
    let currentDocType = '';
    let isUpdating = false;
    let currentCategoryData = [];
    
    let adjModalInstance = null;
    let adjTable1 = null, adjTable2 = null, adjTable3 = null;
    let isAdjEditMode = false;
    let currentAdjDocNo = '';
    let isAdjUpdating = false;

    // Wait for DOM
    document.addEventListener('DOMContentLoaded', () => {
        // Initialization if needed
    });

    const vetItems = JSON.parse(document.getElementById('vet-items-data').textContent);
    const nonVetItems = JSON.parse(document.getElementById('nonvet-items-data').textContent);
    const medItems = document.getElementById('med-items-data') ? JSON.parse(document.getElementById('med-items-data').textContent) : [];
    const compItems = document.getElementById('comp-items-data') ? JSON.parse(document.getElementById('comp-items-data').textContent) : [];
    const furnitureItems = document.getElementById('furniture-items-data') ? JSON.parse(document.getElementById('furniture-items-data').textContent) : [];
    const toolsItems = document.getElementById('tools-items-data') ? JSON.parse(document.getElementById('tools-items-data').textContent) : [];
    const costCenters = document.getElementById('modal-cost-centers-data') ? JSON.parse(document.getElementById('modal-cost-centers-data').textContent) : [];

    const getNum = (val) => parseFloat(String(val).replace(/,/g, '')) || 0;

    // Fills a cost-center <select> with every known cost center and
    // preselects `currentValue` (kept as an option even if it's since been
    // renamed/removed from the master table, so editing never silently
    // drops the document's existing value).
    function populateCostCenterSelect(selectEl, currentValue) {
        selectEl.innerHTML = '';
        const names = costCenters.map(cc => cc.cost_center_name);
        if (currentValue && !names.includes(currentValue)) {
            names.unshift(currentValue);
        }
        names.forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            selectEl.appendChild(opt);
        });
        selectEl.value = currentValue || '';
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

    const onSpreadsheetChange = function(instance, cell, x, y, value) {
        if (!modalTable1 || !modalTable2 || isUpdating || !isEditMode) return;
        isUpdating = true;
        
        x = parseInt(x);
        y = parseInt(y);
        
        const isNonVet = currentDocType === 'NON VET';
        const isMed = currentDocType === 'Medical Equipment';
        const isComp = currentDocType === 'Computer Equipment';
        const isFurniture = currentDocType === 'Furniture';
        const isTools = currentDocType === 'Tools & Equipment';
        const isEquipment = isMed || isComp || isFurniture || isTools;
        let itemsList = vetItems;
        if (isNonVet) itemsList = nonVetItems;
        if (isMed) itemsList = medItems;
        else if (isComp) itemsList = compItems;
        else if (isFurniture) itemsList = furnitureItems;
        else if (isTools) itemsList = toolsItems;

        // If position changed, update salary
        if (x === 0) {
            const match = itemsList.find(i => i.name === value);
            const salary = match ? (isEquipment ? match.purchase_price : match.salary) : 0;
            modalTable1.setValueFromCoords(1, y, salary, true); 
            
            if (isNonVet) {
                const allowance = match ? match.position_allowance : 0;
                modalTable1.setValueFromCoords(2, y, allowance, true);
            }
        }

        // Calculate total for this row in table1
        const rowData1 = modalTable1.getRowData(y);
        let sum1 = 0;
        const startCol = isNonVet ? 3 : 2;
        const endCol = isNonVet ? 14 : 13;
        
        for(let i = startCol; i <= endCol; i++) {
            sum1 += getNum(rowData1[i]);
        }
        modalTable1.setValueFromCoords(endCol + 1, y, sum1, true);

        // Sync with table2
        const pos = rowData1[0];
        const sal = getNum(rowData1[1]);
        
        modalTable2.setValueFromCoords(0, y, pos, true);
        modalTable2.setValueFromCoords(1, y, sal, true);
        
        let total_sal = sal;
        if (isNonVet) {
            const allow = getNum(rowData1[2]);
            modalTable2.setValueFromCoords(2, y, allow, true);
            total_sal += allow;
        }
        
        let sum2 = 0;
        for(let i = startCol; i <= endCol; i++) {
            const count = getNum(rowData1[i]);
            const cost = count * total_sal;
            modalTable2.setValueFromCoords(i, y, cost, true);
            sum2 += cost;
        }
        modalTable2.setValueFromCoords(endCol + 1, y, sum2, true);
        
        isUpdating = false;
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
                        <th>Date Created</th>
                        <th>Created By</th>
                        <th>Total Positions</th>
                        <th>Action</th>
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
                    '<span class="badge" style="background-color: #6610f2;">NON VET</span>';
                const actionUrl = `javascript:viewDocumentDetails('${doc.document_no}', '${doc.type}')`;

                // Per-row stagger delay is handled entirely in CSS via
                // nth-child (see polish.css) — simple-datatables rebuilds
                // this markup on init and drops any inline style we'd set
                // here, so a JS-computed animation-delay would be discarded.
                rowsHtml += `
                    <tr>
                        <td>${doc.document_no}</td>
                        <td>${catBadge}</td>
                        <td>${doc.create_date}</td>
                        <td>${doc.create_eid}</td>
                        <td>${doc.total_positions}</td>
                        <td>
                            <a class="btn btn-datatable btn-icon btn-transparent-dark me-2" href="${actionUrl}"><i data-feather="eye"></i></a>
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

        // Best Practice: Handle the native 'search' and 'input' events for the browser's clear (X) button
        setTimeout(() => {
            const container = document.getElementById('tableContainer');
            const searchInput = container.querySelector('.dataTable-input');
            if (searchInput) {
                const triggerClear = function() {
                    if (searchInput.value === '') {
                        // Force a complete UI refresh to guarantee stability
                        applyTypeFilter();
                    }
                };
                searchInput.addEventListener('search', triggerClear);
                // Also catch manual clears that might not trigger 'search'
                searchInput.addEventListener('input', triggerClear);
            }
        }, 100);
    }

    function applyTypeFilter() {
        const selectedType = document.getElementById('docTypeFilter').value;
        if (selectedType === 'ALL') {
            renderDataTable(currentCategoryData);
        } else {
            const filteredData = currentCategoryData.filter(doc => doc.type === selectedType);
            renderDataTable(filteredData);
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
            `;
        }
        
        const urlTemplate = window.APP_CONFIG.urls.apiGetDocuments;
        const url = urlTemplate.replace('DUMMY', categoryCode);
        
        document.getElementById('placeholderText').style.display = 'none';
        document.getElementById('tableContainer').style.display = 'none';
        document.getElementById('loadingSpinner').style.display = 'block';
        document.getElementById('docTypeFilter').style.display = 'none';

        fetch(url, { signal: fetchController.signal })
            .then(handleApiResponse)
            .then(result => {
                document.getElementById('loadingSpinner').style.display = 'none';
                
                if (result.status === 'success' && result.data && result.data.length > 0) {
                    currentCategoryData = result.data;
                    document.getElementById('docTypeFilter').style.display = 'inline-block';
                    document.getElementById('docTypeFilter').value = 'ALL';
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

        if (!detailModalInstance) {
            detailModalInstance = new bootstrap.Modal(document.getElementById('documentDetailModal'));
        }
        detailModalInstance.show();
        
        document.getElementById('modalContent').style.display = 'none';
        document.getElementById('modalLoadingSpinner').style.display = 'block';

        const urlTemplate = window.APP_CONFIG.urls.apiDocumentDetail;
        const url = urlTemplate.replace('TYPE', encodeURIComponent(docType)).replace('DOCNO', encodeURIComponent(docNo));

        fetch(url)
            .then(handleApiResponse)
            .then(result => {
                document.getElementById('modalLoadingSpinner').style.display = 'none';

                if (result.status === 'success') {
                    // Populate Doc Info
                    document.getElementById('modalDocNo').innerText = result.doc_info.document_no;
                    document.getElementById('modalDocType').innerHTML = result.doc_info.type === 'VET' ? '<span class="badge bg-primary">VET</span>' : result.doc_info.type === 'Medical Equipment' ? '<span class="badge bg-success">Medical Equipment</span>' : result.doc_info.type === 'Computer Equipment' ? '<span class="badge bg-warning text-dark">Computer Equipment</span>' : result.doc_info.type === 'Furniture' ? '<span class="badge bg-secondary">Furniture</span>' : result.doc_info.type === 'Tools & Equipment' ? '<span class="badge bg-dark">Tools & Equipment</span>' : '<span class="badge" style="background-color: #6610f2;">NON VET</span>';
                    document.getElementById('modalDocBranch').innerText = result.doc_info.base_branch_id;
                    document.getElementById('modalDocCostCenter').innerText = result.doc_info.cost_center_name || '-';
                    populateCostCenterSelect(document.getElementById('modalDocCostCenterSelect'), result.doc_info.cost_center_name);
                    document.getElementById('modalDocCostCenterSelect').style.display = 'none';
                    document.getElementById('modalDocCostCenter').style.display = 'inline';
                    document.getElementById('modalDocCreator').innerText = result.doc_info.create_eid;
                    document.getElementById('modalDocDate').innerText = result.doc_info.create_date;

                    const modalContentEl = document.getElementById('modalContent');
                    modalContentEl.style.display = 'block';
                    modalContentEl.classList.remove('modal-content-fade-in');
                    void modalContentEl.offsetWidth;
                    modalContentEl.classList.add('modal-content-fade-in');

                    if (modalTable1) {
                        modalTable1.destroy();
                        modalTable1 = null;
                    }
                    if (modalTable2) {
                        modalTable2.destroy();
                        modalTable2 = null;
                    }
                    const skeletonHtml = '<div class="placeholder-glow p-3"><span class="placeholder col-12 eb-skeleton d-block"></span></div>';
                    document.getElementById('modalSpreadsheet1').innerHTML = skeletonHtml;
                    document.getElementById('modalSpreadsheet2').innerHTML = skeletonHtml;

                    const isNonVet = result.doc_info.type === 'NON VET';
                    const isMed = result.doc_info.type === 'Medical Equipment';
                    const isComp = result.doc_info.type === 'Computer Equipment';
                    const isFurniture = result.doc_info.type === 'Furniture';
                    const isTools = result.doc_info.type === 'Tools & Equipment';
                    const isEquipment = isMed || isComp || isFurniture || isTools;

                    // Columns setup
                    const columns = [
                        { type: 'text', title: isEquipment ? 'เครื่องมือ' : 'ตำแหน่ง', width: 250, readOnly: true },
                        { type: 'numeric', title: isEquipment ? 'ราคาซื้อ' : 'เงินเดือน', width: 100, readOnly: true, mask: '#,##0' }
                    ];
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
                        let row1 = [item.position_name || item.item_name, item.salary || item.purchase_price];
                        let row2 = [item.position_name || item.item_name, item.salary || item.purchase_price];
                        
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
                        let emptyRow = isNonVet ? ['','',0,0,0,0,0,0,0,0,0,0,0,0,0,0] : ['','',0,0,0,0,0,0,0,0,0,0,0,0,0];
                        data1.push([...emptyRow]);
                        data2.push([...emptyRow]);
                    }

                    // Render jspreadsheet inside modal (modal is already shown, and block displayed)
                    setTimeout(() => {
                        // jspreadsheet appends into its target rather than replacing
                        // existing content, so the skeleton placeholder set above
                        // must be cleared explicitly or it stays visible alongside
                        // the real grid.
                        document.getElementById('modalSpreadsheet1').innerHTML = '';
                        document.getElementById('modalSpreadsheet2').innerHTML = '';
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
                    }, 50);
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
        const isEquipment = isMed || isComp || isFurniture || isTools;
        let itemsList = vetItems;
        if (isNonVet) itemsList = nonVetItems;
        if (isMed) itemsList = medItems;
        else if (isComp) itemsList = compItems;
        else if (isFurniture) itemsList = furnitureItems;
        else if (isTools) itemsList = toolsItems;
        const itemNames = itemsList.map(i => i.name);
        
        if (isEditMode) {
            btnEdit.innerHTML = '<i data-feather="x" class="me-1"></i> ยกเลิกการแก้ไข';
            btnEdit.classList.remove('btn-primary');
            btnEdit.classList.add('btn-outline-danger');
            btnAddRow.style.display = 'block';
            btnSave.style.display = 'inline-block';
            if (btnClose) btnClose.style.display = 'none';

            document.getElementById('modalDocCostCenter').style.display = 'none';
            document.getElementById('modalDocCostCenterSelect').style.display = 'inline-block';

            // Re-create Table 1 for Edit
            let columns = [
                { type: 'dropdown', title: isEquipment ? 'เครื่องมือ' : 'ตำแหน่ง', width: 250, source: itemNames, autocomplete: true },
                { type: 'numeric', title: isEquipment ? 'ราคาซื้อ' : 'เงินเดือน', width: 100, mask: '#,##0' }
            ];
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
                contextMenu: function() { return true; }
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
        if (isEditMode && modalTable1 && modalTable2) {
            modalTable1.insertRow();
            modalTable2.insertRow();
        }
    }

    function saveDocument() {
        if (!modalTable1 || !isEditMode) return;

        const costCenterName = document.getElementById('modalDocCostCenterSelect').value;
        if (!costCenterName) {
            Swal.fire('แจ้งเตือน', 'กรุณาเลือก Cost Center', 'warning');
            return;
        }

        const isNonVet = currentDocType === 'NON VET';
        const isMed = currentDocType === 'Medical Equipment';
        const isComp = currentDocType === 'Computer Equipment';
        const isFurniture = currentDocType === 'Furniture';
        const isTools = currentDocType === 'Tools & Equipment';
        const isEquipment = isMed || isComp || isFurniture || isTools;
        const startCol = isNonVet ? 3 : 2;
        
        let rows = modalTable1.getData();
        let dataToSave = [];
        
        for (let i = 0; i < rows.length; i++) {
            let row = rows[i];
            let position = row[0];
            let salary = getNum(row[1]);
            let allowance = isNonVet ? getNum(row[2]) : 0;
            
            if (position && (salary > 0 || allowance > 0)) {
                let monthlyData = {
                    'jan': { 'headcount': getNum(row[startCol]), 'cost': getNum(row[startCol]) * (salary + allowance) },
                    'feb': { 'headcount': getNum(row[startCol+1]), 'cost': getNum(row[startCol+1]) * (salary + allowance) },
                    'mar': { 'headcount': getNum(row[startCol+2]), 'cost': getNum(row[startCol+2]) * (salary + allowance) },
                    'apr': { 'headcount': getNum(row[startCol+3]), 'cost': getNum(row[startCol+3]) * (salary + allowance) },
                    'may': { 'headcount': getNum(row[startCol+4]), 'cost': getNum(row[startCol+4]) * (salary + allowance) },
                    'jun': { 'headcount': getNum(row[startCol+5]), 'cost': getNum(row[startCol+5]) * (salary + allowance) },
                    'jul': { 'headcount': getNum(row[startCol+6]), 'cost': getNum(row[startCol+6]) * (salary + allowance) },
                    'aug': { 'headcount': getNum(row[startCol+7]), 'cost': getNum(row[startCol+7]) * (salary + allowance) },
                    'sep': { 'headcount': getNum(row[startCol+8]), 'cost': getNum(row[startCol+8]) * (salary + allowance) },
                    'oct': { 'headcount': getNum(row[startCol+9]), 'cost': getNum(row[startCol+9]) * (salary + allowance) },
                    'nov': { 'headcount': getNum(row[startCol+10]), 'cost': getNum(row[startCol+10]) * (salary + allowance) },
                    'dec': { 'headcount': getNum(row[startCol+11]), 'cost': getNum(row[startCol+11]) * (salary + allowance) }
                };
                
                let rowData = {};
                if (isEquipment) {
                    rowData = {
                        'item_name': position,
                        'purchase_price': salary,
                        'cost_center_name': costCenterName,
                        'monthly_data': monthlyData
                    };
                } else {
                    rowData = {
                        'position_name': position,
                        'salary': salary,
                        'cost_center_name': costCenterName,
                        'monthly_data': monthlyData
                    };
                    if (isNonVet) {
                        rowData['position_allowance'] = allowance;
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

        if (!adjModalInstance) {
            adjModalInstance = new bootstrap.Modal(document.getElementById('adjustmentDetailModal'));
        }
        adjModalInstance.show();

        document.getElementById('adjModalContent').style.display = 'none';
        document.getElementById('adjModalLoadingSpinner').style.display = 'block';

        const urlTemplate = window.APP_CONFIG.urls.apiAdjustmentDetail;
        const url = urlTemplate.replace('DOCNO', encodeURIComponent(docNo));

        fetch(url)
            .then(handleApiResponse)
            .then(result => {
                document.getElementById('adjModalLoadingSpinner').style.display = 'none';
                
                if (result.status === 'success') {
                    document.getElementById('adjModalDocNo').innerText = result.doc_info.document_no;
                    document.getElementById('adjModalDocBranch').innerText = result.doc_info.base_branch_id;
                    document.getElementById('adjModalDocCostCenter').innerText = result.doc_info.cost_center_name || '-';
                    populateCostCenterSelect(document.getElementById('adjModalDocCostCenterSelect'), result.doc_info.cost_center_name);
                    document.getElementById('adjModalDocCostCenterSelect').style.display = 'none';
                    document.getElementById('adjModalDocCostCenter').style.display = 'inline';
                    document.getElementById('adjModalDocCreator').innerText = result.doc_info.create_eid;
                    document.getElementById('adjModalDocDate').innerText = result.doc_info.create_date;

                    const adjModalContentEl = document.getElementById('adjModalContent');
                    adjModalContentEl.style.display = 'block';
                    adjModalContentEl.classList.remove('modal-content-fade-in');
                    void adjModalContentEl.offsetWidth;
                    adjModalContentEl.classList.add('modal-content-fade-in');

                    if (adjTable1) adjTable1.destroy();
                    if (adjTable2) adjTable2.destroy();
                    if (adjTable3) adjTable3.destroy();

                    const adjSkeletonHtml = '<div class="placeholder-glow p-3"><span class="placeholder col-12 eb-skeleton d-block"></span></div>';
                    document.getElementById('adjModalSpreadsheet1').innerHTML = adjSkeletonHtml;
                    document.getElementById('adjModalSpreadsheet2').innerHTML = adjSkeletonHtml;
                    document.getElementById('adjModalSpreadsheet3').innerHTML = adjSkeletonHtml;

                    const getNum = (val) => parseFloat(String(val).replace(/,/g, '')) || 0;
                    
                    const cols1 = [
                        { type: 'text', title: 'ตำแหน่งเดิม', width: 200, readOnly: true },
                        { type: 'text', title: 'ตำแหน่งใหม่', width: 200, readOnly: true },
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
                        { type: 'text', title: 'ตำแหน่งเดิม', width: 200, readOnly: true },
                        { type: 'text', title: 'ตำแหน่งใหม่', width: 200, readOnly: true },
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
                        { type: 'text', title: 'ตำแหน่งเดิม', width: 200, readOnly: true },
                        { type: 'text', title: 'ตำแหน่งใหม่', width: 200, readOnly: true },
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
                            item.old_position_name, item.new_position_name,
                            item.old_salary, item.old_allowance, item.old_salary + item.old_allowance,
                            item.new_salary, item.new_allowance, item.new_salary + item.new_allowance,
                            diffSal, diffAllow
                        ];
                        let r2 = [item.old_position_name, item.new_position_name, diffSal];
                        let r3 = [item.old_position_name, item.new_position_name, diffAllow];
                        
                        let sumHC = 0, sumSalCost = 0, sumAllowCost = 0;
                        const mKeys = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
                        mKeys.forEach(k => {
                            let hc = parseFloat((m[k] || {}).headcount) || 0;
                            r1.push(hc);
                            r2.push(hc * diffSal);
                            r3.push(hc * diffAllow);
                            sumHC += hc;
                            sumSalCost += hc * diffSal;
                            sumAllowCost += hc * diffAllow;
                        });
                        r1.push(sumHC);
                        r2.push(sumSalCost);
                        r3.push(sumAllowCost);
                        
                        data1.push(r1);
                        data2.push(r2);
                        data3.push(r3);
                    });

                    setTimeout(() => {
                        // Same reason as the document-detail modal: jspreadsheet
                        // appends rather than replaces, so clear the skeleton
                        // placeholders first or they stay visible next to the
                        // real grids.
                        document.getElementById('adjModalSpreadsheet1').innerHTML = '';
                        document.getElementById('adjModalSpreadsheet2').innerHTML = '';
                        document.getElementById('adjModalSpreadsheet3').innerHTML = '';
                        adjTable1 = jspreadsheet(document.getElementById('adjModalSpreadsheet1'), {
                            data: data1, columns: cols1, allowInsertRow: false, allowDeleteRow: false,
                            allowInsertColumn: false, allowManualInsertColumn: false, allowDeleteColumn: false,
                            tableOverflow: true, contextMenu: function() { return false; }, freezeColumns: 2
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
                    }, 50);

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
        
        x = parseInt(x);
        y = parseInt(y);
        
        const allAdjItems = [];
        vetItems.forEach(i => allAdjItems.push({...i, group: 'VET Manpower', position_allowance: 0}));
        nonVetItems.forEach(i => allAdjItems.push({...i, group: 'NON VET Manpower'}));
        
        const getSalary = (name) => { const m = allAdjItems.find(i => i.name === name); return m ? m.salary : 0; };
        const getAllowance = (name) => { const m = allAdjItems.find(i => i.name === name); return m ? m.position_allowance : 0; };
        const getNum = (val) => parseFloat(String(val).replace(/,/g, '')) || 0;

        let oldSal = getNum(adjTable1.getValueFromCoords(2, y));
        let oldAllow = getNum(adjTable1.getValueFromCoords(3, y));
        let newSal = getNum(adjTable1.getValueFromCoords(5, y));
        let newAllow = getNum(adjTable1.getValueFromCoords(6, y));

        if (x === 0) {
            oldSal = getSalary(value);
            oldAllow = getAllowance(value);
            adjTable1.setValueFromCoords(2, y, oldSal, true); 
            adjTable1.setValueFromCoords(3, y, oldAllow, true); 
        }
        if (x === 1) {
            newSal = getSalary(value);
            newAllow = getAllowance(value);
            adjTable1.setValueFromCoords(5, y, newSal, true); 
            adjTable1.setValueFromCoords(6, y, newAllow, true); 
        }
        if (x === 2) oldSal = getNum(value);
        if (x === 3) oldAllow = getNum(value);
        if (x === 5) newSal = getNum(value);
        if (x === 6) newAllow = getNum(value);

        if (x === 0 || x === 1 || x === 2 || x === 3 || x === 5 || x === 6) {
            let oldTotal = oldSal + oldAllow;
            let newTotal = newSal + newAllow;
            adjTable1.setValueFromCoords(4, y, oldTotal, true);
            adjTable1.setValueFromCoords(7, y, newTotal, true);
            
            adjTable1.setValueFromCoords(8, y, newSal - oldSal, true);
            adjTable1.setValueFromCoords(9, y, newAllow - oldAllow, true);
        }

        const rowData1 = adjTable1.getRowData(y);
        const oldPos = rowData1[0];
        const newPos = rowData1[1];
        const diffSal = getNum(rowData1[8]);
        const diffAllow = getNum(rowData1[9]);

        let sumHC = 0;
        for(let i = 10; i <= 21; i++) {
            sumHC += getNum(rowData1[i]);
        }
        adjTable1.setValueFromCoords(22, y, sumHC, true);

        adjTable2.setValueFromCoords(0, y, oldPos, true);
        adjTable2.setValueFromCoords(1, y, newPos, true);
        adjTable2.setValueFromCoords(2, y, diffSal, true);
        
        let sumSalCost = 0;
        for(let i = 10; i <= 21; i++) {
            const count = getNum(rowData1[i]);
            const cost = count * diffSal;
            adjTable2.setValueFromCoords(i - 7, y, cost, true);
            sumSalCost += cost;
        }
        adjTable2.setValueFromCoords(15, y, sumSalCost, true);

        adjTable3.setValueFromCoords(0, y, oldPos, true);
        adjTable3.setValueFromCoords(1, y, newPos, true);
        adjTable3.setValueFromCoords(2, y, diffAllow, true);
        
        let sumAllowCost = 0;
        for(let i = 10; i <= 21; i++) {
            const count = getNum(rowData1[i]);
            const cost = count * diffAllow;
            adjTable3.setValueFromCoords(i - 7, y, cost, true);
            sumAllowCost += cost;
        }
        adjTable3.setValueFromCoords(15, y, sumAllowCost, true);
        
        isAdjUpdating = false;
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

        if (isAdjEditMode) {
            btnEdit.innerHTML = '<i data-feather="x" class="me-1"></i> ยกเลิกการแก้ไข';
            btnEdit.classList.remove('btn-primary', 'text-white');
            btnEdit.classList.add('btn-outline-danger');
            btnAddRow.style.display = 'block';
            btnSave.style.display = 'inline-block';
            if (btnClose) btnClose.style.display = 'none';

            document.getElementById('adjModalDocCostCenter').style.display = 'none';
            document.getElementById('adjModalDocCostCenterSelect').style.display = 'inline-block';

            const cols1 = [
                { type: 'dropdown', title: 'ตำแหน่งเดิม', width: 200, source: allAdjItems, autocomplete: true },
                { type: 'dropdown', title: 'ตำแหน่งใหม่', width: 200, source: allAdjItems, autocomplete: true },
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
                freezeColumns: 2,
                onchange: onAdjSpreadsheetChange,
                contextMenu: function() { return true; }
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
        if (isAdjEditMode && adjTable1 && adjTable2 && adjTable3) {
            adjTable1.insertRow();
            adjTable2.insertRow();
            adjTable3.insertRow();
        }
    }

    function saveAdjDocument() {
        if (!adjTable1 || !isAdjEditMode) return;

        const costCenterName = document.getElementById('adjModalDocCostCenterSelect').value;
        if (!costCenterName) {
            Swal.fire('แจ้งเตือน', 'กรุณาเลือก Cost Center', 'warning');
            return;
        }

        const getNum = (val) => parseFloat(String(val).replace(/,/g, '')) || 0;
        let rows = adjTable1.getData();
        let dataToSave = [];

        for (let i = 0; i < rows.length; i++) {
            let row = rows[i];
            let oldPos = row[0];
            let newPos = row[1];
            let oldSal = getNum(row[2]);
            let oldAllow = getNum(row[3]);
            let newSal = getNum(row[5]);
            let newAllow = getNum(row[6]);

            if (oldPos && newPos) {
                let diffSal = newSal - oldSal;
                let diffAllow = newAllow - oldAllow;
                const monthKeys = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
                let monthlyData = {};
                monthKeys.forEach((key, idx) => {
                    const headcount = getNum(row[10 + idx]);
                    const salaryCost = headcount * diffSal;
                    const allowanceCost = headcount * diffAllow;
                    monthlyData[key] = {
                        headcount: headcount,
                        // BudgetMonthlyDetail only has one 'cost' column, so the
                        // two per-month budgets shown on screen are combined
                        // here into the single total that actually gets persisted
                        // (see budget_add_adjustment.html for the same fix on create).
                        cost: salaryCost + allowanceCost,
                        salary_diff_cost: salaryCost,
                        allowance_diff_cost: allowanceCost,
                    };
                });

                dataToSave.push({
                    'old_position_name': oldPos,
                    'new_position_name': newPos,
                    'old_salary': oldSal,
                    'old_allowance': oldAllow,
                    'new_salary': newSal,
                    'new_allowance': newAllow,
                    'cost_center_name': costCenterName,
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

    // ---- Public API ----
    return {
        fetchDocuments: fetchDocuments,
        applyTypeFilter: applyTypeFilter,
        viewDocumentDetails: viewDocumentDetails,
        toggleEditMode: toggleEditMode,
        addSpreadsheetRow: addSpreadsheetRow,
        saveDocument: saveDocument,
        viewAdjustmentDetails: viewAdjustmentDetails,
        toggleAdjEditMode: toggleAdjEditMode,
        addAdjSpreadsheetRow: addAdjSpreadsheetRow,
        saveAdjDocument: saveAdjDocument
    };
})();

// Expose to window for inline onclick handlers
window.fetchDocuments = BudgetApp.fetchDocuments;
window.applyTypeFilter = BudgetApp.applyTypeFilter;
window.viewDocumentDetails = BudgetApp.viewDocumentDetails;
window.toggleEditMode = BudgetApp.toggleEditMode;
window.addSpreadsheetRow = BudgetApp.addSpreadsheetRow;
window.saveDocument = BudgetApp.saveDocument;
window.viewAdjustmentDetails = BudgetApp.viewAdjustmentDetails;
window.toggleAdjEditMode = BudgetApp.toggleAdjEditMode;
window.addAdjSpreadsheetRow = BudgetApp.addAdjSpreadsheetRow;
window.saveAdjDocument = BudgetApp.saveAdjDocument;

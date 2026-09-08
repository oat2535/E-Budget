from functools import wraps
from django.shortcuts import render, redirect
from django.http import JsonResponse
import json
from django.db import connections, transaction
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Max
from master_data.models import ebudget_budget_item_master, ebudget_budget_category_master
from budget_app.models import ebudget_vet_manpower, ebudget_non_vet_manpower, ebudget_position_adjustment, ebudget_medical_equipment, ebudget_computer_equipment, ebudget_furniture, ebudget_tools_equipment
from budget_app.services import BudgetService

def login_required_json(view_func):
    """Like login_required, but for fetch()/AJAX endpoints: an expired or
    missing session returns a 401 JSON body instead of redirecting to the
    login page HTML, which the caller can't parse as JSON."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse(
                {'status': 'error', 'code': 'session_expired', 'message': 'เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่'},
                status=401,
            )
        return view_func(request, *args, **kwargs)
    return wrapper

# Usernames allowed to view/edit budget documents across every branch,
# instead of being scoped to their own base_site_branch_id.
ALL_BRANCH_USERNAMES = {'nattchai_u', 'kanchana_a', 'pattida_y'}

def get_branch_filter_kwargs(request):
    """Filter kwargs scoping budget-document queries to the current user's
    own branch. Empty dict for ALL_BRANCH_USERNAMES (no scoping). The
    branch id is looked up from imedx once per session (cached in
    request.session) rather than on every request. Fails closed: an
    unknown branch (None) filters to base_branch_id=None, matching no
    real records, instead of showing everything."""
    if request.user.username in ALL_BRANCH_USERNAMES:
        return {}
    if 'base_site_branch_id' not in request.session:
        request.session['base_site_branch_id'] = BudgetService.get_branch_id_from_imedx(request.user.username)
    return {'base_branch_id': request.session['base_site_branch_id']}

def login_view(request):
    if request.method == 'POST':
        employee_id = request.POST.get('employee_id')
        password = request.POST.get('password')
        
        user = authenticate(request, username=employee_id, password=password)
        if user is not None:
            login(request, user)
            return redirect('budget_list')
        else:
            messages.error(request, 'รหัสพนักงานหรือรหัสผ่านไม่ถูกต้อง')
            
    return render(request, 'budget_app/login.html')

@login_required
def budget_list_view(request):
    categories = ebudget_budget_category_master.objects.all().order_by('category_code')
    # If no categories, create some dummy data for display
    if not categories.exists():
        c1, _ = ebudget_budget_category_master.objects.get_or_create(category_code='C01', category_name='Category 1')
        c2, _ = ebudget_budget_category_master.objects.get_or_create(category_code='C02', category_name='Category 2')
        c3, _ = ebudget_budget_category_master.objects.get_or_create(category_code='C03', category_name='Category 3')
        categories = [c1, c2, c3]
        
    vet_items = list(ebudget_budget_item_master.objects.filter(category_id=1, sub_category_id=1).values('id', 'item_name', 'salary'))
    vet_items_list = []
    for item in vet_items:
        vet_items_list.append({
            'id': item['item_name'],
            'name': item['item_name'],
            'salary': float(item['salary'])
        })

    non_vet_items = list(ebudget_budget_item_master.objects.filter(category_id=1, sub_category_id=2).values('id', 'item_name', 'salary', 'position_allowance'))
    non_vet_items_list = []
    for item in non_vet_items:
        non_vet_items_list.append({
            'id': item['item_name'],
            'name': item['item_name'],
            'salary': float(item['salary']),
            'position_allowance': float(item.get('position_allowance') or 0)
        })

    med_items = list(ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=4).values('item_name', 'purchase_price'))
    med_items_list = []
    for item in med_items:
        med_items_list.append({
            'name': item['item_name'],
            'purchase_price': float(item.get('purchase_price') or 0)
        })

    comp_items = list(ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=5).values('item_name', 'purchase_price'))
    comp_items_list = []
    for item in comp_items:
        comp_items_list.append({
            'name': item['item_name'],
            'purchase_price': float(item.get('purchase_price') or 0)
        })

    furniture_items = list(ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=6).values('item_name', 'purchase_price'))
    furniture_items_list = []
    for item in furniture_items:
        furniture_items_list.append({
            'name': item['item_name'],
            'purchase_price': float(item.get('purchase_price') or 0)
        })

    tools_items = list(ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=7).values('item_name', 'purchase_price'))
    tools_items_list = []
    for item in tools_items:
        tools_items_list.append({
            'name': item['item_name'],
            'purchase_price': float(item.get('purchase_price') or 0)
        })

    return render(request, 'budget_app/budget_list.html', {
        'categories': categories,
        'items_vet_json': vet_items_list,
        'items_non_vet_json': non_vet_items_list,
        'items_med_json': med_items_list,
        'items_comp_json': comp_items_list,
        'items_furniture_json': furniture_items_list,
        'items_tools_json': tools_items_list
    })

@login_required
def budget_add_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            username = request.user.username
            branch_id = BudgetService.get_branch_id_from_imedx(username)
            doc_no = BudgetService.generate_document_no('VET')

            with transaction.atomic():
                for item in data:
                    master_obj, gl_obj = BudgetService.get_master_fks(item['position_name'])
                    obj = ebudget_vet_manpower.objects.create(
                        position_name=item['position_name'],
                        salary=item['salary'],
                        create_eid=username,
                        base_branch_id=branch_id,
                        document_no=doc_no,
                        item_master=master_obj,
                        general_ledger=gl_obj
                    )
                    BudgetService.save_monthly_data(obj, 'VET', item['monthly_data'])
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

    items = list(ebudget_budget_item_master.objects.filter(category_id=1, sub_category_id=1).values('id', 'item_name', 'salary'))
    if not items:
        # Dummy data
        i1 = ebudget_budget_item_master.objects.create(item_name="แพทย์เฉพาะทาง", salary=50000)
        i2 = ebudget_budget_item_master.objects.create(item_name="พยาบาลวิชาชีพ", salary=25000)
        items = list(ebudget_budget_item_master.objects.values('id', 'item_name', 'salary'))
    items_list = []
    for item in items:
        items_list.append({
            'id': item['item_name'],
            'name': item['item_name'],
            'salary': float(item['salary'])
        })
    
    return render(request, 'budget_app/budget_add.html', {'items_json': items_list})

@login_required
def budget_add_non_vet_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            username = request.user.username
            
            branch_id = BudgetService.get_branch_id_from_imedx(username)
            doc_no = BudgetService.generate_document_no('NON VET')

            with transaction.atomic():
                for item in data:
                    master_obj, gl_obj = BudgetService.get_master_fks(item['position_name'])
                    obj = ebudget_non_vet_manpower.objects.create(
                        position_name=item['position_name'],
                        salary=item['salary'],
                        position_allowance=item.get('position_allowance', 0),
                        create_eid=username,
                        base_branch_id=branch_id,
                        document_no=doc_no,
                        item_master=master_obj,
                        general_ledger=gl_obj
                    )
                    BudgetService.save_monthly_data(obj, 'NON VET', item['monthly_data'])
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

    items = list(ebudget_budget_item_master.objects.filter(category_id=1, sub_category_id=2).values('id', 'item_name', 'salary', 'position_allowance'))
    items_list = []
    for item in items:
        items_list.append({
            'id': item['item_name'],
            'name': item['item_name'],
            'salary': float(item['salary']),
            'position_allowance': float(item.get('position_allowance') or 0)
        })
    
    return render(request, 'budget_app/budget_add_non_vet.html', {'items_json': items_list})

@login_required_json
def get_budget_documents_api(request, category_code):
    branch_filter = get_branch_filter_kwargs(request)
    if category_code == 'C01':
        # Fetch VET — Group by document_no only to avoid row-per-row timestamps splitting documents
        vet_docs = ebudget_vet_manpower.objects.filter(**branch_filter).values('document_no').annotate(
            total_positions=Count('id'),
            create_date=Max('create_date'),
            create_eid=Max('create_eid')
        )

        # Fetch NON VET
        non_vet_docs = ebudget_non_vet_manpower.objects.filter(**branch_filter).values('document_no').annotate(
            total_positions=Count('id'),
            create_date=Max('create_date'),
            create_eid=Max('create_eid')
        )

        # Fetch Position Adjustment
        adj_docs = ebudget_position_adjustment.objects.filter(**branch_filter).values('document_no').annotate(
            total_positions=Count('id'),
            create_date=Max('create_date'),
            create_eid=Max('create_eid')
        )
        
        results = []
        for doc in vet_docs:
            results.append({
                'document_no': doc['document_no'] or '-',
                'create_date_raw': doc['create_date'].isoformat() if doc['create_date'] else '',
                'create_date': doc['create_date'].strftime('%d/%m/%Y %H:%M') if doc['create_date'] else '-',
                'create_eid': doc['create_eid'] or '-',
                'total_positions': doc['total_positions'],
                'type': 'VET'
            })
            
        for doc in non_vet_docs:
            results.append({
                'document_no': doc['document_no'] or '-',
                'create_date_raw': doc['create_date'].isoformat() if doc['create_date'] else '',
                'create_date': doc['create_date'].strftime('%d/%m/%Y %H:%M') if doc['create_date'] else '-',
                'create_eid': doc['create_eid'] or '-',
                'total_positions': doc['total_positions'],
                'type': 'NON VET'
            })
            
        for doc in adj_docs:
            results.append({
                'document_no': doc['document_no'] or '-',
                'create_date_raw': doc['create_date'].isoformat() if doc['create_date'] else '',
                'create_date': doc['create_date'].strftime('%d/%m/%Y %H:%M') if doc['create_date'] else '-',
                'create_eid': doc['create_eid'] or '-',
                'total_positions': doc['total_positions'],
                'type': 'Position Adjustment'
            })
            
        results.sort(key=lambda x: x['create_date_raw'], reverse=True)
        return JsonResponse({'status': 'success', 'data': results})
    
    elif category_code == 'C02':
        # Fetch Medical Equipment — Group by document_no only
        med_docs = ebudget_medical_equipment.objects.filter(**branch_filter).values('document_no').annotate(
            total_positions=Count('id'),
            create_date=Max('create_date'),
            create_eid=Max('create_eid')
        )

        comp_docs = ebudget_computer_equipment.objects.filter(**branch_filter).values('document_no').annotate(
            total_positions=Count('id'),
            create_date=Max('create_date'),
            create_eid=Max('create_eid')
        )

        furniture_docs = ebudget_furniture.objects.filter(**branch_filter).values('document_no').annotate(
            total_positions=Count('id'),
            create_date=Max('create_date'),
            create_eid=Max('create_eid')
        )

        tools_docs = ebudget_tools_equipment.objects.filter(**branch_filter).values('document_no').annotate(
            total_positions=Count('id'),
            create_date=Max('create_date'),
            create_eid=Max('create_eid')
        )

        results = []
        for doc in med_docs:
            results.append({
                'document_no': doc['document_no'] or '-',
                'create_date_raw': doc['create_date'].isoformat() if doc['create_date'] else '',
                'create_date': doc['create_date'].strftime('%d/%m/%Y %H:%M') if doc['create_date'] else '-',
                'create_eid': doc['create_eid'] or '-',
                'total_positions': doc['total_positions'],
                'type': 'Medical Equipment'
            })
            
        for doc in comp_docs:
            results.append({
                'document_no': doc['document_no'] or '-',
                'create_date_raw': doc['create_date'].isoformat() if doc['create_date'] else '',
                'create_date': doc['create_date'].strftime('%d/%m/%Y %H:%M') if doc['create_date'] else '-',
                'create_eid': doc['create_eid'] or '-',
                'total_positions': doc['total_positions'],
                'type': 'Computer Equipment'
            })

        for doc in furniture_docs:
            results.append({
                'document_no': doc['document_no'] or '-',
                'create_date_raw': doc['create_date'].isoformat() if doc['create_date'] else '',
                'create_date': doc['create_date'].strftime('%d/%m/%Y %H:%M') if doc['create_date'] else '-',
                'create_eid': doc['create_eid'] or '-',
                'total_positions': doc['total_positions'],
                'type': 'Furniture'
            })

        for doc in tools_docs:
            results.append({
                'document_no': doc['document_no'] or '-',
                'create_date_raw': doc['create_date'].isoformat() if doc['create_date'] else '',
                'create_date': doc['create_date'].strftime('%d/%m/%Y %H:%M') if doc['create_date'] else '-',
                'create_eid': doc['create_eid'] or '-',
                'total_positions': doc['total_positions'],
                'type': 'Tools & Equipment'
            })

        results.sort(key=lambda x: x['create_date_raw'], reverse=True)
        return JsonResponse({'status': 'success', 'data': results})

    elif category_code == 'C03':
        # C03 — currently no dedicated tables, return empty or extend later
        return JsonResponse({'status': 'success', 'data': []})
        
    return JsonResponse({'status': 'error', 'message': 'ไม่มีข้อมูลสำหรับหมวดหมู่นี้'})

@login_required_json
def get_document_detail_api(request, doc_type, doc_no):
    branch_filter = get_branch_filter_kwargs(request)
    if doc_type == 'VET':
        items = ebudget_vet_manpower.objects.filter(document_no=doc_no, **branch_filter)
    elif doc_type == 'NON VET':
        items = ebudget_non_vet_manpower.objects.filter(document_no=doc_no, **branch_filter)
    elif doc_type == 'Position Adjustment':
        items = ebudget_position_adjustment.objects.filter(document_no=doc_no, **branch_filter)
    elif doc_type == 'Medical Equipment':
        items = ebudget_medical_equipment.objects.filter(document_no=doc_no, **branch_filter)
    elif doc_type == 'Computer Equipment':
        items = ebudget_computer_equipment.objects.filter(document_no=doc_no, **branch_filter)
    elif doc_type == 'Furniture':
        items = ebudget_furniture.objects.filter(document_no=doc_no, **branch_filter)
    elif doc_type == 'Tools & Equipment':
        items = ebudget_tools_equipment.objects.filter(document_no=doc_no, **branch_filter)
    else:
        return JsonResponse({'status': 'error', 'message': 'ประเภทเอกสารไม่ถูกต้อง'})

    if not items.exists():
        return JsonResponse({'status': 'error', 'message': 'ไม่พบเอกสารนี้'})

    first_item = items.first()
    doc_info = {
        'document_no': first_item.document_no,
        'create_date': first_item.create_date.strftime('%d/%m/%Y %H:%M') if first_item.create_date else '-',
        'create_eid': first_item.create_eid,
        'type': doc_type,
        'base_branch_id': first_item.base_branch_id or '-'
    }

    manpower_list = []
    for item in items:
        if doc_type == 'Position Adjustment':
            data = {
                'old_position_name': item.old_position_name,
                'new_position_name': item.new_position_name,
                'old_salary': float(item.old_salary),
                'old_allowance': float(item.old_allowance),
                'new_salary': float(item.new_salary),
                'new_allowance': float(item.new_allowance),
                'monthly_data': item.monthly_data_dict
            }
        elif doc_type == 'Medical Equipment' or doc_type == 'Computer Equipment' or doc_type == 'Furniture' or doc_type == 'Tools & Equipment':
            data = {
                'item_name': item.item_name,
                'purchase_price': float(item.purchase_price),
                'monthly_data': item.monthly_data_dict
            }
        else:
            data = {
                'position_name': item.position_name,
                'salary': float(item.salary),
                'monthly_data': item.monthly_data_dict
            }
            if doc_type == 'NON VET':
                data['position_allowance'] = float(getattr(item, 'position_allowance', 0))
        manpower_list.append(data)

    return JsonResponse({
        'status': 'success',
        'doc_info': doc_info,
        'manpower_list': manpower_list
    })

@login_required_json
def update_document_api(request, doc_type, doc_no):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'})
        
    if request.user.username not in ALL_BRANCH_USERNAMES:
        return JsonResponse({'status': 'error', 'message': 'ไม่มีสิทธิ์ในการแก้ไขข้อมูล'})
        
    try:
        data = json.loads(request.body)
        username = request.user.username
        
        if doc_type == 'VET':
            model_class = ebudget_vet_manpower
        elif doc_type == 'NON VET':
            model_class = ebudget_non_vet_manpower
        elif doc_type == 'Position Adjustment':
            model_class = ebudget_position_adjustment
        elif doc_type == 'Medical Equipment':
            model_class = ebudget_medical_equipment
        elif doc_type == 'Computer Equipment':
            model_class = ebudget_computer_equipment
        elif doc_type == 'Furniture':
            model_class = ebudget_furniture
        elif doc_type == 'Tools & Equipment':
            model_class = ebudget_tools_equipment
        else:
            return JsonResponse({'status': 'error', 'message': 'ประเภทเอกสารไม่ถูกต้อง'})
            
        existing_items = model_class.objects.filter(document_no=doc_no)
        if not existing_items.exists():
            return JsonResponse({'status': 'error', 'message': 'ไม่พบเอกสาร'})
            
        first_item = existing_items.first()
        create_date = first_item.create_date
        create_eid = first_item.create_eid
        base_branch_id = first_item.base_branch_id
        
        with transaction.atomic():
            existing_items.delete()
            
            for item in data:
                if doc_type == 'Position Adjustment':
                    master_obj, gl_obj = BudgetService.get_master_fks(item['new_position_name'])
                    obj = model_class.objects.create(
                        old_position_name=item['old_position_name'],
                        new_position_name=item['new_position_name'],
                        old_salary=item['old_salary'],
                        old_allowance=item['old_allowance'],
                        new_salary=item['new_salary'],
                        new_allowance=item['new_allowance'],
                        base_branch_id=base_branch_id,
                        document_no=doc_no,
                        create_date=create_date,
                        create_eid=create_eid,
                        modify_eid=username,
                        item_master=master_obj,
                        general_ledger=gl_obj
                    )

                    BudgetService.save_monthly_data(obj, doc_type, item['monthly_data'])
                elif doc_type == 'VET':
                    master_obj, gl_obj = BudgetService.get_master_fks(item['position_name'])
                    obj = model_class.objects.create(
                        position_name=item['position_name'],
                        salary=item['salary'],
                        base_branch_id=base_branch_id,
                        document_no=doc_no,
                        create_date=create_date,
                        create_eid=create_eid,
                        modify_eid=username,
                        item_master=master_obj,
                        general_ledger=gl_obj
                    )

                    BudgetService.save_monthly_data(obj, doc_type, item['monthly_data'])
                elif doc_type == 'Medical Equipment' or doc_type == 'Computer Equipment' or doc_type == 'Furniture' or doc_type == 'Tools & Equipment':
                    master_obj, gl_obj = BudgetService.get_master_fks(item['item_name'])
                    obj = model_class.objects.create(
                        item_name=item['item_name'],
                        purchase_price=item['purchase_price'],
                        base_branch_id=base_branch_id,
                        document_no=doc_no,
                        create_date=create_date,
                        create_eid=create_eid,
                        modify_eid=username,
                        item_master=master_obj,
                        general_ledger=gl_obj
                    )

                    BudgetService.save_monthly_data(obj, doc_type, item['monthly_data'])
                else:
                    master_obj, gl_obj = BudgetService.get_master_fks(item['position_name'])
                    obj = model_class.objects.create(
                        position_name=item['position_name'],
                        salary=item['salary'],
                        position_allowance=item.get('position_allowance', 0),
                        base_branch_id=base_branch_id,
                        document_no=doc_no,
                        create_date=create_date,
                        create_eid=create_eid,
                        modify_eid=username,
                        item_master=master_obj,
                        general_ledger=gl_obj
                    )
                    BudgetService.save_monthly_data(obj, doc_type, item['monthly_data'])
                
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required
def budget_add_adjustment_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            username = request.user.username
            
            # Fetch branch_id automatically from imedx
            branch_id = None
            try:
                with connections['imedx'].cursor() as cursor:
                    cursor.execute("""
                        SELECT bsp.base_site_branch_id
                        FROM employee emp 
                        LEFT JOIN base_service_point bsp ON emp.base_service_point_id = bsp.base_service_point_id
                        WHERE emp.employee_id = %s AND emp.active = '1'
                    """, [username])
                    row = cursor.fetchone()
                    if row:
                        branch_id = row[0]
            except Exception as e:
                print(f"Error fetching branch_id: {e}")

            doc_no = BudgetService.generate_document_no('Position Adjustment')

            with transaction.atomic():
                for item in data:
                    master_obj, gl_obj = BudgetService.get_master_fks(item['new_position_name'])
                    obj = ebudget_position_adjustment.objects.create(
                        old_position_name=item['old_position_name'],
                        new_position_name=item['new_position_name'],
                        old_salary=item['old_salary'],
                        old_allowance=item['old_allowance'],
                        new_salary=item['new_salary'],
                        new_allowance=item['new_allowance'],
                        create_eid=username,
                        base_branch_id=branch_id,
                        document_no=doc_no,
                        item_master=master_obj,
                        general_ledger=gl_obj
                    )
                    BudgetService.save_monthly_data(obj, 'Position Adjustment', item['monthly_data'])
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

    # Fetch master data for dropdowns
    items_list = []
    
    # VET items
    vet_items = list(ebudget_budget_item_master.objects.filter(category_id=1, sub_category_id=1).values('item_name', 'salary'))
    for item in vet_items:
        items_list.append({
            'id': item['item_name'],
            'name': item['item_name'],
            'group': 'VET Manpower',
            'salary': float(item['salary']),
            'position_allowance': 0
        })
        
    # NON VET items
    non_vet_items = list(ebudget_budget_item_master.objects.filter(category_id=1, sub_category_id=2).values('item_name', 'salary', 'position_allowance'))
    for item in non_vet_items:
        items_list.append({
            'id': item['item_name'],
            'name': item['item_name'],
            'group': 'NON VET Manpower',
            'salary': float(item['salary']),
            'position_allowance': float(item.get('position_allowance') or 0)
        })
    
    return render(request, 'budget_app/budget_add_adjustment.html', {'items_json': items_list})

@login_required
def budget_add_medical_equipment_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            username = request.user.username
            
            branch_id = None
            try:
                with connections['imedx'].cursor() as cursor:
                    cursor.execute("""
                        SELECT bsp.base_site_branch_id
                        FROM employee emp 
                        LEFT JOIN base_service_point bsp ON emp.base_service_point_id = bsp.base_service_point_id
                        WHERE emp.employee_id = %s AND emp.active = '1'
                    """, [username])
                    row = cursor.fetchone()
                    if row:
                        branch_id = row[0]
            except Exception as e:
                print(f"Error fetching branch_id: {e}")

            doc_no = BudgetService.generate_document_no('Medical Equipment')

            with transaction.atomic():
                for item in data:
                    master_obj, gl_obj = BudgetService.get_master_fks(item['item_name'])
                    obj = ebudget_medical_equipment.objects.create(
                        item_name=item['item_name'],
                        purchase_price=item['purchase_price'],
                        create_eid=username,
                        base_branch_id=branch_id,
                        document_no=doc_no,
                        item_master=master_obj,
                        general_ledger=gl_obj
                    )
                    BudgetService.save_monthly_data(obj, 'Medical Equipment', item['monthly_data'])
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

    items = list(ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=4).values('item_name', 'purchase_price'))
    items_list = []
    for item in items:
        items_list.append({
            'name': item['item_name'],
            'purchase_price': float(item.get('purchase_price') or 0)
        })
    
    return render(request, 'budget_app/budget_add_medical_equipment.html', {'items_json': items_list})

@login_required
def budget_add_computer_equipment_view(request):
    from budget_app.models import ebudget_computer_equipment
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            username = request.user.username
            
            branch_id = None
            try:
                with connections['imedx'].cursor() as cursor:
                    cursor.execute("""
                        SELECT bsp.base_site_branch_id
                        FROM employee emp 
                        LEFT JOIN base_service_point bsp ON emp.base_service_point_id = bsp.base_service_point_id
                        WHERE emp.employee_id = %s AND emp.active = '1'
                    """, [username])
                    row = cursor.fetchone()
                    if row:
                        branch_id = row[0]
            except Exception as e:
                print(f"Error fetching branch_id: {e}")

            doc_no = BudgetService.generate_document_no('Computer Equipment')

            with transaction.atomic():
                for item in data:
                    master_obj, gl_obj = BudgetService.get_master_fks(item['item_name'])
                    obj = ebudget_computer_equipment.objects.create(
                        item_name=item['item_name'],
                        purchase_price=item['purchase_price'],
                        create_eid=username,
                        base_branch_id=branch_id,
                        document_no=doc_no,
                        item_master=master_obj,
                        general_ledger=gl_obj
                    )
                    BudgetService.save_monthly_data(obj, 'Computer Equipment', item['monthly_data'])
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

    items = list(ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=5).values('item_name', 'purchase_price'))
    items_list = []
    for item in items:
        items_list.append({
            'name': item['item_name'],
            'purchase_price': float(item.get('purchase_price') or 0)
        })

    return render(request, 'budget_app/budget_add_computer_equipment.html', {'items_json': items_list})

@login_required
def budget_add_furniture_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            username = request.user.username

            branch_id = None
            try:
                with connections['imedx'].cursor() as cursor:
                    cursor.execute("""
                        SELECT bsp.base_site_branch_id
                        FROM employee emp
                        LEFT JOIN base_service_point bsp ON emp.base_service_point_id = bsp.base_service_point_id
                        WHERE emp.employee_id = %s AND emp.active = '1'
                    """, [username])
                    row = cursor.fetchone()
                    if row:
                        branch_id = row[0]
            except Exception as e:
                print(f"Error fetching branch_id: {e}")

            doc_no = BudgetService.generate_document_no('Furniture')

            with transaction.atomic():
                for item in data:
                    master_obj, gl_obj = BudgetService.get_master_fks(item['item_name'])
                    obj = ebudget_furniture.objects.create(
                        item_name=item['item_name'],
                        purchase_price=item['purchase_price'],
                        create_eid=username,
                        base_branch_id=branch_id,
                        document_no=doc_no,
                        item_master=master_obj,
                        general_ledger=gl_obj
                    )
                    BudgetService.save_monthly_data(obj, 'Furniture', item['monthly_data'])
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

    items = list(ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=6).values('item_name', 'purchase_price'))
    items_list = []
    for item in items:
        items_list.append({
            'name': item['item_name'],
            'purchase_price': float(item.get('purchase_price') or 0)
        })

    return render(request, 'budget_app/budget_add_furniture.html', {'items_json': items_list})

@login_required
def budget_add_tools_equipment_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            username = request.user.username

            branch_id = None
            try:
                with connections['imedx'].cursor() as cursor:
                    cursor.execute("""
                        SELECT bsp.base_site_branch_id
                        FROM employee emp
                        LEFT JOIN base_service_point bsp ON emp.base_service_point_id = bsp.base_service_point_id
                        WHERE emp.employee_id = %s AND emp.active = '1'
                    """, [username])
                    row = cursor.fetchone()
                    if row:
                        branch_id = row[0]
            except Exception as e:
                print(f"Error fetching branch_id: {e}")

            doc_no = BudgetService.generate_document_no('Tools & Equipment')

            with transaction.atomic():
                for item in data:
                    master_obj, gl_obj = BudgetService.get_master_fks(item['item_name'])
                    obj = ebudget_tools_equipment.objects.create(
                        item_name=item['item_name'],
                        purchase_price=item['purchase_price'],
                        create_eid=username,
                        base_branch_id=branch_id,
                        document_no=doc_no,
                        item_master=master_obj,
                        general_ledger=gl_obj
                    )
                    BudgetService.save_monthly_data(obj, 'Tools & Equipment', item['monthly_data'])
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

    items = list(ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=7).values('item_name', 'purchase_price'))
    items_list = []
    for item in items:
        items_list.append({
            'name': item['item_name'],
            'purchase_price': float(item.get('purchase_price') or 0)
        })

    return render(request, 'budget_app/budget_add_tools_equipment.html', {'items_json': items_list})

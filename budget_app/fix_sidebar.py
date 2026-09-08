import re

filepath = 'c:/E-Budget/budget_app/templates/budget_app/base.html'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = '<div class="nav accordion" id="accordionSidenav">'
end_marker = '<!-- Sidenav Footer-->'

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx != -1 and end_idx != -1:
    new_menu = """<div class="nav accordion" id="accordionSidenav">
        <!-- Sidenav Menu Heading (Core)-->
        <div class="sidenav-menu-heading">E-Budget</div>
        
        <a class="nav-link" href="{% url 'budget_list' %}">
            <div class="nav-link-icon"><i data-feather="list"></i></div>
            Budget List
        </a>
        
        <a class="nav-link" href="{% url 'budget_add' %}">
            <div class="nav-link-icon"><i data-feather="plus-circle"></i></div>
            Add Budget
        </a>
    </div>
    """
    new_content = content[:start_idx] + new_menu + content[end_idx:]
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Sidebar updated successfully.")
else:
    print("Could not find markers.")

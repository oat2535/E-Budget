import re

f = 'c:/E-Budget/budget_app/templates/budget_app/base.html'
with open(f, 'r', encoding='utf-8') as file:
    txt = file.read()

# Remove Search Form
txt = re.sub(r'<form class="form-inline me-auto.*?</form>', '', txt, flags=re.DOTALL)
# Remove Docs Dropdown
txt = re.sub(r'<!-- Documentation Dropdown-->.*?<!-- Alerts Dropdown-->', '<!-- Alerts Dropdown-->', txt, flags=re.DOTALL)
# Remove Alerts Dropdown
txt = re.sub(r'<!-- Alerts Dropdown-->.*?<!-- Messages Dropdown-->', '<!-- Messages Dropdown-->', txt, flags=re.DOTALL)
# Remove Messages Dropdown
txt = re.sub(r'<!-- Messages Dropdown-->.*?<!-- User Dropdown-->', '<!-- User Dropdown-->', txt, flags=re.DOTALL)

# Change profile-1 to profile-2
txt = txt.replace('profile-1.png', 'profile-2.png')
txt = txt.replace('Valerie Luna', 'Admin')

# Pin sidebar footer to bottom
txt = txt.replace('class="sidenav-menu"', 'class="sidenav-menu d-flex flex-column justify-content-between"')
# If there are nested divs inside sidenav-menu that need to group the top items together, 
# we should wrap the menu items in a div. 
# `<div class="nav accordion" id="accordionSidenav">` is the main container. Let's make sure it flex-grows if needed.
txt = txt.replace('class="nav accordion"', 'class="nav accordion flex-grow-1"')

with open(f, 'w', encoding='utf-8') as file:
    file.write(txt)

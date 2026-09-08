import re
import os

files_to_fix = [
    'c:/E-Budget/budget_app/templates/budget_app/login.html',
    'c:/E-Budget/budget_app/templates/budget_app/base.html'
]

for fpath in files_to_fix:
    with open(fpath, 'r', encoding='utf-8') as f:
        txt = f.read()
    
    txt = '{% load static %}\n' + txt
    txt = re.sub(r'href="css/', 'href="{% static \'budget_app/css/', txt)
    txt = re.sub(r'src="js/', 'src="{% static \'budget_app/js/', txt)
    txt = re.sub(r'href="assets/', 'href="{% static \'budget_app/assets/', txt)
    txt = re.sub(r'src="assets/', 'src="{% static \'budget_app/assets/', txt)
    
    txt = txt.replace('.css"', '.css\' %}"')
    txt = txt.replace('.js"', '.js\' %}"')
    txt = txt.replace('.png"', '.png\' %}"')
    
    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(txt)

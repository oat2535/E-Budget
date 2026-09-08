import os
import glob
import re

html_files = glob.glob('c:/E-Budget/budget_app/templates/budget_app/*.html')

for filepath in html_files:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Fix broken CDN URLs (e.g. src="https://cdnjs.cloudflare.com/.../all.min.js' %}")
    # The previous faulty script did: replace('.js"', '.js\' %}"')
    # So if there was: src="https://.../all.min.js"
    # It became: src="https://.../all.min.js' %}"
    
    # We will find http links that end with ' %} and fix them
    # Regex: (https?://[^"]+)' %}" -> \1"
    content = re.sub(r'(https?://[^"\']+)\' %}"', r'\1"', content)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

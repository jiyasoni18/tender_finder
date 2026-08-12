import sys
sys.stdout.reconfigure(encoding='utf-8')
from bs4 import BeautifulSoup
with open('ireps_initial.html', 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')
for btn in soup.find_all(['button', 'input']):
    if btn.get('type') in ('submit', 'button'):
        print(f"{btn.name} type={btn.get('type')} value='{btn.get('value')}' class={btn.get('class')}")

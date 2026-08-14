import sys
sys.stdout.reconfigure(encoding='utf-8')
from bs4 import BeautifulSoup

with open('ireps_results.html', 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

print("=== SELECT FIELDS ===")
for sel in soup.find_all('select'):
    name = sel.get('name') or sel.get('id', '')
    print(f"SELECT name={name}")
    for opt in sel.find_all('option'):
        val = opt.get('value', '')
        txt = opt.get_text(strip=True)[:40]
        print(f"  option value='{val}' text='{txt}'")
    print()

print("=== HIDDEN FIELDS ===")
for inp in soup.find_all('input', type='hidden'):
    print(f"HIDDEN name={inp.get('name')} value={inp.get('value','')[:40]}")

print("=== FORM ACTION ===")
for form in soup.find_all('form'):
    print(f"FORM action={form.get('action')} method={form.get('method')}")

print("\n=== TABLE ROWS (first 10 with 6+ cells) ===")
for i, row in enumerate(soup.find_all('tr')):
    cells = row.find_all('td')
    if len(cells) >= 6:
        texts = [c.get_text(strip=True)[:25] for c in cells[:8]]
        print(f"Row {i}: {texts}")

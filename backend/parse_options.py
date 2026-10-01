import re
with open("nprocure_home.html", "r", encoding="utf-8") as f:
    html = f.read()

opts = re.findall(r'<option[^>]*value="([^"]+)"[^>]*>(.*?)</option>', html)
for v, t in opts:
    if "Municipal" in t or "municipal" in t.lower():
        print(f"Value: {v} | Text: {t.strip()}")

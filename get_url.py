import urllib.request
import re

try:
    html = urllib.request.urlopen('https://tender-finder-ui.jiyatsc18.workers.dev/').read().decode('utf-8')
    js_url = re.search(r'src="(/assets/index-[^\"]+\.js)"', html)
    if js_url:
        js = urllib.request.urlopen('https://tender-finder-ui.jiyatsc18.workers.dev' + js_url.group(1)).read().decode('utf-8')
        urls = re.findall(r'https://[^\"]+\.onrender\.com', js)
        print("Backend URL:", urls)
except Exception as e:
    print("Error:", e)

import urllib.request
import json
try:
    url = "https://tender-finder-backend.onrender.com/api/results"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    response = urllib.request.urlopen(req)
    data = json.loads(response.read().decode('utf-8'))
    print(json.dumps(data, indent=2))
except Exception as e:
    print(f"Error: {e}")

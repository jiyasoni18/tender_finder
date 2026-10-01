import requests

def run():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        r1 = requests.get("https://tender.nprocure.com/", headers=headers, timeout=10, verify=False)
        with open("nprocure_home.html", "w", encoding="utf-8") as f:
            f.write(r1.text)
        print("Saved home")
    except Exception as e:
        print("Home error", e)
        
    try:
        r2 = requests.get("https://smc.nprocure.com/", headers=headers, timeout=10, verify=False)
        with open("nprocure_smc.html", "w", encoding="utf-8") as f:
            f.write(r2.text)
        print("Saved smc")
    except Exception as e:
        print("SMC error", e)

if __name__ == "__main__":
    run()

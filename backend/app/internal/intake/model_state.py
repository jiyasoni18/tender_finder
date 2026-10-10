import os

STATE_FILE = os.path.join(os.path.dirname(__file__), ".model_state")

def get_model_idx():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return int(f.read().strip())
        except:
            return 0
    return 0

def increment_model_idx():
    idx = get_model_idx() + 1
    with open(STATE_FILE, 'w') as f:
        f.write(str(idx))
    return idx

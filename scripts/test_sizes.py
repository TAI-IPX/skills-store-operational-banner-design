import json, requests, os, struct, base64
from pathlib import Path

root = Path(__file__).resolve().parent.parent
env_file = root / '.env'
if env_file.is_file():
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, _, v = line.partition('=')
                if k.strip() == 'PACKYGPT_API_KEY' and v.strip() and k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip().strip("'\"")

api_key = os.environ.get('PACKYGPT_API_KEY', '').strip()
base_url = 'https://www.packyapi.com'

def get_png_size(data):
    if len(data) < 24:
        return None, None
    w = struct.unpack('>I', data[16:20])[0]
    h = struct.unpack('>I', data[20:24])[0]
    return w, h

test_sizes = ['1024x640', '1792x448', '1536x384', '2048x512', '4096x1024']

for size in test_sizes:
    body = json.dumps({
        'model': 'gpt-image-2',
        'prompt': 'a simple red dot on white background, minimal',
        'size': size,
        'quality': 'low',
        'n': 1,
    }).encode('utf-8')
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    try:
        resp = requests.post(f'{base_url}/v1/images/generations', data=body, headers=headers, timeout=120)
        data = resp.json()
        item = data.get('data', [{}])[0]
        img_url = item.get('url', '')
        b64 = item.get('b64_json', '')
        
        img_bytes = None
        if img_url:
            img_resp = requests.get(img_url, timeout=60)
            img_bytes = img_resp.content
        elif b64:
            img_bytes = base64.b64decode(b64)
        
        if img_bytes and len(img_bytes) > 24:
            w, h = get_png_size(img_bytes)
            match = f'MATCH' if str(w)+'x'+str(h) == size else f'MISMATCH'
            print(f'request {size:>12s} -> actual {w}x{h}  [{match}]')
        else:
            print(f'request {size:>12s} -> no image data')
    except Exception as e:
        print(f'request {size:>12s} -> error: {e}')

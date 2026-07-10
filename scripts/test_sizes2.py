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

# Test just one size but dump raw bytes
size = '1024x640'
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
resp = requests.post(f'{base_url}/v1/images/generations', data=body, headers=headers, timeout=120)
data = resp.json()
item = data.get('data', [{}])[0]
b64 = item.get('b64_json', '')
img_bytes = base64.b64decode(b64)

print(f'Requested: {size}')
print(f'Total bytes: {len(img_bytes)}')
print(f'First 40 bytes (hex): {img_bytes[:40].hex()}')
print()

# Parse PNG properly
# Bytes 0-7: signature
sig = img_bytes[:8]
print(f'PNG Signature: {sig.hex()} (expected: 89504e470d0a1a0a)')

# Bytes 8-11: IHDR chunk length (should be 13 = 0x0D)
chunk_len = struct.unpack('>I', img_bytes[8:12])[0]
print(f'IHDR chunk length: {chunk_len}')

# Bytes 12-15: 'IHDR'
chunk_type = img_bytes[12:16].decode('ascii')
print(f'Chunk type: {chunk_type}')

# Bytes 16-19: width
w = struct.unpack('>I', img_bytes[16:20])[0]
# Bytes 20-23: height
h = struct.unpack('>I', img_bytes[20:24])[0]
print(f'Width: {w}, Height: {h}')
print(f'Image size: {w}x{h}')

# Also try with PIL
try:
    from PIL import Image
    from io import BytesIO
    im = Image.open(BytesIO(img_bytes))
    print(f'PIL says: {im.size[0]}x{im.size[1]}')
except Exception as e:
    print(f'PIL error: {e}')

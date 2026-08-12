from pathlib import Path
import base64
import hashlib
import zlib

parts = sorted(Path('tools').glob('.phase192_recovery_patch.*'))
if len(parts) != 29:
    raise SystemExit(f'expected 29 recovery parts, found {len(parts)}')
encoded = ''.join(p.read_text(encoding='ascii') for p in parts)
patch = zlib.decompress(base64.b64decode(encoded))
digest = hashlib.sha256(patch).hexdigest()
expected = '58d48d0163f58a6d40887a4ed45d3c774113b9e34d04fd44973c2b335b68bdd0'
if digest != expected:
    raise SystemExit(f'patch sha256 mismatch: {digest}')
Path('tools/.phase192_recovery.patch').write_bytes(patch)

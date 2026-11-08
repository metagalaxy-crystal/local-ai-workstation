import collections
import json
import os
import struct

D = r"d:\models\models\agent\mage-vl-cowork"

for name in [
    "model-00001-of-00002.safetensors",
    "model-00002-of-00002.safetensors",
]:
    p = os.path.join(D, name)
    size = os.path.getsize(p)
    with open(p, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        hdr = json.loads(f.read(n))
    tensors = {k: v for k, v in hdr.items() if k != "__metadata__"}
    payload = max(v["data_offsets"][1] for v in tensors.values())
    expected = 8 + n + payload
    status = "MATCH" if size == expected else "MISMATCH"
    print(name)
    print("  file size :", size)
    print("  computed  :", expected, "->", status)
    print("  tensors   :", len(tensors))
    print("  dtypes    :", dict(collections.Counter(v["dtype"] for v in tensors.values())))

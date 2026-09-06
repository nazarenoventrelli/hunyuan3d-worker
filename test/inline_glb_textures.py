"""Rewrite a GLB so embedded textures become data: URIs instead of bufferViews.

Why: three.js builds a Blob and loads it through a blob: URL for images stored in a
bufferView. The artifact sandbox blocks that scheme, so the load dies with
"TypeError: Failed to fetch" while the geometry itself is fine. Images carried as
data: URIs skip the Blob path entirely.

The image bufferViews are then dropped from the binary chunk and every remaining
bufferView index is remapped, so the texture bytes are not carried twice.

usage: python test/inline_glb_textures.py in.glb out.glb
"""
import base64
import json
import struct
import sys
import pathlib


def read_glb(raw):
    magic, version, _ = struct.unpack_from("<4sII", raw, 0)
    if magic != b"glTF":
        raise ValueError("not a GLB")
    off, chunks = 12, {}
    while off < len(raw):
        clen, ctype = struct.unpack_from("<I4s", raw, off)
        chunks[ctype.rstrip(b"\x00")] = raw[off + 8: off + 8 + clen]
        off += 8 + clen + ((4 - clen % 4) % 4)
    return json.loads(chunks[b"JSON"].decode("utf-8")), chunks.get(b"BIN", b"")


def pad(b, filler):
    return b + filler * ((4 - len(b) % 4) % 4)


def write_glb(gltf, binary):
    j = pad(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")
    b = pad(binary, b"\x00")
    total = 12 + 8 + len(j) + (8 + len(b) if b else 0)
    out = struct.pack("<4sII", b"glTF", 2, total)
    out += struct.pack("<I4s", len(j), b"JSON") + j
    if b:
        out += struct.pack("<I4s", len(b), b"BIN\x00") + b
    return out


def main():
    src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    gltf, binary = read_glb(src.read_bytes())
    views = gltf.get("bufferViews", [])

    # 1. images -> data: uris, remembering which views they freed
    freed = set()
    for img in gltf.get("images", []):
        if "bufferView" not in img:
            continue
        idx = img["bufferView"]
        bv = views[idx]
        start = bv.get("byteOffset", 0)
        data = binary[start: start + bv["byteLength"]]
        mime = img.get("mimeType", "image/png")
        img["uri"] = "data:%s;base64,%s" % (mime, base64.b64encode(data).decode())
        del img["bufferView"]
        img.pop("mimeType", None)  # spec: mimeType only pairs with bufferView
        freed.add(idx)
        print("  inlined '%s' (%s, %.2f MB)" % (img.get("name", "?"), mime, len(data) / 1e6))

    # 2. rebuild the binary chunk from the views that are still referenced
    new_views, remap, blob = [], {}, bytearray()
    for i, bv in enumerate(views):
        if i in freed:
            continue
        start = bv.get("byteOffset", 0)
        chunk = binary[start: start + bv["byteLength"]]
        while len(blob) % 4:
            blob.append(0)
        nb = dict(bv)
        nb["byteOffset"] = len(blob)
        remap[i] = len(new_views)
        new_views.append(nb)
        blob += chunk

    # 3. repoint everything that indexes a bufferView
    for acc in gltf.get("accessors", []):
        if "bufferView" in acc:
            acc["bufferView"] = remap[acc["bufferView"]]
    for name in ("meshes", "skins", "nodes"):
        for obj in gltf.get(name, []):
            if "bufferView" in obj:
                obj["bufferView"] = remap[obj["bufferView"]]

    gltf["bufferViews"] = new_views
    gltf["buffers"] = [{"byteLength": len(blob)}]

    dst.write_bytes(write_glb(gltf, bytes(blob)))
    print("views dropped  : %d of %d" % (len(freed), len(views)))
    print("in  : %.2f MB" % (src.stat().st_size / 1e6))
    print("out : %.2f MB" % (dst.stat().st_size / 1e6))
    print("as base64 in the page: %.2f MB" % (dst.stat().st_size * 4 / 3 / 1e6))


if __name__ == "__main__":
    main()

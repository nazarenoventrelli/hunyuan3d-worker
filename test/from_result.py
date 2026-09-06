"""Turn a Runpod job result (JSON, possibly a huge MCP tool-result dump) into a .glb + viewer.

usage:
  python test/from_result.py <path-to-result.json-or-txt> [tag]

Works with either the raw /status response or an MCP tool-result file that wraps it.
Never prints the base64 payload.
"""
import sys
import json
import re
import base64
import pathlib

from run import build_viewer  # noqa: E402  (same folder)

HERE = pathlib.Path(__file__).resolve().parent


def find_payload(text):
    """Return (glb_b64, meta_dict). Tolerates the blob being nested anywhere."""
    # fast path: valid JSON somewhere in the file
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        start = text.find("{")
        end = text.rfind("}")
        data = None
        if start != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except Exception:  # noqa: BLE001
                data = None

    if isinstance(data, dict):
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if "glb_b64" in node and isinstance(node["glb_b64"], str):
                    meta = {k: v for k, v in node.items() if k != "glb_b64"}
                    return node["glb_b64"], meta
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)

    # last resort: regex the blob straight out of the text
    m = re.search(r'"glb_b64"\s*:\s*"([A-Za-z0-9+/=]+)"', text)
    if m:
        return m.group(1), {}
    return None, {}


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python test/from_result.py <result-file> [tag]")
    path = pathlib.Path(sys.argv[1])
    tag = sys.argv[2] if len(sys.argv) > 2 else "shape"

    text = path.read_text(encoding="utf-8", errors="ignore")
    b64, meta = find_payload(text)
    if not b64:
        sys.exit("no glb_b64 found in " + str(path))

    glb = base64.b64decode(b64)
    glb_path = HERE / ("cafe_%s.glb" % tag)
    glb_path.write_bytes(glb)

    flat = {"mode": tag, "glb size": "%.2f MB" % (len(glb) / 1e6)}
    for k in ("faces", "textured", "bytes"):
        if k in meta:
            flat[k] = meta[k]
    for k, v in (meta.get("timings") or {}).items():
        flat[k] = ("{:,}".format(v) if k.startswith("faces") else "%s s" % v)

    viewer = HERE / ("viewer_%s.html" % tag)
    build_viewer(glb, flat, viewer, "cafe / %s" % tag)

    print(json.dumps({"glb": str(glb_path), "viewer": str(viewer), **flat}, indent=2))


if __name__ == "__main__":
    main()

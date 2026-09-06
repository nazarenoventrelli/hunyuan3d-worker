"""Submit a job to the Hunyuan3D endpoint, poll it, save the GLB, build a three.js viewer.

usage:
  set RUNPOD_API_KEY=...          (or put it in .env next to this file)
  python test/run.py <ENDPOINT_ID> [--texture] [--image URL] [--timeout 1800]
"""
import os
import sys
import json
import time
import base64
import pathlib
import urllib.request
import urllib.error

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_IMAGE = (
    "https://raw.githubusercontent.com/nazarenoventrelli/hunyuan3d-worker/main/test/cafe.jpg"
)


def api_key():
    key = os.environ.get("RUNPOD_API_KEY", "").strip()
    if key:
        return key
    for candidate in (HERE / ".env", HERE.parent / ".env"):
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("RUNPOD_API_KEY"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("RUNPOD_API_KEY not set (env var or .env file)")


def post(url, key, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def get(url, key):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


VIEWER_PATH = HERE / "viewer_template.html"


def build_viewer(glb_bytes, meta, out_path, title):
    rows = "".join(
        '<tr><td class="k">%s</td><td>%s</td></tr>' % (k, v) for k, v in meta.items()
    )
    html = (
        VIEWER_PATH.read_text(encoding="utf-8").replace("__GLB__", base64.b64encode(glb_bytes).decode())
        .replace("__ROWS__", rows)
        .replace("__TITLE__", title)
    )
    out_path.write_text(html, encoding="utf-8")


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit("usage: python test/run.py <ENDPOINT_ID> [--texture] [--image URL]")
    endpoint = args[0]
    texture = "--texture" in args
    image = DEFAULT_IMAGE
    if "--image" in args:
        image = args[args.index("--image") + 1]
    timeout = 1800
    if "--timeout" in args:
        timeout = int(args[args.index("--timeout") + 1])

    key = api_key()
    base = "https://api.runpod.ai/v2/" + endpoint

    payload = {"input": {"image": image, "texture": texture}}
    print("submitting (texture=%s) ..." % texture)
    t0 = time.time()
    job = post(base + "/run", key, payload)
    jid = job.get("id")
    if not jid:
        sys.exit("no job id: " + json.dumps(job))
    print("job " + jid)

    last = None
    while True:
        time.sleep(5)
        st = get(base + "/status/" + jid, key)
        status = st.get("status")
        if status != last:
            print("  [%6.1fs] %s" % (time.time() - t0, status))
            last = status
        if st.get("stream") or st.get("output") is not None:
            pass
        if status in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            break
        if time.time() - t0 > timeout:
            sys.exit("client timeout after %ds (job still %s)" % (timeout, status))

    wall = time.time() - t0
    if status != "COMPLETED":
        print(json.dumps(st, indent=2)[:2000])
        sys.exit("job ended: " + str(status))

    out = st.get("output") or {}
    if "error" in out:
        sys.exit("handler error: " + str(out["error"]))

    glb = base64.b64decode(out["glb_b64"])
    tag = "textured" if out.get("textured") else "shape"
    glb_path = HERE / ("cafe_%s.glb" % tag)
    glb_path.write_bytes(glb)

    meta = {
        "mode": tag,
        "faces": out.get("faces"),
        "glb size": "%.2f MB" % (len(glb) / 1e6),
        "wall clock": "%.1f s" % wall,
        "delayTime": "%.1f s" % (st.get("delayTime", 0) / 1000.0),
        "executionTime": "%.1f s" % (st.get("executionTime", 0) / 1000.0),
    }
    for k, v in (out.get("timings") or {}).items():
        meta[k] = "%s s" % v

    viewer = HERE / ("viewer_%s.html" % tag)
    build_viewer(glb, meta, viewer, "cafe / %s" % tag)

    print("\n--- result ---")
    print(json.dumps({"glb": str(glb_path), "viewer": str(viewer), **meta}, indent=2))


if __name__ == "__main__":
    main()

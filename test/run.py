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


VIEWER = """<title>Cafe - Hunyuan3D 2.1</title>
<style>
  :root{color-scheme:dark;--bg:#101014;--fg:#e8e8ee;--dim:#9a9aa8;--line:#2a2a34;--accent:#7dd3a0}
  body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 ui-sans-serif,system-ui,sans-serif}
  #c{width:100vw;height:100vh;display:block}
  .panel{position:fixed;top:16px;left:16px;background:rgba(16,16,20,.86);border:1px solid var(--line);
         border-radius:10px;padding:14px 16px;backdrop-filter:blur(8px);max-width:300px}
  h1{margin:0 0 10px;font-size:14px;letter-spacing:.02em}
  table{border-collapse:collapse;width:100%}
  td{padding:2px 0;font-variant-numeric:tabular-nums}
  td:last-child{text-align:right;color:var(--accent)}
  .k{color:var(--dim)}
  .hint{position:fixed;bottom:16px;left:16px;color:var(--dim);font-size:12px}
</style>
<canvas id="c"></canvas>
<div class="panel"><h1>__TITLE__</h1><table>__ROWS__</table></div>
<div class="hint">drag to orbit &middot; scroll to zoom</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/128/three.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/128/examples/js/loaders/GLTFLoader.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/128/examples/js/controls/OrbitControls.js"></script>
<script>
const B64="__GLB__";
const renderer=new THREE.WebGLRenderer({canvas:document.getElementById('c'),antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.outputEncoding=THREE.sRGBEncoding;
const scene=new THREE.Scene();scene.background=new THREE.Color(0x101014);
const camera=new THREE.PerspectiveCamera(45,1,0.01,100);
const controls=new THREE.OrbitControls(camera,renderer.domElement);
controls.enableDamping=true;
scene.add(new THREE.HemisphereLight(0xffffff,0x223344,1.1));
const key=new THREE.DirectionalLight(0xffffff,1.4);key.position.set(3,5,4);scene.add(key);
const fill=new THREE.DirectionalLight(0xffffff,0.5);fill.position.set(-4,2,-3);scene.add(fill);
function resize(){const w=innerWidth,h=innerHeight;renderer.setSize(w,h,false);
  camera.aspect=w/h;camera.updateProjectionMatrix();}
addEventListener('resize',resize);resize();
const bin=Uint8Array.from(atob(B64),c=>c.charCodeAt(0));
new THREE.GLTFLoader().parse(bin.buffer,'',g=>{
  const o=g.scene;const box=new THREE.Box3().setFromObject(o);
  const size=box.getSize(new THREE.Vector3()).length();
  const ctr=box.getCenter(new THREE.Vector3());
  o.position.sub(ctr);scene.add(o);
  camera.position.set(0,size*0.15,size*0.9);
  controls.target.set(0,0,0);controls.update();
},e=>console.error(e));
(function loop(){requestAnimationFrame(loop);controls.update();renderer.render(scene,camera);})();
</script>
"""


def build_viewer(glb_bytes, meta, out_path, title):
    rows = "".join(
        '<tr><td class="k">%s</td><td>%s</td></tr>' % (k, v) for k, v in meta.items()
    )
    html = (
        VIEWER.replace("__GLB__", base64.b64encode(glb_bytes).decode())
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

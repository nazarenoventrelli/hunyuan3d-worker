"""Build a standalone local viewer HTML with the GLB embedded.

No server, no sandbox: double-click the output. three.js comes from a CDN, the mesh
travels inside the file as base64, so there is nothing to fetch from disk.

usage: python test/make_local_viewer.py <in.glb> <out.html> [title]
"""
import base64
import json
import pathlib
import struct
import sys

TEMPLATE = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
  :root{
    --ink:#0a0c11; --panel:rgba(12,15,21,.86); --line:#242c3a;
    --fg:#eceff5; --dim:#8e9aae; --accent:#ffab5e; --ok:#3ddc97;
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0;background:var(--ink);color:var(--fg);overflow:hidden;
       font:14px/1.55 ui-sans-serif,system-ui,"Segoe UI",sans-serif}
  #c{position:fixed;inset:0;width:100%;height:100%;display:block}
  .panel{position:fixed;top:18px;left:18px;z-index:5;background:var(--panel);
         border:1px solid var(--line);border-radius:8px;padding:14px 16px;
         backdrop-filter:blur(10px);min-width:250px}
  h1{margin:0 0 11px;font-size:12px;font-weight:600;letter-spacing:.09em;
     text-transform:uppercase;color:var(--accent)}
  table{border-collapse:collapse;width:100%}
  td{padding:2.5px 0;font-size:12.5px}
  td:first-child{color:var(--dim);padding-right:22px}
  td:last-child{text-align:right;font-family:ui-monospace,Menlo,monospace;
                font-variant-numeric:tabular-nums}
  .bar{position:fixed;bottom:18px;left:18px;z-index:5;display:flex;gap:8px;
       align-items:center;flex-wrap:wrap;max-width:calc(100vw - 36px)}
  button{background:var(--panel);color:var(--fg);border:1px solid var(--line);
         border-radius:6px;padding:7px 13px;font:inherit;font-size:12.5px;
         cursor:pointer;backdrop-filter:blur(10px)}
  button:hover{border-color:var(--accent);color:var(--accent)}
  button[aria-pressed="true"]{border-color:var(--accent);color:var(--accent)}
  button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  .hint{color:var(--dim);font-size:12px;margin-left:4px}
  #err{position:fixed;left:18px;right:18px;bottom:64px;z-index:9;padding:12px 14px;
       border:1px solid #b3453f;background:#2a1416;color:#ffb4ae;border-radius:6px;
       font:12.5px ui-monospace,monospace;white-space:pre-wrap;display:none}
  #boot{position:fixed;inset:0;display:grid;place-items:center;color:var(--dim);
        font-size:13px;z-index:4;pointer-events:none}
</style>
</head>
<body>
<canvas id="c"></canvas>
<div id="boot">cargando malla&hellip;</div>
<div class="panel"><h1>__TITLE__</h1><table>__ROWS__</table></div>
<div class="bar">
  <button id="spin" aria-pressed="true">Pausar giro</button>
  <button id="wire" aria-pressed="false">Wireframe</button>
  <button id="tex" aria-pressed="true">Texturas</button>
  <button id="bg">Fondo</button>
  <span class="hint">arrastrar para orbitar &middot; rueda para zoom</span>
</div>
<div id="err"></div>

<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/GLTFLoader.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const GLB_B64 = "__GLB__";

function fail(msg){
  const e = document.getElementById('err');
  e.style.display = 'block';
  e.textContent = msg;
  document.getElementById('boot').style.display = 'none';
}
window.addEventListener('error', ev => fail('JS error: ' + ev.message));

if (typeof THREE === 'undefined') fail('three.js no cargo (sin internet?)');
else if (!THREE.GLTFLoader) fail('GLTFLoader no cargo');
else main();

function main(){
  // GLTFLoader picks ImageBitmapLoader when createImageBitmap exists, and that
  // path pulls textures through fetch(). Hiding it forces the <img> path, which
  // works from file:// where fetch on a blob: URL does not.
  const realCIB = window.createImageBitmap;
  window.createImageBitmap = undefined;

  const canvas = document.getElementById('c');
  const renderer = new THREE.WebGLRenderer({canvas, antialias:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputEncoding = THREE.sRGBEncoding;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const GROUNDS = [0x141922, 0x2b2f36, 0xb9bec7, 0x07080b];
  let groundIdx = 0;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(GROUNDS[0]);
  scene.fog = new THREE.Fog(GROUNDS[0], 7, 26);

  const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 300);
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.07;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 1.1;

  scene.add(new THREE.HemisphereLight(0x9fb4d8, 0x2a2118, 0.7));
  scene.add(new THREE.AmbientLight(0xffffff, 0.16));
  const key = new THREE.DirectionalLight(0xfff2e0, 2.4);
  key.position.set(4, 6.5, 4.5);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.bias = -0.0008;
  key.shadow.camera.near = 0.5; key.shadow.camera.far = 40;
  scene.add(key);
  const fillL = new THREE.DirectionalLight(0xbcd2ff, 0.7);
  fillL.position.set(-5, 2, 3); scene.add(fillL);
  const rim = new THREE.DirectionalLight(0xffc38a, 1.4);
  rim.position.set(-2.5, 3.5, -5.5); scene.add(rim);

  const clay = new THREE.MeshStandardMaterial({color:0xd8c9b6, roughness:0.62, metalness:0.04});
  let model = null, wireOn = false, texOn = true;
  const originals = new Map();

  function frame(o){
    const box = new THREE.Box3().setFromObject(o);
    const size = box.getSize(new THREE.Vector3());
    const ctr  = box.getCenter(new THREE.Vector3());
    const span = Math.max(size.x, size.y, size.z) || 1;
    const s = 2 / span;
    o.scale.setScalar(s);
    o.position.set(-ctr.x * s, -box.min.y * s, -ctr.z * s);

    const ground = new THREE.Mesh(
      new THREE.CircleGeometry(11, 64),
      new THREE.MeshStandardMaterial({color:0x1b212c, roughness:0.95})
    );
    ground.rotation.x = -Math.PI/2; ground.receiveShadow = true; scene.add(ground);
    const grid = new THREE.GridHelper(20, 40, 0x2f3a4d, 0x222b39);
    grid.position.y = 0.001; grid.material.transparent = true; grid.material.opacity = 0.45;
    scene.add(grid);

    camera.position.set(2.6, 2.0, 3.4);
    controls.target.set(0, 1.0, 0);
    controls.update();
  }

  function resize(){
    renderer.setSize(innerWidth, innerHeight, false);
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
  }
  addEventListener('resize', resize); resize();

  const bin = Uint8Array.from(atob(GLB_B64), c => c.charCodeAt(0));
  new THREE.GLTFLoader().parse(bin.buffer, '', g => {
    window.createImageBitmap = realCIB;
    model = g.scene;
    let meshes = 0, tris = 0, textured = 0;
    model.traverse(n => {
      if (!n.isMesh) return;
      meshes++;
      n.castShadow = true; n.receiveShadow = true;
      if (n.geometry) {
        if (!n.geometry.attributes.normal) n.geometry.computeVertexNormals();
        const idx = n.geometry.index;
        tris += idx ? idx.count/3 : n.geometry.attributes.position.count/3;
      }
      if (n.material && n.material.map) { originals.set(n, n.material); textured++; }
      else n.material = clay;
    });
    scene.add(model);
    frame(model);
    document.getElementById('boot').style.display = 'none';
    if (!textured) {
      document.getElementById('tex').disabled = true;
      document.getElementById('tex').setAttribute('aria-pressed', 'false');
    }
    console.log('meshes', meshes, 'tris', tris, 'textured meshes', textured);
  }, e => {
    window.createImageBitmap = realCIB;
    fail('No se pudo parsear el GLB:\n' + (e && e.message ? e.message : e));
  });

  const spinBtn = document.getElementById('spin');
  spinBtn.onclick = () => {
    controls.autoRotate = !controls.autoRotate;
    spinBtn.textContent = controls.autoRotate ? 'Pausar giro' : 'Reanudar giro';
    spinBtn.setAttribute('aria-pressed', String(controls.autoRotate));
  };
  controls.addEventListener('start', () => {
    controls.autoRotate = false;
    spinBtn.textContent = 'Reanudar giro';
    spinBtn.setAttribute('aria-pressed', 'false');
  });

  const wireBtn = document.getElementById('wire');
  wireBtn.onclick = () => {
    if (!model) return;
    wireOn = !wireOn;
    wireBtn.setAttribute('aria-pressed', String(wireOn));
    model.traverse(n => { if (n.isMesh && n.material) n.material.wireframe = wireOn; });
  };

  const texBtn = document.getElementById('tex');
  texBtn.onclick = () => {
    if (!model || !originals.size) return;
    texOn = !texOn;
    texBtn.setAttribute('aria-pressed', String(texOn));
    originals.forEach((mat, mesh) => {
      mesh.material = texOn ? mat : clay;
      mesh.material.wireframe = wireOn;
    });
  };

  document.getElementById('bg').onclick = () => {
    groundIdx = (groundIdx + 1) % GROUNDS.length;
    scene.background = new THREE.Color(GROUNDS[groundIdx]);
    scene.fog.color = new THREE.Color(GROUNDS[groundIdx]);
  };

  if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
    controls.autoRotate = false;
    spinBtn.textContent = 'Reanudar giro';
    spinBtn.setAttribute('aria-pressed', 'false');
  }

  (function loop(){
    requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  })();
}
</script>
</body>
</html>
"""


def glb_stats(raw):
    off, out = 12, {}
    while off < len(raw):
        clen, ctype = struct.unpack_from("<I4s", raw, off)
        if ctype.rstrip(b"\x00") == b"JSON":
            g = json.loads(raw[off + 8: off + 8 + clen].decode("utf-8"))
            out["materials"] = len(g.get("materials", []))
            out["textures"] = len(g.get("textures", []))
            out["images"] = len(g.get("images", []))
        off += 8 + clen + ((4 - clen % 4) % 4)
    return out


def main():
    src = pathlib.Path(sys.argv[1])
    dst = pathlib.Path(sys.argv[2])
    title = sys.argv[3] if len(sys.argv) > 3 else src.stem

    raw = src.read_bytes()
    info = glb_stats(raw)

    rows = {
        "archivo": src.name,
        "tamano": "%.2f MB" % (len(raw) / 1e6),
        "materiales": info.get("materials", 0),
        "texturas": info.get("textures", 0),
    }
    meta_file = src.with_suffix(".meta.json")
    if meta_file.exists():
        rows.update(json.loads(meta_file.read_text(encoding="utf-8")))

    html = (
        TEMPLATE.replace("__GLB__", base64.b64encode(raw).decode())
        .replace("__TITLE__", title)
        .replace(
            "__ROWS__",
            "".join("<tr><td>%s</td><td>%s</td></tr>" % (k, v) for k, v in rows.items()),
        )
    )
    dst.write_text(html, encoding="utf-8")
    print("escrito: %s  (%.2f MB)" % (dst, dst.stat().st_size / 1e6))
    for k, v in rows.items():
        print("  %-12s %s" % (k, v))


if __name__ == "__main__":
    main()

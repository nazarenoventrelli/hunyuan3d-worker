"""Runpod serverless handler for Hunyuan3D 2.1 (Tencent official Space code).

input:
  image      str  base64 (with or without data: prefix) OR http(s) url   [required]
  texture    bool run the PBR texture stage too (default false)
  steps      int  shape diffusion steps (default 30)
  guidance_scale     float (default 5.0)
  octree_resolution  int (default 256)
  seed       int  (default 42)
  face_count int  max faces after reduction (default 40000)
  max_num_view       int texture views (default 6)   # 6 views @512 = the ~21GB setting
  texture_resolution int (default 512)

output:
  glb_b64, format, bytes, faces, textured, timings{}
"""
import os
import sys
import time
import base64
import io
import tempfile
import traceback

sys.path.insert(0, "/app")
# hy3dshape/ is the project folder; the importable package is nested one level down
# (/app/hy3dshape/hy3dshape/). Without this, "from hy3dshape import FaceReducer"
# resolves the outer namespace package and fails with "unknown location".
sys.path.insert(0, "/app/hy3dshape")
os.chdir("/app")

import runpod
import torch
from PIL import Image

# basicsr/realesrgan break on torchvision>=0.17; the Space ships the fix.
try:
    from torchvision_fix import apply_fix
    apply_fix()
except Exception as e:  # noqa: BLE001
    print("[warn] torchvision_fix not applied: " + str(e))

# --- HARD GUARD -------------------------------------------------------------
# The texture stage needs the compiled pybind11 extension. If it is missing the
# upstream code silently falls back to a pure-python loop that is ~60x slower
# (hours instead of ~2 min) and the endpoint STILL returns correct results, so
# the only symptom is the bill. Fail loudly at boot instead.
sys.path.insert(0, "/app/hy3dpaint/DifferentiableRenderer")
import mesh_inpaint_processor  # noqa: F401,E402

print("[boot] compiled mesh_inpaint_processor OK -> " + str(mesh_inpaint_processor.__file__))
# ---------------------------------------------------------------------------

from hy3dshape import (  # noqa: E402
    FaceReducer,
    FloaterRemover,
    DegenerateFaceRemover,
    Hunyuan3DDiTFlowMatchingPipeline,
)
from hy3dshape.pipelines import export_to_trimesh  # noqa: E402
from hy3dshape.rembg import BackgroundRemover  # noqa: E402

MODEL_PATH = "tencent/Hunyuan3D-2.1"
SUBFOLDER = "hunyuan3d-dit-v2-1"

_shape = None
_paint = None
_rembg = None


def _log_vram(tag):
    if torch.cuda.is_available():
        alloc = torch.cuda.memory_allocated() / 2 ** 30
        peak = torch.cuda.max_memory_reserved() / 2 ** 30
        print("[vram] %s: allocated=%.2fGiB peak_reserved=%.2fGiB" % (tag, alloc, peak))


def get_shape():
    global _shape, _rembg
    if _shape is None:
        t = time.time()
        _shape = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            MODEL_PATH, subfolder=SUBFOLDER, use_safetensors=False, device="cuda"
        )
        _rembg = BackgroundRemover()
        print("[load] shape pipeline in %.1fs" % (time.time() - t))
        _log_vram("shape loaded")
    return _shape


def get_paint(max_num_view, resolution):
    global _paint
    if _paint is None:
        from hy3dpaint.textureGenPipeline import Hunyuan3DPaintPipeline, Hunyuan3DPaintConfig

        t = time.time()
        conf = Hunyuan3DPaintConfig(max_num_view=max_num_view, resolution=resolution)
        # paths relative to /app, same as the Space gradio_app does
        conf.realesrgan_ckpt_path = "hy3dpaint/ckpt/RealESRGAN_x4plus.pth"
        conf.multiview_cfg_path = "hy3dpaint/cfgs/hunyuan-paint-pbr.yaml"
        conf.custom_pipeline = "hy3dpaint/hunyuanpaintpbr"
        _paint = Hunyuan3DPaintPipeline(conf)
        print("[load] paint pipeline in %.1fs" % (time.time() - t))
        _log_vram("paint loaded")
    return _paint


def _decimate_open3d(mesh, target_faces):
    """Quadric decimation via open3d, used when the upstream pymeshlab path breaks."""
    try:
        import numpy as np
        import open3d as o3d
        import trimesh

        if len(mesh.faces) <= target_faces:
            return mesh
        o = o3d.geometry.TriangleMesh(
            o3d.utility.Vector3dVector(np.asarray(mesh.vertices, dtype=float)),
            o3d.utility.Vector3iVector(np.asarray(mesh.faces, dtype=int)),
        )
        o.remove_duplicated_vertices()
        o.remove_degenerate_triangles()
        o = o.simplify_quadric_decimation(int(target_faces))
        return trimesh.Trimesh(
            vertices=np.asarray(o.vertices), faces=np.asarray(o.triangles), process=False
        )
    except Exception as e:  # noqa: BLE001
        print("[warn] open3d decimation failed too (%s); returning raw mesh" % e)
        return mesh


def load_image(spec):
    if not spec:
        raise ValueError("input.image is required (base64 or http url)")
    if spec.startswith("http://") or spec.startswith("https://"):
        import urllib.request

        with urllib.request.urlopen(spec, timeout=60) as resp:
            raw = resp.read()
    else:
        if spec.strip().startswith("data:") and "," in spec[:128]:
            spec = spec.split(",", 1)[1]
        raw = base64.b64decode(spec)
    return Image.open(io.BytesIO(raw)).convert("RGBA")


def handler(job):
    t0 = time.time()
    timings = {}
    inp = job.get("input") or {}

    def progress(msg):
        print("[job] " + msg)
        try:
            runpod.serverless.progress_update(job, msg)
        except Exception:  # noqa: BLE001
            pass

    try:
        want_texture = bool(inp.get("texture", False))
        steps = int(inp.get("steps", 30))
        guidance = float(inp.get("guidance_scale", 5.0))
        octree = int(inp.get("octree_resolution", 256))
        seed = int(inp.get("seed", 42))
        face_count = int(inp.get("face_count", 40000))
        max_num_view = int(inp.get("max_num_view", 6))
        tex_res = int(inp.get("texture_resolution", 512))

        progress("loading image")
        image = load_image(inp.get("image"))

        pipe = get_shape()

        needs_rembg = image.mode != "RGBA" or image.getextrema()[3][0] == 255
        if needs_rembg:
            progress("removing background")
            t = time.time()
            image = _rembg(image.convert("RGB"))
            timings["rembg_s"] = round(time.time() - t, 2)

        progress("shape generation (%d steps, octree %d)" % (steps, octree))
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        t = time.time()
        gen = torch.Generator(device="cuda").manual_seed(seed)
        outputs = pipe(
            image=image,
            num_inference_steps=steps,
            guidance_scale=guidance,
            generator=gen,
            octree_resolution=octree,
            output_type="mesh",
        )
        # the pipeline yields Latent2MeshOutput, not a trimesh - the Space converts
        # with export_to_trimesh before anything downstream touches .faces
        mesh = export_to_trimesh(outputs)[0]
        timings["shape_s"] = round(time.time() - t, 2)
        _log_vram("after shape")

        progress("cleaning mesh")
        t = time.time()
        timings["faces_raw"] = int(len(mesh.faces))
        try:
            mesh = FloaterRemover()(mesh)
            mesh = DegenerateFaceRemover()(mesh)
            mesh = FaceReducer()(mesh, max_facenum=face_count)
        except Exception as e:  # noqa: BLE001
            # The upstream helpers ride a pymeshlab API that moves between versions.
            # Never lose a generated mesh over decimation.
            print("[warn] upstream cleanup failed (%s); falling back to open3d" % e)
            timings["cleanup_fallback"] = type(e).__name__
            mesh = _decimate_open3d(mesh, face_count)
        timings["cleanup_s"] = round(time.time() - t, 2)

        tmp = tempfile.mkdtemp()
        shape_path = os.path.join(tmp, "shape.glb")
        mesh.export(shape_path)
        out_path = shape_path

        if want_texture:
            progress("texture generation (%d views @ %d)" % (max_num_view, tex_res))
            t = time.time()
            img_path = os.path.join(tmp, "input.png")
            image.convert("RGB").save(img_path)
            tex = get_paint(max_num_view, tex_res)
            textured = os.path.join(tmp, "textured.obj")
            produced = tex(
                mesh_path=shape_path,
                image_path=img_path,
                output_mesh_path=textured,
                save_glb=True,
            )
            timings["texture_s"] = round(time.time() - t, 2)
            _log_vram("after texture")
            for cand in (
                str(produced) if produced else "",
                str(produced).replace(".obj", ".glb") if produced else "",
                textured.replace(".obj", ".glb"),
            ):
                if cand and cand.endswith(".glb") and os.path.exists(cand):
                    out_path = cand
                    break

        with open(out_path, "rb") as f:
            blob = f.read()

        timings["total_s"] = round(time.time() - t0, 2)
        progress("done in %ss" % timings["total_s"])
        return {
            "glb_b64": base64.b64encode(blob).decode(),
            "format": "glb",
            "bytes": len(blob),
            "faces": int(len(mesh.faces)),
            "textured": bool(want_texture and out_path != shape_path),
            "timings": timings,
        }

    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return {
            "error": type(e).__name__ + ": " + str(e),
            "timings": timings,
            "elapsed_s": round(time.time() - t0, 2),
        }


runpod.serverless.start({"handler": handler})

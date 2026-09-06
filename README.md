# hunyuan3d-worker

Runpod Serverless worker for **Hunyuan3D 2.1**, built from Tencent's official
Hugging Face Space (`tencent/Hunyuan3D-2.1`) so the code path matches what Tencent runs.

Why the image is ~15GB instead of the official ~70GB: the Space ships a **prebuilt**
`custom_rasterizer` CUDA wheel, so we skip the CUDA devel toolchain + conda entirely.
Only the mesh-inpainting extension is compiled, and that is plain `c++`/pybind11.

The handler **fails at boot** if `mesh_inpaint_processor` is not the compiled extension:
the pure-python fallback returns correct results but is ~60x slower, so the only symptom
would be the invoice.

## API

`POST /run` (async) then poll `GET /status/{id}`.

```json
{ "input": { "image": "<base64 or url>", "texture": false } }
```

| field | default | notes |
|---|---|---|
| `image` | — | base64 or http(s) url, required |
| `texture` | `false` | run the PBR texture stage |
| `steps` | `30` | shape diffusion steps |
| `octree_resolution` | `256` | geometry detail |
| `face_count` | `40000` | decimation target |
| `max_num_view` | `6` | texture views (6@512 ≈ 21GB VRAM) |
| `texture_resolution` | `512` | raise to 768 for quality, more VRAM |

Returns `glb_b64`, `faces`, `bytes`, `textured`, and a `timings` breakdown.

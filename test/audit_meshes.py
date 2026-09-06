"""Measure the two generated assets: structure, topology, and how far apart they are.

Answers two questions the sensor-bank plan depends on:
  1. is the scene segmented into objects, or one fused blob?
  2. can cafe_hq be used as ground truth for cafe_textured?
"""
import sys
import pathlib
import numpy as np
import trimesh


def load(path):
    s = trimesh.load(path, process=False)
    parts = list(s.geometry.values()) if isinstance(s, trimesh.Scene) else [s]
    return s, parts


def report(path):
    print("=" * 62)
    print(path.name)
    print("=" * 62)
    scene, parts = load(path)
    print("geometrias en la escena : %d" % len(parts))
    for i, m in enumerate(parts):
        print("  [%d] verts=%d faces=%d" % (i, len(m.vertices), len(m.faces)))
        print("      watertight        : %s" % m.is_watertight)
        print("      winding consistent: %s" % m.is_winding_consistent)
        print("      volumen valido    : %s" % m.is_volume)
        print("      euler number      : %s" % m.euler_number)
        try:
            print("      cuerpos separados : %d" % m.body_count)
        except Exception:
            pass
        edges = m.edges_sorted.reshape((-1, 2))
        uniq, cnt = np.unique(edges, axis=0, return_counts=True)
        print("      aristas borde     : %d" % int((cnt == 1).sum()))
        print("      aristas non-manif : %d" % int((cnt > 2).sum()))
        uv = getattr(m.visual, "uv", None)
        print("      UVs               : %s" % ("si (%d)" % len(uv) if uv is not None else "NO"))
        bb = m.bounds
        print("      bbox              : %s" % np.round(bb[1] - bb[0], 4))
        # sliver / regularity
        areas = m.area_faces
        print("      area caras min/med/max: %.3e / %.3e / %.3e" % (areas.min(), np.median(areas), areas.max()))
        print("      caras area<1e-9   : %d" % int((areas < 1e-9).sum()))
    return parts


def chamfer(a, b, n=20000):
    """Symmetric point-to-point distance after normalising both to a unit box."""
    def norm(m):
        c = m.bounds.mean(axis=0)
        v = m.vertices - c
        return v / np.abs(v).max()

    rng = np.random.default_rng(0)
    A, B = norm(a), norm(b)
    A = A[rng.choice(len(A), min(n, len(A)), replace=False)]
    B = B[rng.choice(len(B), min(n, len(B)), replace=False)]

    def nn(P, Q):
        # brute force in chunks, no scipy needed
        out = np.empty(len(P))
        step = 512
        for i in range(0, len(P), step):
            d = np.linalg.norm(P[i:i + step, None, :] - Q[None, :, :], axis=2)
            out[i:i + step] = d.min(axis=1)
        return out

    d_ab = nn(A, B)
    d_ba = nn(B, A)
    return d_ab, d_ba


def main():
    here = pathlib.Path(__file__).resolve().parent
    p_tex = here / "cafe_textured.glb"
    p_hq = here / "cafe_hq.glb"

    parts_tex = report(p_tex)
    parts_hq = report(p_hq)

    a, b = parts_tex[0], parts_hq[0]
    print("=" * 62)
    print("DISTANCIA ENTRE LAS DOS GENERACIONES (normalizadas a caja unitaria)")
    print("=" * 62)
    d_ab, d_ba = chamfer(a, b)
    for name, d in (("textured -> hq", d_ab), ("hq -> textured", d_ba)):
        print("%s : media=%.4f  p50=%.4f  p95=%.4f  max=%.4f"
              % (name, d.mean(), np.percentile(d, 50), np.percentile(d, 95), d.max()))
    print()
    print("Escala: 1.0 = media caja delimitadora. Si estas dos fueran la misma forma")
    print("a distinta resolucion, la media deberia estar en el orden de 0.005-0.01.")


if __name__ == "__main__":
    main()

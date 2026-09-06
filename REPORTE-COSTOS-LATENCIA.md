# Hunyuan3D 2.1 en Runpod Serverless — costos y latencia medidos

**Fecha:** 2026-09-06 · **GPU:** NVIDIA A40 48 GB (pool `AMPERE_48`) · **Endpoint:** `pvm2ufn5kvlhul`
**Tarifa:** $1.22/hr = **$0.000339/s**

Todo lo que sigue son mediciones de corridas reales con `cafe render ref.JPG`, no estimaciones.

---

## El titular

| | |
|---|---|
| **Malla sola** | **~46 s** en worker tibio → **$0.016** |
| **Malla + textura PBR** | **~143 s** en worker tibio → **$0.048** |
| **Pico de VRAM** | **7.93 GiB** |
| Facturado en toda la sesión | **$0.2987** |

El texturizado tardó **99 segundos**, no las 2.4 horas que reportaban en GitHub. Ver la sección de validación.

---

## Latencia por etapa

### Corrida shape-only (handler v5)

| Etapa | Tiempo |
|---|---|
| Carga del modelo de forma (primera vez en el worker) | 72.4 s |
| Quitar fondo (rembg) | 0.14 s |
| **Generación de forma** (30 pasos, octree 256) | **23.86 s** |
| Limpieza + decimación 685,534 → 40,000 caras | 22.2 s |
| **Total del handler** | **118.8 s** |

Salida: GLB de **0.72 MB**, 40.000 caras.

### Corrida con textura (handler v10)

| Etapa | Tiempo |
|---|---|
| Quitar fondo | 0.14 s |
| **Generación de forma** | **22.69 s** |
| Limpieza + decimación | 20.72 s |
| **Textura PBR** (6 vistas @ 512) | **99.41 s** |
| **Total del handler** | **185.92 s** |

Salida: GLB de **5.31 MB**, 40.000 caras, con materiales PBR.

La forma reprodujo **23.69 / 23.66 / 23.72 / 23.95 / 22.69 s** en cinco corridas. Es un número estable, no una casualidad.

---

## Cold start — lo que más pesa

`delayTime` medido, o sea el tiempo entre encolar y que el worker levante el job:

| Situación | Observado |
|---|---|
| Worker **tibio** (segundo job seguido) | **0.48 s** |
| Imagen cacheada en el host, worker nuevo | 49.6 s – 62 s |
| Imagen nueva, host frío | **277 s – 295 s** |

**El pull de la imagen domina todo.** La imagen final pesa ~14 GB comprimidos (base CUDA `devel`, obligatoria — ver validación). Cada vez que se republica el digest, el primer worker paga ~5 minutos.

A eso se le suma, una vez por worker, la descarga de pesos desde HuggingFace: ~7.4 GB para forma, ~7 GB más para pintura.

---

## Costo por asset

| Escenario | Segundos | Costo |
|---|---|---|
| Malla, worker tibio | 46.2 | **$0.016** |
| Malla, incluyendo carga de modelo | 118.8 | $0.040 |
| Malla + textura, worker tibio | ~143 | **$0.048** |
| Malla + textura, incluyendo carga de modelo | 185.9 | $0.063 |
| Malla + textura, worker frío con pull de imagen | ~480 | $0.163 |

**Para producción el número a usar es $0.048 por asset texturizado**, siempre que el worker esté tibio.

### Un detalle que no esperaba

De los $0.2987 facturados, **$0.1775 son fee de plataforma y solo $0.1191 es GPU**. O sea que **el 59% de la factura no es cómputo**. A este volumen da igual, pero si esto escala a miles de assets conviene mirarlo: el fee no baja optimizando la inferencia.

---

## Validación del riesgo de las 2.4 horas

El reporte previo (`hunyuan3d-texturizado-reporte.md`) concluía que los reportes de texturizados de horas eran un **fallback de Python** por extensiones nativas sin compilar, y no el comportamiento normal.

**Confirmado en producción: 99.41 segundos.**

El worker arranca imprimiendo:

```
[boot] compiled mesh_inpaint_processor OK -> .../mesh_inpaint_processor.cpython-310-x86_64-linux-gnu.so
```

Ese assert está en el `handler.py` a propósito: si la extensión compilada falta, el worker **no arranca**. Un fallback silencioso costaría ~60x en la factura y devolvería resultados igual de correctos, o sea que el único síntoma sería la plata.

### Lo que el reporte previo decía mal

Yo afirmé que el wheel precompilado de `custom_rasterizer` que trae el Space de Tencent nos ahorraba el toolchain CUDA, y que por eso la imagen podía ser de 10 GB en vez de los 70 GB del Dockerfile oficial.

**Es falso.** Ese wheel está linkeado contra otra ABI de C++ de PyTorch y revienta al importar contra torch 2.5.1:

```
undefined symbol: _ZN3c106detail23torchInternalAssertFail...
```

Una extensión CUDA hay que compilarla contra el torch que embarcás. Hubo que pasar a base `nvidia/cuda:12.4.1-cudnn-devel` y compilar el rasterizer en el build (~100 s de `nvcc`). **Ese es exactamente el motivo por el que el Dockerfile oficial es tan pesado.**

Lo que sí sigue siendo cierto: el inpainting se compila con `c++` y pybind11, sin CUDA.

---

## Configuración del endpoint

| Parámetro | Valor | Por qué |
|---|---|---|
| `workersMin` | 0 | scale-to-zero, $0 en idle |
| `workersMax` | 1 | techo duro de gasto |
| `idleTimeout` | 10 s | apagar rápido |
| `executionTimeout` | 30 min | mata cualquier job colgado |
| `scalerType` | QUEUE_DELAY | más barato que REQUEST_COUNT |
| GPU pool | AMPERE_48 | A40 48 GB a $1.22/hr |

**La A40 sobra.** El pico real fue de **7.93 GiB**, contra los 29 GB que declara el README de Tencent para forma + textura. Una placa de 24 GB entra cómoda, y probablemente una de 12 también para shape-only.

Con los precios de Runpod, bajar a `AMPERE_24` (A5000/3090/L4, **$0.69/hr**) llevaría el asset texturizado de $0.048 a **$0.027**, casi la mitad. **Es la optimización más grande que queda pendiente**, y las mediciones de VRAM dicen que entra.

---

## Qué haría después

1. **Bajar a `AMPERE_24`.** Casi mitad de precio, y el pico de 7.93 GiB dice que entra sin drama.
2. **Network volume para los pesos.** Hoy cada worker nuevo baja 15 GB de HuggingFace. Un volumen de 20 GB sale ~$1.40/mes y elimina esa descarga de todos los cold starts.
3. **Achicar la imagen.** El `requirements.txt` del Space trae `gradio`, `fastapi`, `uvicorn` y `bpy` (~1 GB) que un worker headless no usa. Menos peso = cold starts más cortos.
4. **`idleTimeout` alto durante sesiones de trabajo.** Si generás assets de a tandas, pagás un cold start por sesión en vez de uno por pieza.

---

## Anexo: qué costó llegar acá

Diez builds. Los errores fueron **todos de empaquetado, ninguno del modelo ni de la infraestructura**:

| # | Error | Causa |
|---|---|---|
| 1 | `python3-config: command not found` | Ubuntu 22.04 trae `python3.10-config` |
| 2 | `cannot import name 'FaceReducer'` | el paquete real está en `hy3dshape/hy3dshape/` |
| 3 | `'Latent2MeshOutput' has no attribute 'faces'` | falta convertir con `export_to_trimesh` |
| 4 | `pymeshlab MeshSet has no attribute 'mesh_v'` | consecuencia del anterior |
| 5 | `ModuleNotFoundError: DifferentiableRenderer` | `hy3dpaint` fuera del `sys.path` |
| 6 | `libXi.so.6` | `bpy` necesita el stack de X11 |
| 7 | `undefined symbol: torchInternalAssertFail` | wheel con ABI de torch incompatible |
| 8 | `Getting requirements to build wheel` | `setup.py` importa torch, faltaba `--no-build-isolation` |
| 9 | `libc10.so` | mi assert importaba el kernel sin torch primero |

La raíz común: escribí el handler a partir de fragmentos del `gradio_app.py` en vez de leer el archivo completo y el layout del repo de entrada. Leer primero hubiera evitado los ítems 2, 3, 4 y 5.

Costo de esas diez iteraciones: **$0.30**. Iterar salió barato en plata; caro en tiempo.

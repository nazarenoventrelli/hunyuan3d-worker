# Hunyuan3D 2.1 worker for Runpod Serverless, built from Tencent official Space.
# devel base is required: the Space ships a prebuilt custom_rasterizer wheel, but it is
# linked against a different torch C++ ABI and dies at import, so the CUDA extension has
# to be compiled here against this image torch. That needs nvcc.
FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYOPENGL_PLATFORM=egl \
    HF_HOME=/runpod-volume/hf \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    CUDA_HOME=/usr/local/cuda \
    TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.10 python3.10-dev python3-pip \
      build-essential git git-lfs wget ca-certificates \
      libegl1 libgl1 libglx0 libgles2 libglvnd0 libglib2.0-0 libglu1-mesa \
      libxrender1 libsm6 libice6 libxext6 libgomp1 \
      libx11-6 libxi6 libxxf86vm1 libxfixes3 libxkbcommon0 libxkbcommon-x11-0 \
      libxrandr2 libxcursor1 libxinerama1 libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && ln -sf /usr/bin/python3.10-config /usr/bin/python3-config && python -m pip install -U pip

# torch first so the heavy layer caches independently
RUN pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 \
      --index-url https://download.pytorch.org/whl/cu124

WORKDIR /app
# Tencent's official Space = the exact code they run in production
RUN git lfs install && git clone --depth 1 https://huggingface.co/spaces/tencent/Hunyuan3D-2.1 /app

RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir runpod hf_transfer pybind11

# The Space ships a prebuilt custom_rasterizer wheel, but it is linked against a
# different torch C++ ABI than torch 2.5.1 and fails at import with
# "undefined symbol: _ZN3c106detail23torchInternalAssertFail...". Build from source.
RUN set -eux; \
    if [ -d hy3dpaint/custom_rasterizer ]; then SRC=hy3dpaint/custom_rasterizer; \
    elif [ -d hy3dpaint/packages/custom_rasterizer ]; then SRC=hy3dpaint/packages/custom_rasterizer; \
    else echo "custom_rasterizer source not found:"; find . -maxdepth 4 -name "custom_rasterizer*" ; exit 1; fi; \
    echo "building $SRC"; cd "$SRC"; pip install --no-cache-dir --no-build-isolation . ; \
    cd /app; python -c "import torch, custom_rasterizer, custom_rasterizer_kernel; print('custom_rasterizer OK')" 

# compile the mesh inpainting extension. Plain c++/pybind11, no CUDA.
# Without this the texture stage silently falls back to pure Python and is ~60x slower.
RUN cd hy3dpaint/DifferentiableRenderer && bash compile_mesh_painter.sh \
 && ls -la mesh_inpaint_processor*.so

RUN mkdir -p hy3dpaint/ckpt \
 && wget -q https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth \
      -P hy3dpaint/ckpt

COPY handler.py /app/handler.py
CMD ["python", "-u", "/app/handler.py"]

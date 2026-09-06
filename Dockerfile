# Slim image for Hunyuan3D 2.1 on Runpod Serverless.
# Built from Tencent's official Space, which ships a PREBUILT custom_rasterizer wheel
# -> we do not need the CUDA devel toolchain (the official Dockerfile is >70GB because of it).
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYOPENGL_PLATFORM=egl \
    HF_HOME=/runpod-volume/hf \
    HF_HUB_ENABLE_HF_TRANSFER=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.10 python3.10-dev python3-pip \
      build-essential git git-lfs wget ca-certificates \
      libegl1 libgl1 libglx0 libgles2 libglvnd0 libglib2.0-0 \
      libxrender1 libsm6 libxext6 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && python -m pip install -U pip

# torch first so the heavy layer caches independently
RUN pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 \
      --index-url https://download.pytorch.org/whl/cu124

WORKDIR /app
# Tencent's official Space = the exact code they run in production
RUN git lfs install && git clone --depth 1 https://huggingface.co/spaces/tencent/Hunyuan3D-2.1 /app

RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir runpod hf_transfer pybind11

# prebuilt CUDA rasterizer wheel that ships in the Space root
RUN pip install --no-cache-dir ./custom_rasterizer-0.1-cp310-cp310-linux_x86_64.whl

# compile the mesh inpainting extension. Plain c++/pybind11, no CUDA.
# Without this the texture stage silently falls back to pure Python and is ~60x slower.
RUN cd hy3dpaint/DifferentiableRenderer && bash compile_mesh_painter.sh \
 && ls -la mesh_inpaint_processor*.so

RUN mkdir -p hy3dpaint/ckpt \
 && wget -q https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth \
      -P hy3dpaint/ckpt

COPY handler.py /app/handler.py
CMD ["python", "-u", "/app/handler.py"]

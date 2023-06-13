#!/bin/bash
export PYTORCH_CUDA_ALLOC_CONF=garbage_collection_threshold:0.75,max_split_size_mb:512
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
export COMMANDLINE_ARGS="--xformers --no-hashing --enable-insecure-extension-access --share --no-half-vae --ckpt /content/sd/models/Stable-diffusion/model.safetensors --disable-safe-unpickle --disable-console-progressbars --ui-settings-file settings.json --skip-torch-cuda-test --opt-channelslast --upcast-sampling"
export ACCELERATE="True"
python launch.py
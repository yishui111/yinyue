# -*- coding: utf-8 -*-
r"""
把 openvpi 0211_opencpop_ds1000_keyshift（v1.7 时代旧格式 ckpt）迁移成 v2.5.1 可加载的格式。

旧格式（TokenTextEncoder，词表=3 保留符 + 64 音素 = 67）：
  model.fs2.txt_embed.weight      [67, 256]   id: PAD=0,EOS=1,UNK=2,AP=3,E=4,En=5,SP=6,a=7...
  model.fs2.encoder.embed_tokens  (与 txt_embed 重复，v2.5.1 官方忽略)
  model.denoise_fn.* / model.betas / model.spec_min ...（diffusion 子模块，无前缀）
新格式（PhonemeDictionary，PAD=0,AP=1,E=2,En=3,SP=4,a=5...，len=65）：
  fs2.txt_embed.weight [65,256]，diffusion.denoise_fn.*，diffusion.betas...

迁移动作：
  1) 非 fs2. 的键加 diffusion. 前缀（官方 v2.0.0 migrate.py 同款逻辑）
  2) txt_embed 行重映射：新 id k(k>=1) ← 旧 id k+3；新 PAD 行(0)置零
  3) category='acoustic'，清空 optimizer 状态省磁盘
"""
import sys
from collections import OrderedDict

import torch

SRC = "checkpoints/0211_opencpop_ds1000_keyshift/model_ckpt_steps_360000.old.ckpt"
DST = "checkpoints/0211_opencpop_ds1000_keyshift/model_ckpt_steps_360000.ckpt"
OLD_RESERVED = 3   # PAD / EOS / UNK

ckpt = torch.load(SRC, map_location="cpu", weights_only=False)
sd = ckpt["state_dict"]

new_sd = OrderedDict()
for k, v in sd.items():
    core = k[len("model."):] if k.startswith("model.") else k
    if core == "fs2.txt_embed.weight":
        # 行重映射：旧词表多 2 个保留符（EOS/UNK），新 id k(k>=1) ← 旧 id k+2；新 PAD 行置零
        new_rows = [torch.zeros_like(v[0])]
        for new_id in range(1, 65):
            new_rows.append(v[new_id + 2])
        new_sd["model." + core] = torch.stack(new_rows, dim=0)
        print("remap %s: %s -> %s" % (core, tuple(v.shape), tuple(new_sd["model." + core].shape)))
    elif core == "fs2.encoder.embed_tokens.weight":
        print("drop  %s（与 txt_embed 重复，官方迁移同款处理）" % core)
    elif core.startswith("fs2."):
        new_sd[k] = v
    elif core.startswith("denoise_fn.") or core in (
            "betas", "alphas_cumprod", "alphas_cumprod_prev", "sqrt_alphas_cumprod",
            "sqrt_one_minus_alphas_cumprod", "log_one_minus_alphas_cumprod",
            "sqrt_recip_alphas_cumprod", "sqrt_recipm1_alphas_cumprod",
            "posterior_variance", "posterior_log_variance_clipped",
            "posterior_mean_coef1", "posterior_mean_coef2", "spec_min", "spec_max"):
        new_sd["model.diffusion." + core] = v
    else:
        print("keep? %s" % k)
        new_sd[k] = v

ckpt["state_dict"] = new_sd
ckpt["category"] = "acoustic"
if isinstance(ckpt.get("optimizer_states"), list) and ckpt["optimizer_states"]:
    ckpt["optimizer_states"][0]["state"].clear()
torch.save(ckpt, DST)
print("已保存:", DST)

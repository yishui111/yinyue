# 二次元唱歌换声 · 三引擎 + 总控页 + 端到端

把一首歌里的原声换成二次元角色的音色（唱得一模一样，音色全换）。整个目录是一套
本地 GPU 推理系统：

| 目录 | 是什么 | 引擎 | 端口 |
|---|---|---|---|
| `0-web/` | **总控页**（我写的）：一个网页对应下面全部服务，状态灯实时反映服务健康 | — | 8100 |
| `1-rvc/` | RVC 换声/训练 WebUI（换音色不换时长语调，说话唱歌都能换） | [RVC-Project/Retrieval-based-Voice-Conversion-WebUI](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI)（固定 `81eed5e`） | 7865 |
| `2-gpt-sovits/` | GPT-SoVITS 文字转二次元语音（旁白/台词，零样本克隆） | [RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)（固定 `d523079`） | 9880 (API) |
| `3-so-vits-svc/` | so-vits-svc 4.1-Stable，**核心引擎**：歌曲原声 → 角色音色，保留旋律 | [svc-develop-team/so-vits-svc](https://github.com/svc-develop-team/so-vits-svc)（4.1-Stable 分支） | 6843 |
| `4-e2e/` | **端到端**（我写的）：音乐视频 → 提音轨 → 人声伴奏分离 → 换二次元音色 → 混音 → 封装回视频 | 调 6843 | — |
| `获取旋律/` | **旋律工作台**：歌曲 → 分离人声 → 提旋律/提歌词 → song.json → DeepSeek 依曲填词 | Demucs + librosa.pyin + faster-whisper + DeepSeek | 8765 |
| `会唱歌/` | **唱出来**（我写的）：song.json + 填好的新词 → DiffSinger 直接唱出人声 → 自带 `换声引擎\`（so-vits 推理代码 + 6 个二次元角色音色）本地换声，**自包含不依赖其他目录** | [openvpi/DiffSinger](https://github.com/openvpi/DiffSinger)（v2.5.1 + 官方 0211 中文声学模型）+ so-vits-svc 4.1 推理 | 8102 |
| `会唱歌/训练/` | **训练工作台**：自己的素材 → so-vits-svc 4.1 唱歌音色，训完自动进换声引擎 | so-vits-svc 4.1 训练（含官方 vec768l12 底模） | 8103 |

**这个仓库只提交我自己写的部分**：总控页（`0-web/`）、自研换声服务
`3-so-vits-svc/svc_service.py`、端到端流水线（`4-e2e/`）、各引擎的
启动/停止/自测/装环境脚本、精简依赖清单和文档。引擎源码、`runtime\py312` 便携
Python 环境、模型权重、ffmpeg 都不进仓库，换电脑时按本文档重装。

版本基线：Windows 10 / RTX 4080 16GB / Python 3.12 / torch 2.7.1+cu118。
踩坑与补丁的完整记录见 [部署说明.md](部署说明.md)。

---

## 一、日常使用

每个引擎目录里都是同一套脚本，双击即用：

```
启动.bat        开服务（关掉黑窗口 = 停服务）
停止.bat        按端口结束进程
运行测试.bat     跑一遍自测，产物在 输出\ 目录
安装环境.bat     环境坏了 / 重装依赖时用（要联网，见部署说明）
```

一次全开：根目录 `全部启动.bat`（总控页 + 三引擎）；全停：`全部停止.bat`。
三个引擎同时开会抢显存，训练时建议只开一个。

| 服务 | 双击 | 地址 |
|---|---|---|
| 总控页 | `0-web\启动.bat` | http://127.0.0.1:8100 |
| so-vits 唱歌换声 | `3-so-vits-svc\启动.bat` | http://127.0.0.1:6843 |
| GPT-SoVITS 文字转语音 | `2-gpt-sovits\启动.bat` | http://127.0.0.1:9880 |
| RVC 换声 WebUI | `1-rvc\启动.bat` | http://127.0.0.1:7865 |
| 旋律工作台 | `获取旋律\start.bat` | http://127.0.0.1:8765 |
| 会唱歌（DiffSinger） | `会唱歌\启动.bat` | http://127.0.0.1:8102 |
| 视频换声端到端 | `4-e2e\运行测试.bat` | 依赖 6843 先跑起来 |

接口速查：

```bash
# so-vits 唱歌换声（角色列表 GET /models）
curl -X POST -F "audio=@input.wav" ^
  "http://127.0.0.1:6843/svc/change_voice?model=furina&transpose=0&auto_f0=1" -o out.wav

# GPT-SoVITS 文字转语音（零样本，带参考音频）
curl "http://127.0.0.1:9880/tts?text=晚上好&text_lang=zh&ref_audio_path=models/ayaka/ref.wav&prompt_text=晚上好…&prompt_lang=zh" -o tts.wav

# 会唱歌：song.json（获取旋律 工作台导出）+ DeepSeek 填好的新词 → 唱出人声
# 命令行：runtime\py312\python.exe sing.py song.json 填词.json [--role furina]
curl -X POST --data @req.json http://127.0.0.1:8102/sing -o 唱歌.wav
```

## 二、仓库里有什么（我写的部分）

```
0-web/
├── web_service.py        总控服务（纯标准库 HTTP + 反代，不起任何模型）
├── rvc_convert.py        RVC 换声辅助（子进程跑 1-rvc 同款推理管线）
├── 克隆运行环境.py        runtime\py312 缺失时从 1-rvc / 4-e2e 硬链接克隆
├── static/index.html     总控页前端（离线可用）
├── tests/selftest.py     自测：页面板块与四个项目的接口一一对应
└── 启动/停止/运行测试/安装环境.bat

3-so-vits-svc/
├── svc_service.py        自研换声 HTTP 服务：扫描 models\ 自动出角色列表
├── requirements-infer.txt 自研推理最小依赖清单（训练另装 fairseq 等，见官方 requirements）
└── tests/                自测脚本 + 测试音频

4-e2e/
├── e2e_test.py           视频 → 分离 → 换声 → 混音 → 封装 全流程
├── testdata/输入.mp4      测试输入（32 秒音乐视频，随仓库走）
├── requirements.txt
└── 说明.md               用法与耗时参考（RTX 4080 实测 32 秒视频 36 秒出片）

1-rvc/ 2-gpt-sovits/      各自的 启动/停止/运行测试/安装环境.bat、说明.md、
                          tests\、转为便携环境.py、整理好的依赖清单
全部启动.bat / 全部停止.bat
部署说明.md                完整部署记录：版本固定、补丁清单、镜像地址、踩坑
```

## 三、从零部署（换电脑照着做）

### 0. 基础环境

- Windows 10/11 x64 + NVIDIA 显卡（8GB 以上）；CUDA 11.8
- Python 3.12（只在重建环境时需要）
- ffmpeg（4-e2e 要用；可以不做系统 PATH，脚本会找 `runtime\ffmpeg\`）
- 网络：GitHub `git -c http.proxy=http://127.0.0.1:<端口> clone`；pip 清华镜像
  （高峰限流就换阿里云 `--index-url https://mirrors.aliyun.com/pypi/simple/`）；
  torch 用 `--index-url https://mirrors.nju.edu.cn/pytorch/whl/cu118`；
  HuggingFace 一律走 `https://hf-mirror.com`

### 1. 拉引擎源码（固定 commit，保证和我这套封装兼容）

```bat
git clone https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git 1-rvc
cd 1-rvc && git checkout 81eed5e && cd ..
git clone https://github.com/RVC-Boss/GPT-SoVITS.git 2-gpt-sovits
cd 2-gpt-sovits && git checkout d523079 && cd ..
git clone -b 4.1-Stable https://github.com/svc-develop-team/so-vits-svc.git 3-so-vits-svc
```

### 2. 装依赖

每个引擎各自建环境（不要共用，依赖会打架）：

```bat
:: 通用底子：torch 2.7.1+cu118
pip install torch==2.7.1+cu118 --index-url https://mirrors.nju.edu.cn/pytorch/whl/cu118

:: RVC
pip install -r 1-rvc\requirments_cu118_py312.txt
:: GPT-SoVITS（注意用我整理的 local 版）
pip install -r 2-gpt-sovits\requirements-local.txt
:: so-vits 推理最小集
pip install -r 3-so-vits-svc\requirements-infer.txt
:: 端到端（人声分离 pymss 等）
pip install -r 4-e2e\requirements.txt
```

嫌麻烦可以直接双击各目录的 `安装环境.bat`（内部就是上面这套，加了镜像和顺序处理）。

### 3. 模型权重（都不在仓库里）

- RVC 底模：hubert_base、rmvpe、pretrained_v2 训练底座 → `1-rvc\assets\`
- GPT-SoVITS v2 预训练底模 + G2PW 注音模型 → `2-gpt-sovits\GPT_SoVITS\pretrained_models\`、`GPT_SoVITS\text\G2PWModel\`
- so-vits 预训练件：contentvec(onnx)、nsf_hifigan、rmvpe → `3-so-vits-svc\pretrain\`
- 4-e2e 人声分离模型：bs_roformer_voc_hyperacev2 → `4-e2e\models\pymss\`

全部从 `https://hf-mirror.com` 按上游 README 的路径下载；放的位置各目录 `说明.md` 里都有。

### 4. 角色模型

`3-so-vits-svc\models\<角色名>\` 放角色 ckpt（`svc_service.py` 扫描该目录自动出角色列表，
页面/接口直接按名字调用）；`2-gpt-sovits\models\<角色>\` 放 GPT-SoVITS 的四件套
（ckpt + pth + ref.wav + ref_text.txt）。训练新角色用 `1-rvc` 的训练中心，流程见其 `说明.md`。

### 5. 启动与验收

```bat
全部启动.bat                       :: 总控页状态灯全绿即可使用
3-so-vits-svc\运行测试.bat          :: 逐引擎自测
4-e2e\运行测试.bat                  :: 32 秒视频全流程，约 36 秒出片（RTX 4080 空载）
```

## 四、我对上游动过的地方（重装后要重打）

完整清单和原因都在 [部署说明.md](部署说明.md)，速记：

- **GPT-SoVITS**：`GPT_SoVITS/text/chinese.py`、`tone_sandhi.py`、`chinese2.py` 里
  `jieba_fast` → `jieba`（jieba_fast 没有 py3.12 轮子）；`transformers==4.49.0`
  （4.50 加载 roberta bin 会报错）；`starlette<1.0`（1.x 改了 TemplateResponse 签名，
  gradio 4.44.1 页面起不来）；`opencc` 用纯 Python 替代品；`pyopenjtalk` 不装不影响中文。
- **so-vits-svc**：`cluster/__init__.py` 的 `torch.load` 加 `weights_only=False`
  （torch 2.6+ 默认值变了）；onnxruntime-gpu 要的 cuDNN 8 通过
  `nvidia-cudnn-cu11==8.9.5.29` 等 pip 包补齐，`svc_service.py` 启动时自动把 DLL 目录挂进搜索路径。
- **RVC / so-vits**：官方 requirements 里 `numpy==1.23.5` 等是 py3.12 老古董，
  推理清单放宽到 `numpy<2` + 新 scipy。

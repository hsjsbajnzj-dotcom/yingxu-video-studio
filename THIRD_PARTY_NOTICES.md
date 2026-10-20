# 外部组件与许可边界

核查日期：2026-10-20。以下不是完整SBOM，也不是向这些组件授予新许可。
候选版没有捆绑这些项目源码、二进制、模型权重或运行环境。

| 组件 | 已核查的来源/许可 | 发布处理 |
| --- | --- | --- |
| ComfyUI 0.42.1 | [官方GPLv3文本](https://github.com/Comfy-Org/ComfyUI/blob/v0.42.1/LICENSE) | 外部独立安装；若未来复制或捆绑，重新核查源码和声明义务 |
| Creator插件（已安装版本） | 本机LICENSE为MIT，版权声明roadmaus；[上游现址](https://github.com/roadmaus/ComfyUI-Continuity/blob/main/LICENSE) | 候选不复制插件；保持版本/接口兼容记录。上游改名不等同于本机已升级 |
| WanGP 18.19 | [固定提交的Community License 2.0](https://github.com/deepbeepmeep/WanGP/blob/fdc63bdf89358fb13c93cf6b38693fd89a859f00/LICENSE.txt) | 独立安装与适配。包含受限商业化条款，不标作MIT或无条件商用；互操作本身不当然让独立项目受其许可约束 |
| MiniMax H3 | [官方社区许可](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE) | 不捆绑权重。许可包含地域、再分发、用途与服务保障要求；“只提供适配器”不等于已完成合规 |
| FFmpeg | [官方许可说明](https://github.com/FFmpeg/FFmpeg/blob/master/LICENSE.md) | 不捆绑可执行文件；实际构建选项可能影响义务，不能把所有构建一律标为LGPL |
| Wan2.2、MMAudio、Real-ESRGAN、SeedVR2、FlashVSR系列、LoRA、文本编码器和相关Python包 | 本轮未逐版本核完 | 发布前补具体来源、版本、模型卡与许可；暂不附带或自动下载 |

H3当前许可列出的排除地区包括欧盟、英国、韩国、美国；这不是对所有独立界面代码的地域认定，
但明确意味着不能宣传H3模型/相关整合服务“全球无限制可用”。必须核查实际发布方式和下游义务。

WanGP对收费接入、付费托管、白标和销售软件等有专门条件；用它内部制作作品与出售软件接入不是同一件事。
不要把本项目的未来开源许可当作对外部模型、引擎、服务、商标和用户素材的许可。

网页基础依赖psutil 7.0.0（BSD-3-Clause）；媒体依赖scenedetect-headless 0.7.1（BSD-3-Clause），通过官方PyPI安装，不复制原机vendor。其传递依赖含NumPy、OpenCV headless、Click、platformdirs、tqdm、colorama；已验证版本见constraints-win-py312.txt。各发行包的LICENSE/NOTICE独立保留，安装器不替换它们。该列表不是完整法律审计或带依赖二进制再分发许可。

官方包信息：[psutil](https://pypi.org/project/psutil/7.0.0/)、[PySceneDetect headless](https://pypi.org/project/scenedetect-headless/0.7.1/)。若未来打包这些依赖，必须逐个核对发行包及其捆绑库的许可声明，不能直接沿用“源码不捆绑”的处理方式。

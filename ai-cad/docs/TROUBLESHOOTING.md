# 已知问题与排障手册

本机环境的实际踩坑记录，含解法。新问题按同格式追加。

## 1. build123d 导入即崩：系统字体损坏

**症状**：`import build123d` 抛 `fontTools.ttLib.TTLibError: Not a TrueType or OpenType
font (bad sfntVersion)`。

**原因**：build123d 0.11.1 在 import 时扫描 `C:/Windows/Fonts`，本机 `mstmc.ttf`
是损坏的假 TTF。

**解法**（已打补丁）：`D:\PythonProject\Python312\Lib\site-packages\build123d\text.py`
的 `register_font` 方法已包 try/except 跳过坏字体。

**复发条件**：升级/重装 build123d 会覆盖补丁 → 重新打（改动见 git 历史或
ROADMAP 环境备注）。定位新坏字体的方法：用 fontTools 遍历字体目录找非 TrueType 文件。

## 2. pip 网络故障：镜像索引通、文件下载挂

**症状**：`pip install <pkg>` 卡在 "Looking in indexes" 后无输出直至超时；
`pip -vv` 显示索引页 304 成功后挂起。

**原因**：清华镜像的索引页可达，但 wheel 下载链接指向 `files.pythonhosted.org`
（国内直连常超时）。

**解法**：

```powershell
cd D:\AI\project\Company\AImodeling\ai-cad
# 编辑 scripts/download_wheels.py 的 PACKAGES 列表后：
$env:PYTHONIOENCODING='utf-8'; python scripts\download_wheels.py
pip install --no-input --no-index --find-links .wheels <pkg>
```

注意：pip 安装需要写 DSH 临时目录，沙箱下要提权执行（DSH 会话内）。
`.wheels/` 里已缓存：jsonschema 系、pytest 系。

## 3. PowerShell 的 HTTPS 全部失败（Schannel）

**症状**：`Invoke-WebRequest` 任何 HTTPS（含百度）都报 "SSL connection could not
be established"；Python 的 urllib 却正常。

**原因**：本机代理软件（127.0.0.1:7890）对 Schannel（.NET/PowerShell 的 TLS 栈）
的干扰；Python 用 OpenSSL + 独立证书链不受影响。

**解法**：**下载类操作一律用 Python，不用 Invoke-WebRequest/curl.exe**。
`download_wheels.py` 就是这个原则的产物。

## 4. Windows GBK 控制台编码错误

**症状**：`UnicodeEncodeError: 'gbk' codec can't encode character`（通常是 ³ 或 ✅）。

**解法**：

```powershell
$env:PYTHONIOENCODING='utf-8'   # 每个会话设一次
```

长期产出型脚本（如 examples/phase1_box_with_hole.py）自带
`sys.stdout.reconfigure(encoding="utf-8")`，但 subprocess 里跑的子脚本继承的是
父进程环境，所以环境变量仍要设。

## 5. pytest 在沙箱下的限制

**症状**：`PermissionError: [WinError 5]` 指向 `Temp\...\pytest-of-*` 或
`.pytest_cache`。

**原因**：DSH 文件沙箱限制写入工作区外/隐藏目录。

**解法**：
- 永远加 `-p no:cacheprovider`
- 测试内不用 `tmp_path` fixture，用项目内固定目录（`output/tests/`）
- 在测试里 `subprocess.run(..., encoding='utf-8')` 显式指定编码（默认 GBK 会炸）

## 6. OCCT revolve 返回 0 体积

**症状**：`revolve(profile, axis=Axis.X)` 成功执行但体积为 0。

**原因**：OCCT 要求**旋转轴必须位于轮廓所在平面内**；全局轴 + 偏移平面的组合
静默产出空体。

**解法**：实现 revolve 时生成器必须校验/构造轴在平面内的布局（v1.1 待办，
见 ROADMAP）。教训已写入 DEVELOPMENT.md 的"探针先行"。

## 7. IR 参数引用不能取负/做算术

**症状**：需要 `-25` 或 `base_depth/2 - 3` 时无从表达。

**现状**：v1.0 数值字段只接受字面量或 `{"param": ...}`（正值引用）。
镜像位置写字面量；派生尺寸 DSH 换算后写字面量并在 meta.description 注明依赖。
表达式支持是 v1.1 候选（IR_SPEC.md 已知局限节）。

# TRACE32 API 自动化智能调试与烧录监控工具 (V2)

基于 Python 与 Lauterbach TRACE32 RCL API (`lauterbach.trace32.rcl`) 开发的自动化调试、烧录与稳定性监控脚本，为团队后续开发 SARA 提供接口。

---

## 🆕 新增功能特性

相比于上次的功能，新增和优化了以下自动化能力：

| 特性 | 说明 |
| --- | --- |
| **新增项目自动识别** | 通过路径关键词自动匹配 `project_versions.json` 配置，方便扩展新项目 |
| **固件版本提取和打印** | 自动扫描 `.map` 文件解析版本符号地址，从 `.s19`/`.hex` 中提取版本 ID 和字符串 |
| **彩色终端输出** | 项目名（青色）、固件版本（蓝色）、芯片型号（黄色）、AREA 输出（绿色）分色显示 |
| **AREA 转储** | 自动将 TRACE32 AREA 窗口内容保存到log日志文件，同时实时打印到终端 |
| **3 分钟稳定性监控** | 根据调用TRACE的STATE("RUN")状态命令，简要判断运行状态是否正常|
| **全量日志记录** | 自动在 `logdir/` 按时间戳生成通讯日志，记录每次 `cmd`/`fnc` 调用 |


---

## 项目结构

```
Commmon_lautxx/
├── debugV2.bat                          # 一键启动脚本（Windows CMD）
├── Scripts-common/
│   ├── api_debug.py                     # 主入口：参数解析、流程编排
│   ├── t32_helpers.py                   # TRACE32 连接、AREA 读取、日志包装
│   ├── flash_ops.py                     # Flash 烧录与 UCB 编程
│   ├── stability.py                     # 3 分钟稳定性监控
│   ├── firmware_version_extractor.py    # .map/.s19/.hex 版本提取
│   └── project_versions.json            # 项目→版本地址映射配置
├── lauterbach-common/
│   └── Tools/laut-tc3xx-VCUPLUS/        # TRACE32 辅助脚本（TargetAutoDetect, ProgramUcbs...）
├── test-Video/                          # 测试演示视频
├── logdir/                              # 自动生成的运行日志
├── .gitignore
└── readme.md
```

---

## 测试效果

> **相同固件烧录**（跳过烧录直接进入稳定性测试）：

[![相同固件烧录效果](image-1.png)](test-Video/相同固件烧录调试效果.mp4)

> **不同固件烧录**（自动比对 → 擦除烧录 → 重启交互 → 稳定性测试）：

[![不同固件烧录效果](image-2.png)](test-Video/不同固件烧录调试效果.mp4)

> **log日志输出**：

![alt text](image-1.png)

> **烧录验证**： 通过 hexview 工具和 TRACE32 的 dump 功能对比烧录前后 Flash 内容完全一致:

![alt text](image-2.png)

使用本调试环境：项目自动识别、固件版本自动提取、芯片自动探测、强制烧录（或差异跳过）、UCB 编程、3 分钟稳定性测试。**理论上可脱离具体项目，在任何使用 TRACE32 的嵌入式项目中复用**，只需传入对应的参数即可。

测试项目: VCUPLUS，芯片型号：英飞凌 TriCore TC397X。

---

## 与纯 CMM 脚本的区别

| 对比维度 | 纯 CMM (PRACTICE) 脚本 | Python + API (pyrcl) |
| --- | --- | --- |
| **编程语言与生态** | 使用专有的 PRACTICE 语言，语法老旧，无第三方库。处理字符串操作、文件路径解析、格式校验繁琐。 | 拥有庞大的标准库和第三方库（如 `argparse`, `os`）。逻辑处理、正则匹配、数据结构操作极其高效。 |
| **运行环境与通信** | **内部执行**：直接运行在 `t32m*.exe` 引擎内部进程中，与调试器内核紧密耦合。 | **外部进程**：运行在独立的 OS 进程中，通过 RPC/Socket (端口 20000) 与 TRACE32 后台服务进行跨进程通信。 |
| **异常处理与鲁棒性** | **阻塞式报错**：缺乏现代异常捕获机制。遇到严重硬件错误（如 Flash 驱动缺失、无目标板）时，易触发 GUI 弹窗，**导致自动化流程永久挂起**，需人工干预。 | **非阻塞式捕获**：支持标准的 `try...except...finally`。遇到底层崩溃可直接捕获异常、记录日志并安全退出，**保证 CI/CD 流水线无人值守运行**。 |
| **外部工具链集成** | **孤立系统**：难以与其他测试环境交互。无法直接控制 CANoe 发送报文，也无法直接与 Jenkins、GitLab CI/CD 平台进行标准化交互。 | **无缝集成**：可作为"胶水层"轻松集成到任何持续集成系统中。可以在同一脚本内同时控制 TRACE32、串口工具、CAN 盒，并生成测试报告。 |
| **最佳应用场景** | **底层硬件强相关任务**：芯片寄存器初始化、Flash 扇区划分、RAM Code 烧录引擎挂载、底层安全解锁 (HSM)。 | **高层业务与流程控制**：批量测试调度、固件版本对比与文件路由、长时间稳定性轮询监控、自动化测试报告生成。 |

**本调试脚本方法:**
保留 CMM 脚本用于处理极少数底层 Flash 驱动挂载与时钟初始化（调用官方现成脚本），而将整个项目的命令行解析、文件调度、状态监控和测试逻辑完全交由 Python 统筹。

---

## 环境依赖 (Prerequisites)

1. **Python 环境**: Python 3.7+
2. **Lauterbach API 包**:
```bash
& C:\toolbase\python\3.9.17.0.0\python-3.9.5.amd64\python.exe -m pip install lauterbach-trace32-rcl
```

3. **TRACE32 软件**:
   - 默认硬编码安装路径为：`C:\China_Convergence\VP_Artifactorytools\trace32\2022.09.000154087\files\bin\windows64`
   - *(如团队中 TRACE32 安装路径不同，请在 `api_debug.py` 第 42 行修改 `t32_base_path` 变量)*。

---

## 核心特性 (Key Features)

* **🌍 多架构路由 (Multi-Arch Routing)**
  - 无需手动切换 T32 引擎，通过 `--arch` 参数动态拉起对应架构的 TRACE32 核心（已支持英飞凌 TriCore、NXP ARM/PowerPC、瑞萨 RH850 等不同芯片/架构的引擎调起）。

* **⚡ 智能差异烧录 (Smart Diff-Flash)**
  - 烧录前自动进行待选固件与目标板 Flash 的差异比对。若当前固件与目标文件完全一致，将跳过擦写流程；若不同则自动挂载驱动并进行下载烧录。
  - 烧录阶段实时显示各阶段耗时（PFlash 写入耗时、UCB 编程耗时），无需进度条。

* **🔐 UCB 编程 (User Configuration Blocks)**
  - 烧录完成后自动检测固件中是否包含 UCB 数据。若包含则自动调用 `ProgramUcbs.cmm` 完成 UCB 编程，并通过 AREA 输出验证结果（OK/NOK）。

* **📁 项目自动识别与固件版本显示 (Project Detection)**
  - 通过路径关键词自动匹配 `project_versions.json` 中的项目配置。
  - 自动查找 `.map` 文件并提取固件版本 ID 和版本字符串（支持 APP/BL/BM 分区）。
  - 终端以彩色显示：**项目**（青色）、**固件版本**（蓝色）、**芯片型号**（黄色）。

* **🔍 芯片自动探测 (Chip Auto-Detection)**
  - 上电后自动通过调试接口识别芯片型号（如 TC397XP），无需手动指定。
  - 优先使用仓库内的 `TargetAutoDetect.cmm` 进行 Flash 驱动挂载，失败则回退到官方 demo 脚本。

* **📋 AREA 内容转储 (AREA Dump)**
  - 自动将 TRACE32 AREA 窗口的运行输出保存到日志文件，同时以绿色打印到终端，方便实时查看烧录过程中的详细状态信息。

* **🛡️ 稳定运行状态监控 (Hardware-Level Monitoring)**
  - 通过读取片内调试模块上的状态寄存器和 PC 指针变化，综合判断运行过程中是否发生异常。
  - **快轮询**：每秒检查 CPU 运行状态，捕获意外停机与异常复位 (Trap/Reset)。
  - 监控时长：**3 分钟**（180 秒），可扩展。

* **📝 固件格式防呆 (Format Safety)**
  - 强制显式声明 `--s19` / `--hex` / `--srec`，利用参数互斥锁避免格式歧义，彻底杜绝自动化脚本"找错文件"的隐患。

* **📼 Log 文件自动保存 (Full API Logging)**
  - 自动在 `logdir/` 目录下按时间戳生成通讯日志，无死角记录每一次 `dbg.cmd` 与 `dbg.fnc` 的下发与返回结果，便于底层软硬件时序问题的复盘。

---

## 快速开始 (Usage)

### 命令行参数说明

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `--dir` | 字符串 | **是** | 固件 (HEX/S19) 与符号表 (OUT/ELF) 所在的绝对文件夹路径 |
| `--s19` / `--hex` / `--srec` | 字符串 | **是** | **【三选一】** 指定要烧录的固件格式及名称（不带后缀即可） |
| `--out` | 字符串 | 否 | 符号表名称（不带后缀）。如果不传，稳定性监控只能打印十六进制地址；传了则可反查 C 语言函数名 |
| `--arch` | 字符串 | 否 | 目标芯片架构。可选值：`tricore`, `arm`, `ppc`, `rh850`。默认值：`tricore` |
| `--force` | 开关标识 | 否 | 强制烧录模式。启用后将无视目标板的现有固件，跳过比对直接执行全局擦除与烧录 |

### 典型使用场景 (Examples)

#### 场景 1：正常测试

传入 `.hex` 固件和 `.out` 符号表，采用默认的 `tricore` 架构。**脚本会自动比对，若固件未改变则瞬间跳过烧录直接开始测试。**

```powershell
.\debugV2.bat --dir C:\ProjectCode\VCUPlus\Build\Output_GM_VCUPLUS_APP_TC397X_debug\SoftwarePackets\Hex_Files --hex GM_VCUPLUS_ND_withPP --out GM_VCUPLUS
```

#### 场景 2：强制覆盖烧录并测试

加上 `--force` 参数强制重新擦写：

```powershell
.\debugV2.bat --dir .\debugV2.bat --dir C:\ProjectCode\VCUPlus\Build\Output_GM_VCUPLUS_APP_TC397X_debug\SoftwarePackets\Hex_Files --hex GM_VCUPLUS_ND_withPP --out GM_VCUPLUS --force
```

#### 场景 3：测试 NXP/ARM 平台的 S19 固件

将架构路由切换至 `arm`，并明确指定传入的是 `.s19` 固件：

```powershell
.\debugV2.bat --dir C:\Temp\ARM_Build --s19 ARM_FIRMWARE_V2 --out ARM_FIRMWARE_V2 --arch arm
```

### 终端输出示例

```
[INFO] 项目: VCUPLUS
[INFO] 检测到 MAP 文件: GM_VCUPLUS.map
  [MAP] Found version_id: addr=0x8011449C, size=4B
  [MAP] Found version_string: addr=0x801144A0, size=64B
       [APP] | ID=0x01C9C380 | Version="MAA.RRR.S.BB"
[1] 正在后台启动 TRACE32 TRICORE 服务端 (t32mtc.exe)...
[2] 正在建立双向 API 连接...
----> 连接成功！
[3] 正在通过物理接口自动检测目标芯片...
----> 成功识别并锁定芯片型号: TC397XP
...

[4] 开始校验并烧录固件: GM_VCUPLUS_ND_withPP.hex
----> 发现固件存在差异，准备执行物理更新...
----> [阶段 A] 正在擦写应用层代码 (PFlash)...
----> [阶段 A] PFlash 写入完成（耗时 34s）
----> [阶段 B] 编程 UCB 配置...
----> [阶段 B] UCB 编程结果: RESULT OK!!
----> 请手动断电-上电复位...

[5] 正在执行深度硬件复位并加载符号表...
[6] 放行程序，准备进行 3 分钟通用稳定性监测...
----> 程序已RUNNING，开始运行状态监测...
...
[7] 测试框架任务结束，正在断开连接...
```

---

## 设计方案

1. **参数解析与引擎启动**：
   Python 接管命令行输入，在后台静默拉起对应架构的 TRACE32 引擎，建立 RPC 连接并开启日志记录。

2. **项目识别与版本提取**：
   在启动 TRACE32 前，先扫描固件目录中的 `.map` 文件，解析版本符号地址，从 `.s19`/`.hex` 二进制中提取固件版本 ID 和字符串，在终端以彩色展示。

3. **硬件握手与驱动挂载**：
   自动识别芯片 ID，借用官方 CMM 脚本划分 Flash 扇区并注入 RAM Code（利用 `PREPAREONLY` 参数剥夺其下载权，交由 Python 接管）。

4. **固件比对与烧录复位**：
   执行物理 Flash 差异比对。若固件一致则瞬间跳过；若不同（或触发 `--force`），则执行物理擦写。写入完成后自动检测并编程 UCB，最后**强制硬件复位**确保 PC 归零。

5. **稳定性测试**：
   加载符号表并放行 CPU，进入 3 分钟核心监控：
   - **快轮询**：每秒检查 CPU 运行状态，秒抓硬件宕机/复位 (Trap)。
   - **慢采样**：PC 指针抓拍比对，多次在同一地址停留则判定为代码死锁，输出异常状态并退出。

6. **安全退出与现场清理**：
   保留错误现场或输出测试通过报告，断开 API 连接。

---

## 扩展新项目

要为新项目添加支持，编辑 `Scripts-common/project_versions.json`：

```json
{
  "你的项目名（大写，需与路径中的关键词匹配）": {
    "APP": {
      "version_id":     "0x8xxx...",     // .map 中 SW_VERSION_ID 的地址
      "version_string": "0x8xxx..."      // .map 中 SW_VERSION_STRING 的地址
    },
    "BL": {
      "version_id":     "0xAxxx...",
      "version_string": "0xAxxx..."
    }
  }
}
```

项目名通过路径关键词自动匹配，无需修改代码。

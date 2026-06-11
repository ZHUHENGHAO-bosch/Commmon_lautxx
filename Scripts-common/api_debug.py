import argparse
import subprocess
import time
import os
import sys

# Ensure local helper modules in this directory can be imported regardless of CWD
sys.path.insert(0, os.path.dirname(__file__))
from datetime import datetime
import lauterbach.trace32.rcl as t32

from t32_helpers import start_trace32, connect_dbg, wrap_dbg_with_logger, dump_area
from flash_ops import perform_flash_sequence
from stability import perform_stability_test
from firmware_version_extractor import get_version_info, format_version_summary, find_map_file

def main():
    # =========================================================================
    # 1. 解析命令行参数
    # =========================================================================
    parser = argparse.ArgumentParser(description="TRACE32 API Interactive Debugger V2 (Standalone Framework)")
    parser.add_argument("--dir", required=True, help="固件与符号表所在的文件夹绝对或相对路径")
    
    fw_group = parser.add_mutually_exclusive_group(required=True)
    fw_group.add_argument("--s19", help="指定烧录 S19 格式固件名称 (带或不带后缀均可)")
    fw_group.add_argument("--hex", help="指定烧录 HEX 格式固件名称 (带或不带后缀均可)")
    fw_group.add_argument("--srec", help="指定烧录 SREC 格式固件名称 (带或不带后缀均可)")
    
    parser.add_argument("--out", help="符号表名称 (可选，带或不带后缀均可)")
    parser.add_argument("--arch", choices=["tricore", "arm", "ppc", "rh850"], default="tricore", help="目标芯片架构")
    parser.add_argument("--force", action="store_true", help="强制执行烧录，跳过相同固件的差异检查")
    args = parser.parse_args()

    # =========================================================================
    # 2. 动态目录寻址
    # =========================================================================
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    t32_base_path = r"C:\China_Convergence\VP_Artifactorytools\trace32\2022.09.000154087\files\bin\windows64"
    exe_map = {"tricore": "t32mtc.exe", "arm": "t32marm.exe", "ppc": "t32mppc.exe", "rh850": "t32mrh850.exe"}
    trace32_exe = os.path.join(t32_base_path, exe_map[args.arch])
    
    config_file = os.path.join(base_dir, "laut-common", "config.t32").replace('\\', '/')
    program_ucbs_cmm = os.path.join(base_dir, "laut-common", "Tools", "laut-tc3xx-VCUPLUS", "ProgramUcbs.cmm").replace('\\', '/')
    ucb_config_dir = os.path.join(base_dir, "laut-common", "Tools", "laut-tc3xx-VCUPLUS", "tc3x7").replace('\\', '/')

    fw_dir = os.path.abspath(args.dir)
    
    if args.s19: fw_name = args.s19 if args.s19.lower().endswith(".s19") else args.s19 + ".s19"
    elif args.hex: fw_name = args.hex if args.hex.lower().endswith(".hex") else args.hex + ".hex"
    elif args.srec: fw_name = args.srec if args.srec.lower().endswith(".srec") else args.srec + ".srec"
    
    flash_file = os.path.join(fw_dir, fw_name).replace('\\', '/')
    out_file = None
    if args.out:
        out_name = args.out if args.out.endswith(('.out', '.elf')) else f"{args.out}.out"
        out_file = os.path.join(fw_dir, out_name).replace('\\', '/')

    # =========================================================================
    # 3. 日志环境准备与后台服务启动
    # =========================================================================
    log_dir = os.path.join(base_dir, "logdir")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    now = datetime.now()
    log_filename = f"log_{now.strftime('%Y%m%d_%H%M%S')}.log"
    api_log_file = os.path.join(log_dir, log_filename)

    # ── 在启动 TRACE32 前，先从目录中查找 MAP 文件并提取固件版本 ──
    map_path = find_map_file(fw_dir)
    if map_path:
        print(f"[INFO] 检测到 MAP 文件: {os.path.basename(map_path)}")
        try:
            ver_info = get_version_info(fw_dir, fw_name, map_path=map_path)
            if ver_info:
                ver_str = format_version_summary(ver_info)
                print(f"       \033[91m{ver_str}\033[0m")
                _prelog_version = ver_str  # saved for log header below
        except Exception:
            pass
    else:
        print(f"[INFO] 未找到 MAP 文件，跳过固件版本读取。")

    print(f"[1] 正在后台启动 TRACE32 {args.arch.upper()} 服务端 ({exe_map[args.arch]})...")
    t32_process = start_trace32(trace32_exe, config_file)

    try:
        print("[2] 正在建立双向 API 连接...")
        dbg = connect_dbg(timeout=600)
        print("----> 连接成功！")

        with open(api_log_file, "w", encoding="utf-8") as f:
            f.write(f"// ===================================================\n")
            f.write(f"// TRACE32 Python API Execution Log (Standalone Framework)\n")
            f.write(f"// Date: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"// Architecture: {args.arch.upper()}\n")
            f.write(f"// Target Firmware: {flash_file}\n")
            try:
                f.write(f"// Firmware Version: {_prelog_version}\n")
            except NameError:
                pass
            f.write(f"// ===================================================\n\n")

        dbg = wrap_dbg_with_logger(dbg, api_log_file)

        # dump_area provided by t32_helpers

        # =========================================================================
        # 4. 硬件初始化与安全状态接管 (!!! 终极破解连环死结 !!!)
        # =========================================================================
        print("[3] 正在通过物理接口自动检测目标芯片...")
        dbg.cmd("SYStem.RESet")
        
        try: dbg.cmd("SYStem.DETECT CPU")
        except: pass 
            
        detected_cpu = dbg.fnc("SYStem.CPU()")
        if not detected_cpu or detected_cpu.strip() == "":
            raise RuntimeError("自动探测芯片失败！请检查目标板是否上电，以及调试排线是否连接牢固。")
        print(f"----> 成功识别并锁定芯片型号: {detected_cpu}")
        
        # 4.1 显式声明芯片型号
        dbg.cmd(f"SYStem.CPU {detected_cpu}")

        # 4.2 Flash 驱动挂载：优先使用仓库内的 TargetAutoDetect.cmm（会做 PREPAREONLY），
        # 若不存在则退化为对 demo 脚本使用 PREPAREONLY 挂载，确保 TRACE32 注册可编程 FLASH 设备。
        if args.arch == "tricore" and detected_cpu.upper().startswith("TC"):
            family = detected_cpu[:4].lower() + "x"
            flash_script = f"~~/demo/tricore/flash/{family}.cmm"
            local_target_auto = os.path.join(base_dir, "laut-common", "Tools", "laut-tc3xx-VCUPLUS", "tc3x7", "TargetAutoDetect.cmm").replace('\\', '/')
            print(f"----> 挂载目标芯片 Flash 驱动: {family}.cmm")
            try:
                if os.path.exists(os.path.join(base_dir, "laut-common", "Tools", "laut-tc3xx-VCUPLUS", "tc3x7", "TargetAutoDetect.cmm")):
                    print("----> 优先使用仓库内的 TargetAutoDetect.cmm 进行挂载 ")
                    dbg.cmd(f'DO "{local_target_auto}" CPU={detected_cpu}')
                    time.sleep(1.0)
                    # 诊断：TargetAutoDetect 可能依赖 TRACE32 内部的 demo flash 脚本，检查并显式 PREPAREONLY
                    try:
                        demo_exists = False
                        try:
                            demo_exists = bool(dbg.fnc(f'OS.FILE("{flash_script}")'))
                        except Exception:
                            demo_exists = False
                        with open(api_log_file, "a", encoding="utf-8") as f:
                            f.write(f"// INFO :: demo flash script {flash_script} exists: {demo_exists}\n")
                        if demo_exists:
                            print(f"----> demo flash 脚本存在，显式执行 PREPAREONLY: {flash_script}")
                            dbg.cmd(f'DO "{flash_script}" CPU={detected_cpu} PREPAREONLY')
                            time.sleep(1.0)
                    except Exception as e:
                        with open(api_log_file, "a", encoding="utf-8") as f:
                            f.write(f"// WARN :: demo PREPAREONLY attempt failed: {e}\n")
                else:
                    print("----> 未发现 TargetAutoDetect.cmm，改为使用 demo 脚本并加 PREPAREONLY 挂载")
                    dbg.cmd(f'DO "{flash_script}" CPU={detected_cpu} PREPAREONLY')
                    time.sleep(1.0)
            except Exception as e:
                with open(api_log_file, "a", encoding="utf-8") as f:
                    f.write(f"// ERROR :: Flash DO failed: {e}\n")
                raise

            # （已移除冗余的 FLASH 探针命令，保持与原始 tc39x.cmm 一致）
            with open(api_log_file, "a", encoding="utf-8") as f:
                f.write("// INFO :: Skipped redundant FLASH probe commands to match original tc39x.cmm\n")

        # 4.3 硬件预配置：遵循 tc39x.cmm 的顺序进行 Down -> JTAG/DEBUG 配置 -> 根据电源状态选择是否禁用看门狗 -> Up
        try:
            dbg.cmd("SYStem.Mode.Down")
        except Exception:
            pass

        try:
            combiprobe = False
            try:
                combiprobe = bool(dbg.fnc("hardware.COMBIPROBE()"))
            except Exception:
                combiprobe = False
            if combiprobe:
                dbg.cmd("SYStem.CONFIG DEBUGPORTTYPE DAPWIDE")
            else:
                dbg.cmd("SYStem.CONFIG DEBUGPORTTYPE DAP2")
        except Exception as e:
            with open(api_log_file, "a", encoding="utf-8") as f:
                f.write(f"// WARN :: SYStem.CONFIG DEBUGPORTTYPE failed: {e}\n")

        try:
            dbg.cmd("SYStem.JtagClock 30.MHz")
        except Exception as e:
            with open(api_log_file, "a", encoding="utf-8") as f:
                f.write(f"// WARN :: SYStem.JtagClock failed: {e}\n")

        # 仅在没有外部供电时尝试禁用板载 watchdog（与 CMM 行为一致）
        try:
            has_power = False
            try:
                has_power = bool(dbg.fnc("STATE.POWER()"))
            except Exception:
                has_power = False

            if not has_power:
                print("----> 目标未上电，尝试执行看门狗解除脚本...")
                wdg_paths = [
                    "~~/demo/tricore/hardware/triboard-tc3x7/tc397xp/disable_tlf35584.cmm",
                    "~~/demo/tricore/hardware/triboard-tc3x7/tc377tp/disable_tlf35584.cmm",
                    "~~/demo/tricore/hardware/triboard-tc3x7/disable_tlf35584.cmm",
                    "~~/demo/tricore/hardware/triboard/tc39xb/disable_tlf35584.cmm",
                    "~~/demo/tricore/hardware/triboard/disable_tlf35584.cmm"
                ]
                wdg_success = False
                for wdg_script in wdg_paths:
                    try:
                        if dbg.fnc(f'OS.FILE("{wdg_script}")'):
                            dbg.cmd(f'DO "{wdg_script}"')
                            wdg_success = True
                            print(f"----> 成功执行看门狗解除脚本: {os.path.basename(wdg_script)}")
                            break
                    except Exception:
                        continue
                if not wdg_success:
                    print("----> [警告] 未找到 disable_tlf35584.cmm 或执行失败，若主板含看门狗可能引发擦写中断！")
            else:
                print("----> 目标已上电，跳过看门狗解除")
        except Exception as e:
            with open(api_log_file, "a", encoding="utf-8") as f:
                f.write(f"// WARN :: watchdog handling failed: {e}\n")

        try:
            dbg.cmd("SYStem.Mode.Up")
        except Exception:
            pass

        # 给总线赋权以便后续可能的内存访问操作
        try:
            dbg.cmd("System.MemAccess CPU")
        except Exception as e:
            with open(api_log_file, "a", encoding="utf-8") as f:
                f.write(f"// WARN :: System.MemAccess failed: {e}\n")

        # =========================================================================
        # 5. 双重隔离烧录架构
        # =========================================================================
        print(f"\n[4] 开始校验并烧录固件: {os.path.basename(flash_file)}")
        start_time = time.time()
        should_flash = False
        
        if args.force:
            print("----> [强制烧录模式] 参数已启用，跳过差异比对！")
            should_flash = True
        else:
            dbg.cmd(f'Data.LOAD.auto "{flash_file}" /DIFF /SingleLineAdjacent')
            time.sleep(0.2)
            if dbg.fnc("FOUND()"):
                print("----> 发现固件存在差异，准备执行物理更新...")
                should_flash = True
            else:
                print("----> 目标板已包含相同固件与配置，跳过烧录以保护闪存寿命。")
        
        if should_flash:
            pflash_ok, ucb_ok = perform_flash_sequence(dbg, flash_file, program_ucbs_cmm, ucb_config_dir, api_log_file, start_time, force=args.force)
            # 手动断电-上电复位的确认逻辑已移至 flash_ops.perform_flash_sequence

        # =========================================================================
        # 6. 正确的硬件复位与符号表加载
        # =========================================================================
        time.sleep(2)
        print("\n[5] 正在执行深度硬件复位并加载符号表...")
        dbg.cmd("SYStem.Option.RESETMODE PORST")
        dbg.cmd("SYStem.RESetTarget")
        dbg.cmd("SYStem.Up")
        try:
            dump_area(dbg, api_log_file, 'after_reset')
        except Exception:
            pass

        if out_file and os.path.exists(out_file):
            print(f"----> 已找到符号表文件，正在加载 (不包含代码): {os.path.basename(out_file)}")
            dbg.cmd(f'Data.LOAD.Elf "{out_file}" /NoCODE')
        else:
            print("----> [提示] 未传入或未找到符号表，监控报警时将无法反查 C 语言函数名。")
        
        # Delegate stability test to stability.perform_stability_test
        perform_stability_test(dbg, api_log_file, out_file)
            
    except Exception as e:
        print(f"\n[!] 交互过程中发生异常: {e}")
        with open(api_log_file, "a", encoding="utf-8") as f:
            f.write(f"\n// ERROR :: 脚本异常终止: {e}\n")
            
    finally:
        print("\n[7] 测试框架任务结束，正在断开连接...")
        # try: dbg.cmd("QUIT")
        # except: pass
            
        # if t32_process.poll() is None:
        #     t32_process.terminate()
        #     t32_process.wait()
            
        # print("环境清理完毕。")

if __name__ == "__main__":
    main()
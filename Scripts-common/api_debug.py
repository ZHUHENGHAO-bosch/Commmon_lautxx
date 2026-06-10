import argparse
import subprocess
import time
import os
import sys
import lauterbach.trace32.rcl as t32
from datetime import datetime

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

    print(f"[1] 正在后台启动 TRACE32 {args.arch.upper()} 服务端 ({exe_map[args.arch]})...")
    t32_process = subprocess.Popen([trace32_exe, "-b", "-c", config_file])
    time.sleep(2.0)

    try:
        print("[2] 正在建立双向 API 连接...")
        try:
            # 尝试使用较长超时建立连接（若 t32.rcl 支持 timeout 参数）
            dbg = t32.connect(node="localhost", port=20000, timeout=600)
        except TypeError:
            dbg = t32.connect(node="localhost", port=20000)
        print("----> 连接成功！")
        
        with open(api_log_file, "w", encoding="utf-8") as f:
            f.write(f"// ===================================================\n")
            f.write(f"// TRACE32 Python API Execution Log (Standalone Framework)\n")
            f.write(f"// Date: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"// Architecture: {args.arch.upper()}\n")
            f.write(f"// Target Firmware: {flash_file}\n")
            f.write(f"// ===================================================\n\n")

        original_cmd = dbg.cmd
        def logged_cmd(cmd_str):
            with open(api_log_file, "a", encoding="utf-8") as f:
                f.write(f"CMD :: {cmd_str}\n")
            # 返回原始调用结果，保留 RCL 的同步/异常语义
            return original_cmd(cmd_str)
        dbg.cmd = logged_cmd

        def dump_area(tag):
            try:
                out = original_cmd('AREA')
            except Exception:
                try:
                    out = original_cmd('AREA.List')
                except Exception as e:
                    out = f'ERROR: cannot get AREA output: {e}'
            if out is None:
                out = ''
            with open(api_log_file, 'a', encoding='utf-8') as f:
                f.write(f"// AREA DUMP [{tag}] start\n")
                f.write(out + '\n')
                f.write(f"// AREA DUMP [{tag}] end\n")

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
                    print("----> 优先使用仓库内的 TargetAutoDetect.cmm 进行挂载 (含 PREPAREONLY)")
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
                print("----> 目标已上电，跳过看门狗解除（与 CMM 行为一致）")
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
            # 【阶段 A】：常规 PFlash 烧录
            print("----> [阶段 A] 正在擦写应用层代码 (PFlash)...")
            pflash_ok = None
            ucb_ok = None
            
            # 按 tc39x.cmm 的顺序：确保目标处于 Up，再执行 FLASH.ReProgram ALL 然后写入
            try:
                dbg.cmd("SYStem.Mode.Up")
            except Exception:
                pass
            time.sleep(0.2)
            dbg.cmd("FLASH.ReProgram ALL")
            time.sleep(0.5)
            
            # 看门狗被真正按死后，执行写入。为防止 target 在中间掉线，增加对 'target system down' 的重试恢复。
            

            try:
                dbg.cmd(f'Data.LOAD.auto "{flash_file}"')
                pflash_ok = True
            except Exception as e:
                pflash_ok = False
                err_str = str(e)
                with open(api_log_file, "a", encoding="utf-8") as f:
                    f.write(f"// ERROR :: Data.LOAD.auto during PFlash write failed: {err_str}\n")
                print(f"----> 警告: Data.LOAD.auto 写入阶段失败: {err_str}")
                # 如果是 target down，尝试 bring up 后重试一次
                if 'target system down' in err_str.lower() or 'core running' in err_str.lower():
                    try:
                        print("----> 尝试恢复目标通信: SYStem.Up 然后重试写入...")
                        dbg.cmd("SYStem.Up")
                        time.sleep(0.5)
                        dbg.cmd(f'Data.LOAD.auto "{flash_file}"')
                        pflash_ok = True
                    except Exception as e2:
                        pflash_ok = False
                        with open(api_log_file, "a", encoding="utf-8") as f:
                            f.write(f"// ERROR :: Retry Data.LOAD.auto failed: {e2}\n")
                        raise
                else:
                    raise

            dbg.cmd("FLASH.ReProgram OFF")
            time.sleep(0.2)
            try:
                dump_area('after_pflash')
            except Exception:
                pass
            # PFlash 写入结果独立显示与记录
            with open(api_log_file, 'a', encoding='utf-8') as f:
                if pflash_ok:
                    print("----> [阶段 A] PFlash 刷写成功。")
                    f.write("// RESULT :: PFlash OK\n")
                else:
                    print("----> [阶段 A] PFlash 刷写失败！")
                    f.write("// RESULT :: PFlash NOK\n")
            
            # 【阶段 B】UCB 安全差分刷写与防砖回滚
            print("----> [阶段 B] 正在调用专用框架比对并刷写 UCB 安全区域...")
            try:
                # Call ProgramUcbs.cmm with parameters as in TargetDownload.cmm:
                #   DO "ProgramUcbs.cmm" "1" "<fileToFlash>" "<pathToUcbConfig>"
                ucb_ok = False
                dbg.cmd(f'DO "{program_ucbs_cmm}" "1" "{flash_file}" "{ucb_config_dir}"')
                ucb_ok = True
                time.sleep(0.5)
                try:
                    dump_area('after_ucb')
                except Exception:
                    pass
            except Exception as e:
                ucb_ok = False
                with open(api_log_file, "a", encoding="utf-8") as f:
                    f.write(f"// ERROR :: ProgramUcbs invocation failed: {e}\n")
                raise

            # UCB 写入结果独立显示与记录
            with open(api_log_file, 'a', encoding='utf-8') as f:
                if ucb_ok is True:
                    print("----> [阶段 B] UCB 刷写成功。")
                    f.write("// RESULT :: UCB OK\n")
                elif ucb_ok is False:
                    print("----> [阶段 B] UCB 刷写失败！")
                    f.write("// RESULT :: UCB NOK\n")
                else:
                    print("----> [阶段 B] UCB 未执行（跳过或未配置）。")
                    f.write("// RESULT :: UCB N/A\n")
            
            print(f"----> 物理烧录全阶段完成！总耗时: {time.time() - start_time:.2f} 秒")

        # =========================================================================
        # 6. 正确的硬件复位与符号表加载
        # =========================================================================
        time.sleep(2)
        print("\n[5] 正在执行深度硬件复位并加载符号表...")
        dbg.cmd("SYStem.Option.RESETMODE PORST")
        dbg.cmd("SYStem.RESetTarget")
        dbg.cmd("SYStem.Up")
        try:
            dump_area('after_reset')
        except Exception:
            pass

        if out_file and os.path.exists(out_file):
            print(f"----> 已找到符号表文件，正在加载 (不包含代码): {os.path.basename(out_file)}")
            dbg.cmd(f'Data.LOAD.Elf "{out_file}" /NoCODE')
        else:
            print("----> [提示] 未传入或未找到符号表，监控报警时将无法反查 C 语言函数名。")
        
        # =========================================================================
        # 7. 鲁棒性实时监控 (防复位、防异常崩溃)
        # =========================================================================
        print("\n[6] 放行程序，准备进行 3 分钟通用稳定性监控...")
        dbg.cmd("SYStem.Option DUALPORT ON")
        time.sleep(0.3)
        dbg.cmd("Go")
        time.sleep(2) 
        
        # 记录监控开始信息到日志
        with open(api_log_file, "a", encoding="utf-8") as f:
            f.write(f"// INFO :: Stability monitoring started, duration={180}s\n")

        if dbg.fnc("STATE.RUN()"):
            print("----> 程序已启动，开始纯无感运行状态监控...")
            with open(api_log_file, "a", encoding="utf-8") as f:
                f.write("// STABILITY :: initial check -> RUNNING\n")
        else:
            print("----> [致命警告] 程序刚发送 Go 就停机了，请检查是否存在 HardFault 或地址越界。")
            with open(api_log_file, "a", encoding="utf-8") as f:
                f.write("// STABILITY :: initial check -> NOT RUNNING\n")

        test_duration = 180
        error_occurred = False

        for i in range(1, test_duration + 1):
            time.sleep(1)
            running = False
            try:
                running = bool(dbg.fnc("STATE.RUN()"))
            except Exception:
                running = False

            if not running:
                try:
                    pc_val = hex(dbg.fnc("Register(PC)"))
                    sym_name = dbg.fnc("sYmbol.Name(Register(PC))")
                    sym_str = f" (位于函数: {sym_name})" if sym_name and sym_name != "0." else ""
                except Exception:
                    pc_val = "未知"
                    sym_str = ""
                print(f"\n❌ [测试失败] 第 {i} 秒检测到意外停机或频繁复位！")
                print(f"----> 案发现场 PC 指针: {pc_val}{sym_str}")
                with open(api_log_file, "a", encoding="utf-8") as f:
                    f.write(f"// STABILITY :: FAIL second={i} RUN=False PC={pc_val}{sym_str}\n")
                error_occurred = True
                break

            # 每次判定同时写日志并在终端打印
            status_line = f"STABILITY: OK {i}/{test_duration}"
            print(status_line)
            with open(api_log_file, "a", encoding="utf-8") as f:
                f.write(f"// STABILITY :: OK second={i} RUN=True\n")

            if i % 10 == 0:
                print(f"-> 内核全速稳定运行中... {i}/{test_duration} 秒")
                with open(api_log_file, "a", encoding="utf-8") as f:
                    f.write(f"// INFO :: heartbeat {i}/{test_duration}\n")

        if not error_occurred:
            print("\n✅ [测试通过] 恭喜！目标板完美通过 3 分钟无复位稳定测试！")
            
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
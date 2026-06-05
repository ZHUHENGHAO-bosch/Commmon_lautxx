import argparse
import subprocess
import time
import os
import sys
import lauterbach.trace32.rcl as t32
from datetime import datetime

def main():
    # ================= 1. 解析命令行参数 =================
    parser = argparse.ArgumentParser(description="TRACE32 API Interactive Debugger V2")
    parser.add_argument("--dir", required=True, help="固件与符号表所在的文件夹路径")
    
    # 固件格式互斥参数组（必须且只能选择其中一种）
    fw_group = parser.add_mutually_exclusive_group(required=True)
    fw_group.add_argument("--s19", help="指定烧录 S19 格式固件名称 (不带后缀)")
    fw_group.add_argument("--hex", help="指定烧录 HEX 格式固件名称 (不带后缀)")
    fw_group.add_argument("--srec", help="指定烧录 SREC 格式固件名称 (不带后缀)")
    
    parser.add_argument("--out", help="符号表名称 (可选，不带后缀，例如 GM_VCUPLUS)")
    parser.add_argument("--config", help="自定义 config.t32 路径 (可选)")
    
    # 架构选择参数，决定启动哪个 TRACE32 内核
    parser.add_argument("--arch", choices=["tricore", "arm", "ppc", "rh850"], default="tricore", help="目标芯片架构 (默认: tricore)")
    
    # 强制烧录开关参数
    parser.add_argument("--force", action="store_true", help="强制执行烧录，跳过相同固件的检查")
    args = parser.parse_args()

    # ================= 2. 动态路由与路径拼接 =================
    
    exe_map = {
        "tricore": "t32mtc.exe",
        "arm": "t32marm.exe",
        "ppc": "t32mppc.exe",
        "rh850": "t32mrh850.exe"
    }
    
    t32_base_path = r"C:\China_Convergence\VP_Artifactorytools\trace32\2022.09.000154087\files\bin\windows64"
    trace32_exe = os.path.join(t32_base_path, exe_map[args.arch])
    
    fw_dir = os.path.abspath(args.dir)
    
    # ================= 严格按照传入的参数后缀拼接文件名 =================
    if args.s19:
        fw_base = args.s19
        fw_ext = ".s19"
    elif args.hex:
        fw_base = args.hex
        fw_ext = ".hex"
    elif args.srec:
        fw_base = args.srec
        fw_ext = ".srec"

    # 如果用户输入时自己带了后缀就不加，没带就严格补上对应的后缀
    fw_name = fw_base if fw_base.lower().endswith(fw_ext) else fw_base + fw_ext
    flash_file = os.path.join(fw_dir, fw_name)
    # ======================================================================

    out_file = None
    if args.out:
        out_name = args.out if args.out.endswith(('.out', '.elf')) else f"{args.out}.out"
        out_file = os.path.join(fw_dir, out_name)

    if args.config:
        config_file = os.path.abspath(args.config)
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_file = os.path.join(base_dir, "laut-common", "config.t32")

    # ================= 3. 日志路径准备 =================
    script_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(script_parent_dir, "logdir")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    now = datetime.now()
    log_filename = f"log_{now.year}_{now.month}_{now.day}_{now.hour}_{now.minute}_{now.second}.log"
    api_log_file = os.path.join(log_dir, log_filename)

    # ================= 4. 启动后台服务 =================
    print(f"[1] 正在后台启动 TRACE32 {args.arch.upper()} 服务端 ({exe_map[args.arch]})...")
    t32_process = subprocess.Popen([trace32_exe, "-b", "-c", config_file])
    time.sleep(1.5) 

    # ================= 5. 建立强交互连接 =================
    print("[2] 正在建立双向 API 连接...")
    try:
        dbg = t32.connect(node="localhost", port=20000)
        print("----> 连接成功！")
    except Exception as e:
        print(f"连接失败: {e}")
        t32_process.kill()
        sys.exit(1)

    # ================= 6. Log日志读取  =================
    with open(api_log_file, "w", encoding="utf-8") as f:
        f.write(f"// TRACE32 Python API Execution Log\n")
        f.write(f"// Date: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"// Architecture: {args.arch.upper()}\n")
        f.write(f"// Target Firmware: {flash_file}\n")
        f.write(f"// ===================================================\n\n")

    original_cmd = dbg.cmd
    original_fnc = dbg.fnc

    def logged_cmd(cmd_str):
        with open(api_log_file, "a", encoding="utf-8") as f:
            f.write(f"// CMD :: {cmd_str}\n")
        original_cmd(cmd_str)

    def logged_fnc(fnc_str):
        result = original_fnc(fnc_str)
        with open(api_log_file, "a", encoding="utf-8") as f:
            f.write(f"// READ:: {fnc_str}  --->  Result: {result}\n")
        return result

    dbg.cmd = logged_cmd
    dbg.fnc = logged_fnc

    # ================= 7. 核心业务逻辑 =================
    try:
        print("[3] 正在通过物理接口自动检测目标芯片...")
        dbg.cmd("SYStem.RESet")
        
        try:
            dbg.cmd("SYStem.DETECT CPU")
        except:
            pass 
            
        detected_cpu = dbg.fnc("SYStem.CPU()")
        
        if detected_cpu and detected_cpu.strip() != "":
            print(f"----> 成功识别并锁定芯片型号: {detected_cpu}")
        else:
            raise RuntimeError("自动探测芯片失败！请检查目标板是否上电，以及调试排线是否连接牢固。")
            
        dbg.cmd("SYStem.Up")

        # ================= 动态初始化 Flash 驱动 =================
        if args.arch == "tricore" and detected_cpu.upper().startswith("TC"):
            family = detected_cpu[:4] + "x"
            flash_script = f"~~/demo/tricore/flash/{family}.cmm"
            
            print(f"----> 正在挂载目标芯片 Flash 驱动: {family}.cmm")
            dbg.cmd(f"DO {flash_script} CPU={detected_cpu} PREPAREONLY")
            time.sleep(1.0)
            print("----> Flash 驱动挂载完毕！")

        print(f"[4] 开始校验固件: {os.path.basename(flash_file)}")
        start_time = time.time()
        
        # ================= 智能判断是否需要烧录 =================
        should_flash = False
        
        if args.force:
            print("----> [强制烧录模式] 参数已启用，跳过差异比对！")
            should_flash = True
        else:
            dbg.cmd(f"Data.LOAD.auto {flash_file} /DIFF /SingleLineAdjacent")
            if dbg.fnc("FOUND()"):
                print("----> 发现固件差异，准备更新...")
                should_flash = True
            else:
                print("----> 目标板已包含相同固件，跳过烧录。")
        
        # ================= 执行烧录 =================
        if should_flash:
            print("----> 正在执行擦除与烧录 (请勿断开电源)...")
            dbg.cmd("FLASH.ReProgram ALL")
            dbg.cmd(f"Data.LOAD.auto {flash_file}")
            dbg.cmd("FLASH.ReProgram OFF")
            print(f"----> 烧录完成，耗时: {time.time() - start_time:.2f} 秒")
            
            # 烧录完成后复位，让 PC 指针回到起点
            dbg.cmd("SYStem.Down")
            dbg.cmd("SYStem.Up")
            
        # ================= 7.5 进阶：符号表加载与通用稳定性监控 =================
        if out_file and os.path.exists(out_file):
            print(f"\n[5] 已提供并找到符号表文件，正在加载: {os.path.basename(out_file)}")
            dbg.cmd(f"Data.LOAD.Elf {out_file} /NoCODE")
        elif out_file and not os.path.exists(out_file):
            print(f"\n[5] [!] 警告: 传入了 --out 参数，但找不到对应的符号表: {os.path.basename(out_file)}")
            print("    已跳过符号表加载，但将继续执行底层的稳定性监控。")
        else:
            print("\n[5] [!] 提示: 未传入 --out 符号表参数，已跳过符号表加载。")
            print("    监控报错时将仅显示物理地址，无法反查 C 语言函数名。")

        print("\n[6] 放行程序，准备进行 3 分钟通用稳定性监控...")
        
        dbg.cmd("Go")
        time.sleep(2) # 给芯片 2 秒钟越过 Boot 阶段
        
        if dbg.fnc("STATE.RUN()"):
            print("----> 程序已启动，开始实时监控 (1秒状态快检 + 10秒PC慢检)...")
        else:
            print("----> [警告] 程序刚发送 Go 就停机了，请检查是否存在启动硬错误。")

        test_duration = 180
        error_occurred = False
        pc_history = [] 

        for i in range(1, test_duration + 1):
            time.sleep(1)
            
            # 维度 1：快轮询
            if not dbg.fnc("STATE.RUN()"):
                pc_val = hex(dbg.fnc("Register(PC)"))
                sym_name = dbg.fnc("sYmbol.Name(Register(PC))")
                sym_str = f" (位于函数: {sym_name})" if sym_name and sym_name != "0." else ""
                
                print(f"\n❌ [测试失败] 第 {i} 秒检测到意外停机/复位！")
                print(f"----> 案发现场 PC 指针: {pc_val}{sym_str}")
                error_occurred = True
                break
                
            # 维度 2：慢采样
            if i % 10 == 0:
                dbg.cmd("Break")                           # 瞬间刹车
                time.sleep(0.1)                            # 给底层硬件 100ms 缓冲时间
                
                current_pc = dbg.fnc("Register(PC)")       # 等它彻底停稳，再去读取 PC
                
                pc_history.append(current_pc)
                if len(pc_history) > 3:
                    pc_history.pop(0) 
                    
                # 连续3次PC相同，触发死锁判定
                if len(pc_history) == 3 and len(set(pc_history)) == 1:
                    pc_val = hex(current_pc)
                    sym_name = dbg.fnc("sYmbol.Name(Register(PC))") 
                    sym_str = f" (位于函数: {sym_name})" if sym_name and sym_name != "0." else ""
                    
                    print(f"\n❌ [测试失败] 第 {i} 秒检测到系统死锁！")
                    print(f"----> CPU 卡死在死循环中。当前 PC: {pc_val}{sym_str}")
                    error_occurred = True
                    break
                else:
                    dbg.cmd("Go") # 没死锁，放行让它继续跑

                print(f"-> 稳定运行中... {i}/{test_duration} 秒")

        if not error_occurred:
            print("\n✅ [测试通过] 恭喜！目标板稳定运行 3 分钟无复位与死锁现象！")
            
    except Exception as e:
        print(f"交互过程中发生异常: {e}")
        with open(api_log_file, "a", encoding="utf-8") as f:
            f.write(f"\n// ERROR :: 脚本异常终止: {e}\n")
        
    finally:
        # ================= 8. 安全清理进程 =================
        print("\n[7] 正在断开连接并退出 TRACE32...")
        try:
            print(f"----> API 底层通讯日志已导出至: {api_log_file}")
            dbg.cmd("QUIT")
        except:
            t32_process.kill()
        print("任务彻底结束。")

if __name__ == "__main__":
    main()
import time


def perform_stability_test(dbg, api_log_file, out_file=None):
    print("\n[6] 放行程序，准备进行 3 分钟通用稳定性监控...")
    dbg.cmd("SYStem.Option DUALPORT ON")
    time.sleep(0.3)
    dbg.cmd("Go")
    time.sleep(2)

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

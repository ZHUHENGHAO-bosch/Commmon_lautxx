import time
import sys
from datetime import datetime
from t32_helpers import dump_area, read_area_content, elapsed_since

# Module-level sentinel to avoid prompting more than once per run
manual_power_cycle_confirmed = False


def perform_flash_sequence(dbg, flash_file, program_ucbs_cmm, ucb_config_dir, api_log_file, start_time, force=False):
    pflash_ok = None
    ucb_ok = None

    try:
        try:
            dbg.cmd("SYStem.Mode.Up")
        except Exception:
            pass
        time.sleep(0.2)
        dbg.cmd("FLASH.ReProgram ALL")
        time.sleep(0.5)

        try:
            with open(api_log_file, 'a', encoding='utf-8') as f:
                f.write(f"// INFO :: Starting PFlash write, force={force}, time={datetime.now().isoformat()}\n")
            print(f"----> [阶段 A] 正在擦写应用层代码 (PFlash)...")
            t0 = time.time()
            dbg.cmd(f'Data.LOAD.auto "{flash_file}"')
            print(f"----> [阶段 A] PFlash 写入完成（耗时 {elapsed_since(t0)}）")
            pflash_ok = True
            with open(api_log_file, 'a', encoding='utf-8') as f:
                f.write(f"// INFO :: Finished PFlash write, time={datetime.now().isoformat()}\n")
        except Exception as e:
            pflash_ok = False
            err_str = str(e)
            with open(api_log_file, "a", encoding="utf-8") as f:
                f.write(f"// ERROR :: Data.LOAD.auto during PFlash write failed: {err_str}\n")
            print(f"----> 警告: Data.LOAD.auto 写入阶段失败: {err_str}")
            if 'target system down' in err_str.lower() or 'core running' in err_str.lower():
                try:
                    print("----> 尝试恢复目标通信: SYStem.Up 然后重试写入...")
                    dbg.cmd("SYStem.Up")
                    time.sleep(0.5)
                    print(f"----> 重试擦写...")
                    t0 = time.time()
                    dbg.cmd(f'Data.LOAD.auto "{flash_file}"')
                    print(f"----> 重试完成（耗时 {elapsed_since(t0)}）")
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
            dump_area(dbg, api_log_file, 'after_pflash')
        except Exception:
            pass

        with open(api_log_file, 'a', encoding='utf-8') as f:
            if pflash_ok:
                print("----> [阶段 A] PFlash 刷写成功。")
                f.write("// RESULT :: PFlash OK\n")
            else:
                print("----> [阶段 A] PFlash 刷写失败！")
                f.write("// RESULT :: PFlash NOK\n")

        # UCB
        try:
            ucb_ok = False
            dbg.cmd(f'DO "{program_ucbs_cmm}" "1" "{flash_file}" "{ucb_config_dir}"')
            time.sleep(0.5)

            # Check actual UCB result from AREA window output.
            # The CMM script prints "RESULT OK!!" / "RESULT NOK!!" / or
            # silently skips when no UCB data exists in the firmware file.
            area_text = read_area_content(dbg)
            if "RESULT OK!!" in area_text:
                ucb_ok = True
            elif "RESULT NOK!!" in area_text:
                ucb_ok = False
            else:
                # No UCB data found in the firmware file (normal when flashing
                # APP or BL hex — only BM contains BMHD/UCB data).
                ucb_ok = None  # N/A — not an error, just nothing to do

            try:
                dump_area(dbg, api_log_file, 'after_ucb')
            except Exception:
                pass
        except Exception as e:
            ucb_ok = False
            with open(api_log_file, "a", encoding="utf-8") as f:
                f.write(f"// ERROR :: ProgramUcbs invocation failed: {e}\n")
            raise

        with open(api_log_file, 'a', encoding='utf-8') as f:
            if ucb_ok is True:
                print("----> [阶段 B] UCB 刷写成功。")
                f.write("// RESULT :: UCB OK\n")
            elif ucb_ok is False:
                print("----> [阶段 B] UCB 刷写失败！")
                f.write("// RESULT :: UCB NOK\n")
            else:
                print("----> [阶段 B] UCB 无需更新（当前固件不包含 UCB 数据）。")
                f.write("// RESULT :: UCB N/A (no UCB data in firmware)\n")

        print(f"----> 物理烧录全阶段完成！总耗时: {time.time() - start_time:.2f} 秒")

        # Manual power-cycle prompt if pflash_ok (only once per process)
        global manual_power_cycle_confirmed
        try:
            if pflash_ok and not manual_power_cycle_confirmed:
                prompt_msg = ("\n[!] 已检测到物理烧录（固件已写入）。请现在对目标板进行断电-上电复位（手动电源循环），"
                              "完成后在终端输入 'Y' 继续: ")
                while True:
                    try:
                        resp = input(prompt_msg).strip().lower()
                    except EOFError:
                        with open(api_log_file, "a", encoding="utf-8") as f:
                            f.write(f"// ERROR :: EOF while waiting manual power-cycle confirmation at {datetime.now().isoformat()}\n")
                        raise RuntimeError("Non-interactive environment: cannot get manual confirmation for power-cycle")

                    with open(api_log_file, "a", encoding="utf-8") as f:
                        f.write(f"// INFO :: Manual power-cycle input at {datetime.now().isoformat()} -> {resp}\n")

                    if resp == 'y':
                        print("----> 用户确认已完成断电-上电复位，继续后续复位/加载与稳定性测试。")
                        with open(api_log_file, "a", encoding="utf-8") as f:
                            f.write("// INFO :: User confirmed manual power-cycle -> continue\n")
                        manual_power_cycle_confirmed = True
                        break
                    else:
                        print("----> 未收到 'Y' 确认，若已完成复位请输入 'Y' 继续。")
            elif pflash_ok and manual_power_cycle_confirmed:
                with open(api_log_file, "a", encoding="utf-8") as f:
                    f.write(f"// INFO :: Skipped manual power-cycle prompt because already confirmed earlier in this run at {datetime.now().isoformat()}\n")
        except Exception:
            with open(api_log_file, "a", encoding="utf-8") as f:
                f.write(f"// ERROR :: Exception while awaiting manual power-cycle confirmation: {sys.exc_info()[0]}\n")
            raise

        return pflash_ok, ucb_ok

    except Exception:
        raise

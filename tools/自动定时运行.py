import datetime
import time

import pyautogui

# 配置参数
TARGET_POSITION = (100, 200)  # 替换为你的目标坐标 (x, y)
INPUT_TEXT = """
You are a Python expert with 50 years of experience. Your task is as follows:

Run install_unix.sh.
If the test cases pass with a 100% success rate, commit the current code to Git, and then optimize the code to improve the overall performance of the project.
If the test cases do not pass 100%, continue fixing bugs in the source code until all test cases pass.
When fixing bugs, do not modify the expected results or logic of the test cases, and do not use new metaclasses or metaprogramming techniques.
"""
INTERVAL_MINUTES = 10  # 执行间隔（分钟）
MAX_ATTEMPTS = 1000  # 最大执行次数（防止无限循环）


def get_mouse_position():
    """获取当前鼠标位置（用于确定目标坐标）"""
    print("5秒内将鼠标移动到目标位置...")
    time.sleep(5)
    return pyautogui.position()


def input_and_enter():
    """在目标位置输入文本并按下回车键"""
    try:
        # 移动鼠标到目标位置并点击（确保输入焦点）
        pyautogui.moveTo(TARGET_POSITION[0], TARGET_POSITION[1], duration=0.5)
        pyautogui.click()

        # 将文本分割成行，逐行输入（避免\n被解释为Enter）
        for line in INPUT_TEXT.split("\n"):
            pyautogui.write(line, interval=0.001)
            # 模拟手动换行：Alt+Enter 或 Shift+Enter（根据应用程序而定）
            pyautogui.hotkey("shift", "enter")  # 尝试这个
            # 如果上面无效，尝试这个：pyautogui.hotkey('alt', 'enter')
            time.sleep(0.1)  # 行间短暂延迟

        # 最后按下回车键提交
        pyautogui.press("enter")
        return True
    except Exception as e:
        print(f"操作失败: {str(e)}")
        return False


if __name__ == "__main__":
    # 第一步：获取目标坐标（取消注释以下两行来获取坐标）

    attempt = 0
    while attempt < MAX_ATTEMPTS:
        TARGET_POSITION = get_mouse_position()
        print(f"目标坐标已设置为: {TARGET_POSITION}")
        print("自动输入程序已启动 (Ctrl+C 终止)")
        print(f"配置: 每 {INTERVAL_MINUTES} 分钟在 {TARGET_POSITION} 输入多行文本")

        try:
            # 显示下次执行时间
            next_time = datetime.datetime.now() + datetime.timedelta(minutes=INTERVAL_MINUTES)
            print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] 开始执行...")
            print(f"下次执行: {next_time.strftime('%H:%M:%S')}")

            # 执行输入操作
            if input_and_enter():
                print("✅ 输入成功!")
            else:
                print("⚠️ 输入失败，将重试")

            # 等待间隔时间（5分钟）
            time.sleep(INTERVAL_MINUTES * 60)
            attempt += 1

        except KeyboardInterrupt:
            print("\n程序已被用户终止")
            break
        except Exception as e:
            print(f"发生未预期错误: {str(e)}")
            time.sleep(60)  # 出错后等待1分钟再重试

    print("程序执行完成")

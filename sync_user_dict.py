import os
import shutil
import sys
from pathlib import Path


def find_spellchecker_dictionary(start_path):
    """
    在指定目录及其子目录中查找名为 'spellchecker-dictionary.xml' 的文件，
    并排除 .idea 文件夹及其子目录。
    :param start_path: 搜索的起始目录。
    :return: 找到的文件路径列表。
    """
    matches = []
    for root, dirs, files in os.walk(start_path):
        # 排除 .idea 文件夹
        dirs[:] = [d for d in dirs if d != ".idea"]
        for file in files:
            if file == "spellchecker-dictionary.xml":
                matches.append(Path(root) / file)
    return matches


def copy_to_idea_folder(source_files):
    """
    将找到的文件复制到当前目录下的 .idea 文件夹中。
    :param source_files: 要复制的文件列表。
    """
    current_dir = Path.cwd()
    idea_dir = current_dir / ".idea"

    # 确保 .idea 文件夹存在
    idea_dir.mkdir(exist_ok=True)

    for source_file in source_files:
        destination = idea_dir / source_file.name
        shutil.copy(source_file, destination)
        print(f"已复制: {source_file} 到 {destination}")


def find_non_idea_folders_with_file(start_path, filename="spellchecker-dictionary.xml"):
    """
    查找包含指定文件的文件夹，并排除名称为 .idea 的文件夹。
    :param start_path: 搜索的起始路径。
    :param filename: 要查找的文件名，默认是 'spellchecker-dictionary.xml'。
    :return: 找到的文件夹路径列表。
    """
    matches = []
    for root, dirs, files in os.walk(start_path):
        # 排除 .idea 文件夹
        dirs[:] = [d for d in dirs if d != ".idea"]
        if filename in files:
            matches.append(Path(root))
    return matches


def install_from_idea():
    """
    自动查找目标文件夹，并从当前目录下的 .idea 文件夹中安装 spellchecker-dictionary.xml。
    """
    current_dir = Path.cwd()
    idea_dir = current_dir / ".idea"
    source_file = idea_dir / "spellchecker-dictionary.xml"

    # 检查 .idea 文件夹是否存在
    if not idea_dir.exists():
        print(".idea 文件夹不存在！请先执行复制操作。")
        return

    # 检查 spellchecker-dictionary.xml 是否存在
    if not source_file.exists():
        print("在 .idea 文件夹中未找到 'spellchecker-dictionary.xml' 文件！")
        return

    # 搜索目标文件夹
    print("正在搜索目标文件夹...")
    target_folders = find_non_idea_folders_with_file(Path.home())

    if not target_folders:
        print("未找到包含 'spellchecker-dictionary.xml' 且不在 '.idea' 中的文件夹！")
        print("请到pycharm->设置->自然语言->拼写->设置应用程序级字典，然后重试")
        return

    print(f"找到以下目标文件夹：\n{target_folders}\n")
    for folder in target_folders:
        destination = folder / source_file.name
        shutil.copy(source_file, destination)
        print(f"已将 {source_file} 安装到 {destination}")


def run_copy():
    """
    执行默认的复制操作，将文件复制到 .idea 文件夹中。
    """
    # 从用户主目录开始搜索
    home_dir = Path.home()
    print("正在搜索 'spellchecker-dictionary.xml' 文件，请稍候...")

    # 搜索文件
    found_files = find_spellchecker_dictionary(home_dir)

    if not found_files:
        print("未找到 'spellchecker-dictionary.xml' 文件！")
    else:
        print(f"找到以下文件：\n{found_files}\n")
        print("正在将文件复制到当前目录的 .idea 文件夹中...")
        copy_to_idea_folder(found_files)
        print("复制完成！")


def main():
    """
    主函数，根据传入参数决定执行复制还是安装操作。
    """
    args = sys.argv[1:]  # 获取命令行参数

    if not args or args[0] == "copy":
        # 默认执行 copy 操作
        run_copy()
    elif args[0] == "install":
        # 执行 install 操作
        install_from_idea()
    else:
        print("未知参数！支持的操作：")
        print("  - 默认: copy")
        print("  - install")


if __name__ == "__main__":
    main()




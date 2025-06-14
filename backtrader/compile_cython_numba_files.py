import os
import warnings

warnings.filterwarnings("ignore")
import sys

for root, dirs, files in os.walk("./utils/"):
    if sys.platform == "win32":
        pass
    elif sys.platform == "linux":
        if "my_corr" in root:
            continue
    elif sys.platform == "darwin":
        pass
    compile_cython = False
    compile_numba = False
    for file in files:
        file_path = os.path.join(root, file)
        if file.endswith(".pyx"):
            if not compile_cython:
                os.system(
                    "cd {root} && python -W ignore setup.py build_ext --inplace".format(root=root)
                )
                compile_cython = True
                print(f"{file_path} compile success")
        if file.endswith("py") and "numba" in file:
            if not compile_numba:
                os.system("cd {root} && python -W ignore {file}".format(root=root, file=file))
                compile_numba = True
                print(f"{file_path} compile success")

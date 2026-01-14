# 安装指南

本文将指导你完成 Backtrader 的安装过程。

## 系统要求

- Python 3.11 或更高版本
- Git（用于克隆代码库）
- C++ 编译器（用于编译 Cython 代码）

## 安装步骤

### 1. 安装 Python

推荐使用 Anaconda 安装 Python，以下是各系统的 Anaconda 安装包下载链接：

- Windows: [Anaconda3-2023.09-0-Windows-x86_64.exe](https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-Windows-x86_64.exe)
- Mac M系列: [Anaconda3-2023.09-0-MacOSX-arm64.sh](https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-MacOSX-arm64.sh)
- Ubuntu: [Anaconda3-2023.09-0-Linux-x86_64.sh](https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-Linux-x86_64.sh)

### 2. 克隆项目

```bash
git clone https://gitee.com/yunjinqi/backtrader.git
cd backtrader
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 编译和安装

#### Mac/Linux 用户

```bash
cd ./backtrader && python -W ignore compile_cython_numba_files.py && cd .. && pip install -U .
```

#### Windows 用户

```bash
cd ./backtrader; python -W ignore compile_cython_numba_files.py; cd ..; pip install -U .
```

注意：在 Windows 上编译时可能会有一个文件报错，这是正常的，可以忽略。

### 5. 验证安装

运行测试套件以验证安装：

```bash
pytest tests -n 4
```

## 常见问题

### 1. 编译错误

如果遇到编译错误，请确保：
- 已安装 C++ 编译器
- Python 版本正确（3.11+）
- 所有依赖都已正确安装

### 2. 导入错误

如果遇到模块导入错误，请检查：
- Python 环境变量是否正确设置
- 是否已经完成 pip install 步骤
- 是否在正确的目录中

### 3. 测试失败

如果某些测试失败：
- 加密货币相关的测试需要配置 API 密钥
- 某些测试可能需要特定的数据文件
- 检查是否所有可选依赖都已安装

## 下一步

- 阅读[快速开始](./quickstart.md)指南
- 查看[基本概念](../user_guide/basic_concepts.md)
- 浏览[示例代码](../examples/README.md)

## 获取帮助

如果在安装过程中遇到问题：
1. 查看[常见问题](#常见问题)
2. 搜索 [Issues](https://gitee.com/yunjinqi/backtrader/issues)
3. 在[官方论坛](https://www.backtrader.com/community)提问
4. 提交新的 [Issue](https://gitee.com/yunjinqi/backtrader/issues/new)

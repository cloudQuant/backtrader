# Use the official Ubuntu 24.04 base image
FROM ubuntu:24.04

# Set environment variables to prevent prompts during apt-get installs
ENV DEBIAN_FRONTEND=noninteractive

# Update the package list and install dependencies
RUN apt-get update && \
    apt-get install -y \
    python3.11 \
    python3.11-distutils \
    python3.11-dev \
    python3-pip \
    git \
    build-essential \
    curl \
    ca-certificates \
    libssl-dev \
    libffi-dev \
    libsqlite3-dev \
    libbz2-dev \
    libreadline-dev \
    liblzma-dev \
    zlib1g-dev \
    libncurses5-dev \
    libgdbm-dev \
    libdb-dev \
    && apt-get clean

# Set python3.11 as the default python version
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Install pip for Python 3.11
RUN curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && python3 get-pip.py && rm get-pip.py

# Clone the Backtrader repository from Gitee
RUN git clone https://gitee.com/yunjinqi/backtrader.git /app/backtrader

# Set the working directory to the cloned Backtrader repository
WORKDIR /app/backtrader

# Run the install_unix.sh script to install Backtrader
RUN chmod +x install_unix.sh && ./install_unix.sh
#!/usr/bin/env python
"""
Offline pip-like installer for backtrader
This script emulates 'pip install -U .' behavior but works offline
"""
import os
import sys
import subprocess
import tempfile
import shutil
import glob
import site
from pathlib import Path
import importlib.util

def has_package(package_name):
    """Check if a package is available"""
    return importlib.util.find_spec(package_name) is not None

def run_pip_command(cmd, cwd=None):
    """Run pip command with proper environment setup"""
    print(f"Executing: {' '.join(cmd)}")
    
    env = os.environ.copy()
    # Set environment variables to help pip work offline
    env["PIP_NO_INDEX"] = "1"
    env["PIP_NO_DEPS"] = "1"
    env["PIP_NO_BUILD_ISOLATION"] = "1"
    env["PIP_NO_CACHE_DIR"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    
    try:
        result = subprocess.run(
            cmd,
            env=env,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        success = result.returncode == 0
        output = result.stdout + "\n" + result.stderr
        return success, output
    except Exception as e:
        return False, str(e)

def build_wheel(project_dir):
    """Build wheel without dependencies"""
    print("\nBuilding wheel file...")
    wheel_dir = os.path.join(project_dir, "dist")
    os.makedirs(wheel_dir, exist_ok=True)
    
    # Clean existing wheel files
    for wheel_file in glob.glob(os.path.join(wheel_dir, "*.whl")):
        os.remove(wheel_file)
    
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--no-index",
        "--no-build-isolation",
        "--wheel-dir",
        wheel_dir,
        "."
    ]
    
    success, output = run_pip_command(cmd, cwd=project_dir)
    if not success:
        print("Failed to build wheel:")
        print(output)
        return None
    
    # Find the created wheel file
    wheel_files = glob.glob(os.path.join(wheel_dir, "*.whl"))
    if not wheel_files:
        print("No wheel files created")
        return None
    
    return wheel_files[0]

def install_wheel(wheel_path):
    """Install wheel without dependencies"""
    print(f"\nInstalling wheel: {os.path.basename(wheel_path)}...")
    
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-deps",
        "--no-index",
        "--force-reinstall",
        wheel_path
    ]
    
    success, output = run_pip_command(cmd)
    if not success:
        print("Failed to install wheel:")
        print(output)
        return False
    
    print("Wheel installed successfully")
    return True

def prepare_environment():
    """Prepare environment for offline pip installation"""
    print("\nPreparing environment for offline installation...")
    
    # Check for required build tools
    required_tools = ["wheel", "setuptools"]
    missing_tools = [tool for tool in required_tools if not has_package(tool)]
    
    if missing_tools:
        print(f"Warning: Missing required tools for wheel building: {', '.join(missing_tools)}")
        print("Installation may fail if these packages are not available")
    else:
        print("Required build tools are available")
    
    # Try importing numpy to see if it's available
    try:
        import numpy
        print("NumPy is available")
    except ImportError:
        print("Warning: NumPy is not available. Some features might be limited.")
    
    return True

def main():
    print("\n===== Backtrader Offline Pip-Like Installer =====")
    project_dir = Path(__file__).parent.absolute()
    
    # Prepare environment
    prepare_environment()
    
    # Build wheel
    wheel_path = build_wheel(project_dir)
    if not wheel_path:
        print("\nFailed to build wheel. Falling back to direct copy installation...")
        use_copy_method()
        return
    
    # Install wheel
    if not install_wheel(wheel_path):
        print("\nFailed to install wheel. Falling back to direct copy installation...")
        use_copy_method()
        return
    
    print("\nInstallation completed successfully!")
    print("Note: In offline mode, dependencies need to be installed separately")

def use_copy_method():
    """Fallback to direct copy method"""
    print("\nUsing direct copy method as fallback...")
    
    # Set package name and version
    package_name = "backtrader"
    package_version = "0.2.0"
    project_dir = Path(__file__).parent.absolute()
    
    try:
        # Check if we're in a virtual environment
        in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
        
        # Determine the site-packages directory
        if in_venv:
            site_packages = Path(site.getsitepackages()[0])
        else:
            site_packages = Path(site.getusersitepackages())
        
        # Create the destination directory if it doesn't exist
        os.makedirs(site_packages, exist_ok=True)
        
        # Source backtrader package
        src_package = project_dir / package_name
        
        # Destination package path
        dest_package = site_packages / package_name
        
        # Remove existing package if it exists
        if os.path.exists(dest_package):
            print(f"Removing existing {package_name} installation...")
            if os.path.isdir(dest_package):
                shutil.rmtree(dest_package)
            else:
                os.remove(dest_package)
        
        # Copy the package with all subdirectories
        print(f"Copying {package_name} with all subdirectories to {dest_package}...")
        shutil.copytree(src_package, dest_package, symlinks=False, ignore=None, dirs_exist_ok=False)
        
        # Verify subdirectories were copied
        for subdir in ['utils', 'indicators', 'analyzers', 'feeds', 'observers', 'sizers', 'stores', 'brokers']:
            src_subdir = os.path.join(src_package, subdir)
            dest_subdir = os.path.join(dest_package, subdir)
            if os.path.exists(src_subdir) and not os.path.exists(dest_subdir):
                print(f"WARNING: Subdirectory {subdir} was not copied properly!")
                print(f"Attempting to copy {subdir} separately...")
                # Try to copy subdirectory separately
                try:
                    shutil.copytree(src_subdir, dest_subdir)
                    print(f"Successfully copied {subdir}")
                except Exception as e:
                    print(f"Error copying {subdir}: {str(e)}")
        
        # Check if utils directory was copied
        if not os.path.exists(os.path.join(dest_package, 'utils')):
            print("ERROR: utils directory was not copied, installation will fail!")
            raise Exception("Failed to copy utils directory")
        else:
            print("Verified that utils directory was copied successfully")
        
        # Create metadata files for the package
        dist_info_dir = site_packages / f"{package_name}-{package_version}.dist-info"
        
        # Remove existing dist-info if it exists
        if os.path.exists(dist_info_dir):
            shutil.rmtree(dist_info_dir)
        
        # Create new dist-info directory
        os.makedirs(dist_info_dir, exist_ok=True)
        
        # Create METADATA file
        with open(dist_info_dir / "METADATA", "w") as f:
            f.write(f"Metadata-Version: 2.1\n")
            f.write(f"Name: {package_name}\n")
            f.write(f"Version: {package_version}\n")
            f.write(f"Summary: Enhanced backtrader library with Cython optimizations\n")
            f.write(f"Author: cloudQuant\n")
            f.write(f"Author-email: yunjinqi@qq.com\n")
            f.write(f"License: MIT\n")
            f.write(f"Requires-Python: >=3.8\n")
        
        # Create INSTALLER file
        with open(dist_info_dir / "INSTALLER", "w") as f:
            f.write("install_offline_pip.py\n")
        
        # Create RECORD file (empty for now)
        with open(dist_info_dir / "RECORD", "w") as f:
            pass
            
        print("Direct file copy installation completed successfully!")
        
    except Exception as e:
        print(f"Error during fallback installation: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()

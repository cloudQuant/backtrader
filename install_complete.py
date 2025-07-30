#!/usr/bin/env python
"""
Complete Backtrader Installation Script
This script ensures backtrader is properly installed with all subdirectories
Works in both online and offline environments
"""
import os
import sys
import subprocess
import shutil
import site
import glob
from pathlib import Path
import importlib.util
import urllib.request
from distutils.dir_util import copy_tree

def has_package(package_name):
    """Check if a package is available"""
    return importlib.util.find_spec(package_name) is not None

def check_internet_connection(timeout=3):
    """Check if internet connection is available"""
    test_urls = [
        "https://www.baidu.com",
        "https://www.google.com", 
        "https://pypi.org"
    ]
    
    for url in test_urls:
        try:
            urllib.request.urlopen(url, timeout=timeout)
            return True
        except:
            continue
    return False

def run_pip_command(cmd, cwd=None):
    """Run pip command with proper environment setup"""
    print(f"Executing: {' '.join(cmd)}")
    
    env = os.environ.copy()
    # Set environment variables for offline installation
    if not check_internet_connection():
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

def get_site_packages_dir():
    """Get the site-packages directory"""
    # Check if we're in a virtual environment
    in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    
    # Determine the site-packages directory
    if in_venv:
        site_packages = Path(site.getsitepackages()[0])
    else:
        site_packages = Path(site.getusersitepackages())
    
    # Create the destination directory if it doesn't exist
    os.makedirs(site_packages, exist_ok=True)
    
    return site_packages

def try_online_install(project_dir):
    """Try to install using pip with --no-build-isolation"""
    print("\n[1/3] Trying standard pip installation with --no-build-isolation...")
    
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-U",
        ".",
        "--no-build-isolation"
    ]
    
    success, output = run_pip_command(cmd, cwd=project_dir)
    print(output)
    
    if success:
        print("\n✅ Standard pip installation succeeded!")
        verify_installation()
        return True
    
    print("\n❌ Standard pip installation failed, trying next method...")
    return False

def try_setup_install(project_dir):
    """Try to install directly using setup.py"""
    print("\n[2/3] Trying direct setup.py installation with --no-deps...")
    
    cmd = [
        sys.executable,
        "setup.py",
        "install",
        "--no-deps"
    ]
    
    success, output = run_pip_command(cmd, cwd=project_dir)
    print(output)
    
    if success:
        print("\n✅ Direct setup.py installation succeeded!")
        verify_installation()
        return True
    
    print("\n❌ Direct setup.py installation failed, trying next method...")
    return False

def try_direct_copy_install(project_dir):
    """Install by directly copying files to site-packages"""
    print("\n[3/3] Trying direct file copy installation method...")
    
    # Set package name and version
    package_name = "backtrader"
    package_version = "0.2.0"
    
    try:
        # Determine the site-packages directory
        site_packages = get_site_packages_dir()
        
        # Source backtrader package
        src_package = project_dir / package_name
        
        # Destination package path
        dest_package = site_packages / package_name
        
        print(f"Source package: {src_package}")
        print(f"Destination: {dest_package}")
        
        # Remove existing package if it exists
        if os.path.exists(dest_package):
            print(f"Removing existing {package_name} installation...")
            if os.path.isdir(dest_package):
                shutil.rmtree(dest_package)
            else:
                os.remove(dest_package)
        
        # Create parent directories if they don't exist
        os.makedirs(os.path.dirname(dest_package), exist_ok=True)
        
        # Use distutils copy_tree to ensure all subdirectories are copied
        print(f"Copying {package_name} with all subdirectories...")
        copy_tree(str(src_package), str(dest_package))
        
        # Additional verification of subdirectories
        missing_subdirs = []
        important_subdirs = ['utils', 'indicators', 'analyzers', 'feeds', 'observers', 'sizers', 'stores', 'brokers']
        for subdir in important_subdirs:
            src_subdir = os.path.join(src_package, subdir)
            dest_subdir = os.path.join(dest_package, subdir)
            
            if os.path.exists(src_subdir) and not os.path.exists(dest_subdir):
                missing_subdirs.append(subdir)
                print(f"WARNING: {subdir} was not copied! Attempting to copy manually...")
                try:
                    # Try another copy method
                    shutil.copytree(src_subdir, dest_subdir)
                    print(f"Successfully copied {subdir}")
                    missing_subdirs.remove(subdir)
                except Exception as e:
                    print(f"Error copying {subdir}: {str(e)}")
        
        if missing_subdirs:
            print(f"ERROR: Failed to copy subdirectories: {', '.join(missing_subdirs)}")
            print("Installation will likely fail!")
            return False
        
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
            f.write("install_complete.py\n")
        
        # Create RECORD file (empty for now)
        with open(dist_info_dir / "RECORD", "w") as f:
            pass
            
        print("\n✅ Direct file copy installation completed!")
        verify_installation()
        return True
        
    except Exception as e:
        print(f"\n❌ Error during direct copy installation: {str(e)}")
        return False

def verify_installation():
    """Verify the installation was successful"""
    print("\nVerifying installation...")
    
    # Check if backtrader is importable
    try:
        import backtrader
        print(f"✅ Backtrader {backtrader.__version__} successfully imported")
        
        # Try to import utils to check if subdirectories were properly installed
        try:
            from backtrader.utils import num2date
            print("✅ Backtrader utils successfully imported")
        except ImportError as e:
            print(f"❌ Error importing backtrader.utils: {str(e)}")
            return False
        
        # Try to import indicators
        try:
            from backtrader import indicators
            print("✅ Backtrader indicators successfully imported")
        except ImportError as e:
            print(f"❌ Error importing backtrader.indicators: {str(e)}")
            return False
            
        return True
    except ImportError as e:
        print(f"❌ Error importing backtrader: {str(e)}")
        return False

def main():
    print("\n========= Backtrader Complete Installation =========")
    print("This script will install backtrader with all subdirectories")
    
    # Get project directory
    project_dir = Path(__file__).parent.absolute()
    print(f"Project directory: {project_dir}")
    
    # Check internet connection
    online = check_internet_connection()
    if online:
        print("✅ Internet connection detected")
    else:
        print("⚠️ No internet connection detected, using offline installation methods")
    
    # Try installation methods in order
    if online and try_online_install(project_dir):
        print("\n🎉 Installation successful via pip!")
    elif try_setup_install(project_dir):
        print("\n🎉 Installation successful via setup.py!")
    elif try_direct_copy_install(project_dir):
        print("\n🎉 Installation successful via direct copy!")
    else:
        print("\n❌ All installation methods failed!")
        print("Please check the error messages above and ensure you have appropriate permissions.")
        return False
    
    print("\n📌 Installation Notes:")
    print("1. If using in offline mode, dependencies must be installed separately")
    print("2. Required dependencies: numpy, pandas, matplotlib")
    print("3. Optional dependencies: plotly, pyecharts, numba, scipy, cython")
    print("\nTo uninstall backtrader, use: python uninstall.py")
    
    return True

if __name__ == "__main__":
    main()

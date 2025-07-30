#!/usr/bin/env python
"""
Fix for backtrader installation - ensures all subdirectories are included
This script will:
1. Create a complete sdist package with all subdirectories
2. Install from that package file
"""
import os
import sys
import subprocess
import shutil
import tempfile
import glob
from pathlib import Path
import site

def run_command(cmd, cwd=None, capture_output=True):
    """Run a command and return output"""
    print(f"Running: {' '.join(cmd)}")
    try:
        if capture_output:
            result = subprocess.run(cmd, cwd=cwd, check=True, 
                                  stdout=subprocess.PIPE, 
                                  stderr=subprocess.PIPE,
                                  text=True)
            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            return result.returncode == 0
        else:
            result = subprocess.run(cmd, cwd=cwd, check=True)
            return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"Command failed with error: {e}")
        if e.stdout:
            print("STDOUT:", e.stdout)
        if e.stderr:
            print("STDERR:", e.stderr)
        return False

def create_sdist():
    """Create a source distribution with all subdirectories"""
    print("\nStep 1: Creating source distribution...")
    
    # Clean existing dist directory
    dist_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dist')
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)
    os.makedirs(dist_dir, exist_ok=True)
    
    # Create sdist using setuptools
    cmd = [sys.executable, "setup.py", "sdist"]
    success = run_command(cmd)
    
    if not success:
        print("Failed to create source distribution")
        return None
    
    # Find the sdist file
    sdist_files = glob.glob(os.path.join(dist_dir, "*.tar.gz"))
    if not sdist_files:
        print("No source distribution file found")
        return None
    
    print(f"Created source distribution: {sdist_files[0]}")
    return sdist_files[0]

def install_from_sdist(sdist_file):
    """Install from source distribution file"""
    print(f"\nStep 2: Installing from source distribution: {os.path.basename(sdist_file)}...")
    
    # Install the package with pip
    cmd = [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-build-isolation", sdist_file]
    success = run_command(cmd)
    
    if success:
        print("\nPackage installed successfully!")
    else:
        print("\nFailed to install package from source distribution")
    
    return success

def verify_installation():
    """Verify that all modules are correctly installed"""
    print("\nStep 3: Verifying installation...")
    
    # Try to import backtrader
    try:
        import importlib
        import importlib.util
        
        # Try to import backtrader
        bt_spec = importlib.util.find_spec("backtrader")
        if not bt_spec:
            print("❌ backtrader package not found")
            return False
        
        bt_path = os.path.dirname(bt_spec.origin)
        print(f"backtrader installed at: {bt_path}")
        
        # Check for key subdirectories
        subdirs = ["utils", "indicators", "analyzers", "feeds", "observers", 
                  "sizers", "stores", "brokers"]
        
        missing_subdirs = []
        for subdir in subdirs:
            subdir_path = os.path.join(bt_path, subdir)
            init_path = os.path.join(subdir_path, "__init__.py")
            if not os.path.exists(subdir_path) or not os.path.exists(init_path):
                missing_subdirs.append(subdir)
        
        if missing_subdirs:
            print(f"❌ Missing subdirectories: {', '.join(missing_subdirs)}")
            
            # Fallback to direct copy
            print("\nAttempting fallback to direct copy method...")
            return fix_by_direct_copy()
        else:
            print("✅ All subdirectories are present")
            
            # Test imports
            try:
                import backtrader as bt
                print(f"✅ Successfully imported backtrader {bt.__version__}")
                from backtrader.utils import num2date
                print("✅ Successfully imported backtrader.utils")
                return True
            except ImportError as e:
                print(f"❌ Import error: {e}")
                print("\nAttempting fallback to direct copy method...")
                return fix_by_direct_copy()
    except Exception as e:
        print(f"❌ Error during verification: {e}")
        print("\nAttempting fallback to direct copy method...")
        return fix_by_direct_copy()

def fix_by_direct_copy():
    """Fix installation by direct copying all files"""
    print("\nEmergency fix: Copying all files directly...")
    
    package_name = "backtrader"
    package_version = "0.2.0"
    project_dir = os.path.dirname(os.path.abspath(__file__))
    src_package = os.path.join(project_dir, package_name)
    
    # Check if source package exists
    if not os.path.exists(src_package):
        print(f"❌ Source package directory not found: {src_package}")
        return False
    
    # Try different potential site-packages directories
    site_dirs = []
    
    # Add system site-packages
    site_dirs.extend(site.getsitepackages())
    
    # Add user site-packages
    site_dirs.append(site.getusersitepackages())
    
    # Add current environment
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        site_dirs.append(os.path.join(sys.prefix, 'Lib', 'site-packages'))
    
    # Try anaconda specific paths if it looks like an anaconda environment
    if 'conda' in sys.prefix.lower() or 'anaconda' in sys.prefix.lower():
        site_dirs.append(os.path.join(sys.prefix, 'Lib', 'site-packages'))
    
    # Remove duplicates
    site_dirs = list(set(site_dirs))
    
    # Try each potential destination
    success = False
    for site_dir in site_dirs:
        dest_package = os.path.join(site_dir, package_name)
        dist_info_dir = os.path.join(site_dir, f"{package_name}-{package_version}.dist-info")
        
        print(f"\nTrying to install to: {site_dir}")
        
        if not os.path.exists(site_dir):
            print(f"❌ Site directory doesn't exist: {site_dir}")
            continue
        
        try:
            # Clean up existing installation
            if os.path.exists(dest_package):
                print(f"Removing existing package: {dest_package}")
                shutil.rmtree(dest_package)
            
            if os.path.exists(dist_info_dir):
                print(f"Removing existing dist-info: {dist_info_dir}")
                shutil.rmtree(dist_info_dir)
            
            # Copy package recursively
            print(f"Copying package to: {dest_package}")
            shutil.copytree(src_package, dest_package)
            
            # Create dist-info
            print(f"Creating dist-info: {dist_info_dir}")
            os.makedirs(dist_info_dir, exist_ok=True)
            
            # Create METADATA file
            with open(os.path.join(dist_info_dir, "METADATA"), "w") as f:
                f.write(f"Metadata-Version: 2.1\n")
                f.write(f"Name: {package_name}\n")
                f.write(f"Version: {package_version}\n")
                f.write(f"Summary: Enhanced backtrader library with Cython optimizations\n")
                f.write(f"Author: cloudQuant\n")
                f.write(f"Author-email: yunjinqi@qq.com\n")
                f.write(f"License: MIT\n")
                f.write(f"Requires-Python: >=3.8\n")
            
            # Create INSTALLER file
            with open(os.path.join(dist_info_dir, "INSTALLER"), "w") as f:
                f.write("setup_fix_subdirs.py\n")
            
            # Create RECORD file (empty for now)
            with open(os.path.join(dist_info_dir, "RECORD"), "w") as f:
                pass
            
            # Verify subdirectories were copied
            all_copied = True
            for subdir in ["utils", "indicators", "analyzers", "feeds"]:
                subdir_path = os.path.join(dest_package, subdir)
                if not os.path.exists(subdir_path):
                    print(f"❌ Failed to copy {subdir} directory")
                    all_copied = False
            
            if all_copied:
                print("✅ All subdirectories copied successfully")
                success = True
                break
            else:
                print("❌ Some subdirectories were not copied")
                
        except Exception as e:
            print(f"❌ Error installing to {site_dir}: {e}")
    
    if success:
        print("\n✅ Direct copy installation successful!")
    else:
        print("\n❌ All installation attempts failed")
    
    return success

def main():
    print("\n===== Backtrader Installation Fix =====")
    print("This script will fix the issue with missing subdirectories")
    
    # Create source distribution
    sdist_file = create_sdist()
    if not sdist_file:
        print("Failed to create source distribution, trying direct copy method...")
        success = fix_by_direct_copy()
        if success:
            print("\n✅ Installation fixed using direct copy method!")
        else:
            print("\n❌ Failed to fix installation")
        return
    
    # Install from source distribution
    success = install_from_sdist(sdist_file)
    if not success:
        print("Failed to install from source distribution, trying direct copy method...")
        success = fix_by_direct_copy()
        if success:
            print("\n✅ Installation fixed using direct copy method!")
        else:
            print("\n❌ Failed to fix installation")
        return
    
    # Verify installation
    verified = verify_installation()
    if verified:
        print("\n🎉 Installation has been fixed successfully!")
        print("You can now import backtrader and all its submodules")
    else:
        print("\n❌ Failed to verify installation")

if __name__ == "__main__":
    main()

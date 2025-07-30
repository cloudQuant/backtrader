#!/usr/bin/env python
"""
Universal uninstaller for backtrader
This script ensures backtrader is completely uninstalled regardless of how it was installed
"""
import os
import sys
import subprocess
import shutil
import site
import glob
from pathlib import Path
import importlib.util

def run_command(cmd, env=None):
    """Run a command and return the result and success status"""
    try:
        result = subprocess.run(
            cmd,
            env=env,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)

def get_package_location(package_name):
    """Get the location of an installed package"""
    try:
        spec = importlib.util.find_spec(package_name)
        if spec is None:
            return None
        
        # If it's a namespace package without __file__, origin will be None
        if spec.origin is None:
            return None
            
        # Convert from .py file to package directory
        if os.path.isfile(spec.origin):
            package_dir = os.path.dirname(spec.origin)
        else:
            package_dir = spec.origin
            
        return package_dir
    except ImportError:
        return None

def find_all_package_files(package_name):
    """Find all possible locations where the package might be installed"""
    package_files = []
    
    # Check site-packages directories
    for site_dir in site.getsitepackages():
        # Check for the package directory
        package_path = os.path.join(site_dir, package_name)
        if os.path.exists(package_path):
            package_files.append(package_path)
            
        # Check for .egg-info and .dist-info directories
        info_paths = []
        info_paths.extend(glob.glob(os.path.join(site_dir, f"{package_name}-*.egg-info")))
        info_paths.extend(glob.glob(os.path.join(site_dir, f"{package_name}-*.dist-info")))
        package_files.extend(info_paths)
    
    # Check user site-packages
    user_site = site.getusersitepackages()
    package_path = os.path.join(user_site, package_name)
    if os.path.exists(package_path):
        package_files.append(package_path)
        
    info_paths = []
    info_paths.extend(glob.glob(os.path.join(user_site, f"{package_name}-*.egg-info")))
    info_paths.extend(glob.glob(os.path.join(user_site, f"{package_name}-*.dist-info")))
    package_files.extend(info_paths)
    
    return package_files

def main():
    package_name = "backtrader"
    print(f"\n===== Backtrader Universal Uninstaller =====")
    
    # SAFETY CHECK: Make sure we're not running in the source directory
    script_dir = os.path.abspath(os.path.dirname(__file__))
    source_package_dir = os.path.join(script_dir, package_name)
    if os.path.isdir(source_package_dir):
        print("\nSAFETY WARNING: Running from what appears to be the source directory.")
        print(f"This script will NOT remove the source directory: {source_package_dir}")
        print("It will ONLY uninstall from site-packages directories.\n")
    
    # First try standard pip uninstall
    print(f"\nTrying standard pip uninstall for {package_name}...")
    cmd = [sys.executable, "-m", "pip", "uninstall", "-y", package_name]
    success, output = run_command(cmd)
    
    print(output)
    
    if "No files were found to uninstall" in output:
        print(f"\nPip couldn't find files to uninstall. Trying manual removal...")
        
        # Try to get package location using importlib
        package_dir = get_package_location(package_name)
        if package_dir:
            # SAFETY CHECK: Make sure we're not deleting the source directory
            script_dir = os.path.abspath(os.path.dirname(__file__))
            source_package_dir = os.path.join(script_dir, package_name)
            
            # Only remove if it's not the source directory
            if os.path.normpath(package_dir) != os.path.normpath(source_package_dir):
                print(f"Found installed {package_name} at: {package_dir}")
                
                # Remove the package directory
                try:
                    if os.path.isdir(package_dir):
                        shutil.rmtree(package_dir)
                        print(f"Removed directory: {package_dir}")
                    else:
                        os.remove(package_dir)
                        print(f"Removed file: {package_dir}")
                except Exception as e:
                    print(f"Error removing {package_dir}: {str(e)}")
            else:
                print(f"SKIPPED: Found package at {package_dir} but it appears to be the source directory.")
                print("To protect your code, this directory will NOT be removed.")
        
        # Find and remove all package-related files
        script_dir = os.path.abspath(os.path.dirname(__file__))
        source_package_dir = os.path.join(script_dir, package_name)
        
        package_files = find_all_package_files(package_name)
        if package_files:
            safe_files = []
            for file_path in package_files:
                # Skip any files that are in or under the source directory
                if os.path.normpath(file_path).startswith(os.path.normpath(script_dir)):
                    print(f"SKIPPED: {file_path} - appears to be part of the source code")
                else:
                    safe_files.append(file_path)
            
            if safe_files:
                print(f"\nFound {len(safe_files)} safe files/directories related to {package_name}:")
                for file_path in safe_files:
                    try:
                        if os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                            print(f"Removed directory: {file_path}")
                        else:
                            os.remove(file_path)
                            print(f"Removed file: {file_path}")
                    except Exception as e:
                        print(f"Error removing {file_path}: {str(e)}")
            else:
                print(f"\nNo safe files found to remove for {package_name}")
                print("Only source code files were detected and they have been protected.")
        else:
            print(f"No additional files found for {package_name}")
    
    # Check if uninstall was successful
    try:
        importlib.import_module(package_name)
        print(f"\nWARNING: {package_name} is still importable after uninstall attempts!")
        print("There might be other installations in different paths.")
    except ImportError:
        print(f"\n✓ {package_name} has been successfully uninstalled!")
    
    print("\nUninstallation process completed.")

if __name__ == "__main__":
    main()

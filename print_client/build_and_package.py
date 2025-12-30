"""
Build and Package Print Client for Distribution
================================================
This script:
1. Builds the standalone executable with PyInstaller
2. Packages all necessary files into a ZIP
3. Places it in static/downloads/ for web download

Usage:
    python build_and_package.py
"""
import subprocess
import sys
import os
import shutil
import zipfile
from datetime import datetime

def main():
    print("=" * 70)
    print("   BUILD AND PACKAGE PRINT CLIENT")
    print("=" * 70)
    print()
    
    # Get paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    static_downloads = os.path.join(project_root, 'static', 'downloads')
    
    # Step 1: Install dependencies
    print("Step 1: Installing dependencies...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pyinstaller", "colorama"])
        print("✓ Dependencies installed")
    except Exception as e:
        print(f"✗ Error installing dependencies: {e}")
        return False
    
    # Step 2: Build executable
    print("\nStep 2: Building executable...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=PrintClient",
        "--onedir",
        "--console",
        "--icon=NONE",
        "--add-data=config.json.example;.",
        "--hidden-import=win32print",
        "--hidden-import=win32ui",
        "--hidden-import=win32con",
        "--hidden-import=requests",
        "--hidden-import=colorama",
        "print_client.py"
    ]
    
    try:
        # Clean previous build
        if os.path.exists('build'):
            shutil.rmtree('build')
        if os.path.exists('dist'):
            shutil.rmtree('dist')
        if os.path.exists('PrintClient.spec'):
            os.remove('PrintClient.spec')
        
        subprocess.check_call(cmd, cwd=script_dir)
        print("✓ Executable built successfully")
    except Exception as e:
        print(f"✗ Build failed: {e}")
        return False
    
    # Step 3: Create package folder
    print("\nStep 3: Creating package...")
    package_dir = os.path.join(script_dir, 'dist', 'PrintClient')
    
    if not os.path.exists(package_dir):
        print(f"✗ Build output not found: {package_dir}")
        return False
    
    # Copy additional files
    files_to_copy = [
        'config.json.example',
        'README_SIMPLE.md',
        'start_print_client.bat',
        'SETUP.bat',
        'service_installer.py',
        'diagnose_printer.py',
        'DIAGNOSE_PRINTER.bat',
        'FIX_PRINTER_ERROR.bat',
        'TROUBLESHOOTING.md',
    ]
    
    for filename in files_to_copy:
        src = os.path.join(script_dir, filename)
        dst = os.path.join(package_dir, filename)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"  → Copied {filename}")
        else:
            print(f"  ⚠ Skipped {filename} (not found)")
    
    # Create logs directory
    logs_dir = os.path.join(package_dir, 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    print(f"  → Created logs/ directory")
    
    # Step 4: Create ZIP
    print("\nStep 4: Creating ZIP archive...")
    
    # Ensure static/downloads exists
    os.makedirs(static_downloads, exist_ok=True)
    
    zip_path = os.path.join(static_downloads, 'PrintClient_Windows.zip')
    backup_path = os.path.join(static_downloads, f'PrintClient_Windows_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip')
    
    # Backup existing ZIP
    if os.path.exists(zip_path):
        shutil.copy2(zip_path, backup_path)
        print(f"  → Backed up existing ZIP to: {os.path.basename(backup_path)}")
    
    # Create new ZIP
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Walk through package_dir and add all files
        for root, dirs, files in os.walk(package_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.join('PrintClient', os.path.relpath(file_path, package_dir))
                zipf.write(file_path, arcname)
    
    # Get ZIP size
    zip_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    
    print(f"✓ ZIP created: {zip_path}")
    print(f"  Size: {zip_size_mb:.1f} MB")
    
    # Step 5: Summary
    print("\n" + "=" * 70)
    print("   BUILD COMPLETE!")
    print("=" * 70)
    print(f"\nPackage location: {zip_path}")
    print(f"Package size: {zip_size_mb:.1f} MB")
    print("\nWhat's included:")
    print("  • PrintClient.exe (standalone executable)")
    print("  • All DLL dependencies")
    print("  • Configuration files")
    print("  • Diagnostic tools (NEW!)")
    print("  • Troubleshooting guide (NEW!)")
    print("  • Quick fix scripts (NEW!)")
    print("\nThe updated print client includes:")
    print("  ✓ Automatic printer validation")
    print("  ✓ Smart fallback to working printers")
    print("  ✓ Error 1905 detection and handling")
    print("  ✓ Diagnostic tool (DIAGNOSE_PRINTER.bat)")
    print("  ✓ Quick fix tool (FIX_PRINTER_ERROR.bat)")
    print("\nUsers can now download this from:")
    print("  https://hospitality.easyfixsoft.com/admin-panel/printer-settings/")
    print("\n" + "=" * 70)
    
    return True

if __name__ == '__main__':
    try:
        success = main()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nBuild cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

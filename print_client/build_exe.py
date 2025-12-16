"""
Build script to create standalone print_client.exe
This creates an executable that doesn't require Python to be installed!

Run this script on YOUR development machine (where Python is installed):
    python build_exe.py

It will create: dist/PrintClient/PrintClient.exe
Zip the dist/PrintClient folder and give it to restaurants.
"""
import subprocess
import sys
import os

def main():
    print("=" * 60)
    print("   BUILDING PRINT CLIENT EXECUTABLE")
    print("=" * 60)
    
    # Check if PyInstaller is installed
    try:
        import PyInstaller
        print("✓ PyInstaller is installed")
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    # Build the executable
    print("\nBuilding executable...")
    
    # PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=PrintClient",
        "--onedir",  # Creates a folder with exe + dependencies
        "--console",  # Show console window (important for logs)
        "--icon=NONE",  # No icon (you can add one later)
        "--add-data=config.json.example;.",  # Include example config
        "--hidden-import=win32print",
        "--hidden-import=win32ui",
        "--hidden-import=win32con",
        "--hidden-import=requests",
        "print_client.py"
    ]
    
    try:
        subprocess.check_call(cmd)
        print("\n" + "=" * 60)
        print("   BUILD SUCCESSFUL!")
        print("=" * 60)
        print("\nOutput location: dist/PrintClient/")
        print("\nTo distribute to restaurants:")
        print("1. Copy the entire 'dist/PrintClient' folder")
        print("2. Add config.json (they need to edit with their token)")
        print("3. Zip it and provide download link")
        print("\nRestaurant just runs: PrintClient.exe")
        print("NO PYTHON INSTALLATION NEEDED!")
    except subprocess.CalledProcessError as e:
        print(f"\n✗ Build failed: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

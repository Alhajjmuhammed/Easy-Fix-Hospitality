"""
Printer Diagnostic Tool
=======================
Checks all printers and identifies which ones are actually usable.
Helps troubleshoot Windows printer driver issues (Error 1905, etc.)

Usage: python diagnose_printer.py
"""

import win32print
import win32ui
from colorama import init, Fore, Style
import sys

# Initialize colorama for colored console output
try:
    init(autoreset=True)
except:
    pass

def validate_printer(printer_name):
    """Test if a printer can actually be opened and used"""
    try:
        hPrinter = win32print.OpenPrinter(printer_name)
        win32print.ClosePrinter(hPrinter)
        return True, "OK"
    except Exception as e:
        error_code = None
        error_msg = str(e)
        
        # Extract error code if present
        if "1905" in error_msg:
            error_code = 1905
            error_msg = "Printer deleted/not available (Error 1905)"
        elif "1801" in error_msg:
            error_code = 1801
            error_msg = "Printer name is invalid (Error 1801)"
        elif "1722" in error_msg:
            error_code = 1722
            error_msg = "RPC server unavailable (Error 1722)"
        
        return False, error_msg

def is_thermal_printer(printer_name):
    """Check if printer name suggests it's a thermal printer"""
    thermal_keywords = ['thermal', 'pos', 'receipt', 'retsol', 'tp806', 'xprinter', 'epson tm', 'star tsp']
    printer_lower = printer_name.lower()
    return any(keyword in printer_lower for keyword in thermal_keywords)

def main():
    print("\n" + "=" * 70)
    print("  PRINTER DIAGNOSTIC TOOL")
    print("=" * 70)
    print("\nScanning all Windows printers...\n")
    
    # Get all printers
    printers = [printer[2] for printer in win32print.EnumPrinters(2)]
    
    if not printers:
        print(Fore.RED + "❌ No printers found!")
        print("\nPlease install printer drivers first.")
        return
    
    print(f"Found {len(printers)} printer(s):\n")
    
    usable_printers = []
    unusable_printers = []
    thermal_printers = []
    
    for i, printer in enumerate(printers, 1):
        is_usable, status = validate_printer(printer)
        is_thermal = is_thermal_printer(printer)
        
        # Print status
        if is_usable:
            status_icon = Fore.GREEN + "✓ USABLE"
            usable_printers.append(printer)
            if is_thermal:
                thermal_printers.append(printer)
        else:
            status_icon = Fore.RED + "✗ NOT USABLE"
            unusable_printers.append((printer, status))
        
        thermal_label = Fore.CYAN + " [THERMAL]" if is_thermal else ""
        
        print(f"{i}. {printer}")
        print(f"   {status_icon}{thermal_label}")
        if not is_usable:
            print(f"   Error: {status}")
        print()
    
    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total printers: {len(printers)}")
    print(f"{Fore.GREEN}Usable printers: {len(usable_printers)}")
    print(f"{Fore.RED}Unusable printers: {len(unusable_printers)}")
    print(f"{Fore.CYAN}Thermal printers detected: {len(thermal_printers)}")
    print()
    
    # Recommendations
    if thermal_printers:
        print(Fore.GREEN + "✓ RECOMMENDED PRINTER(S) FOR AUTO-PRINT:")
        for printer in thermal_printers:
            print(f"  • {printer}")
        print()
    elif usable_printers:
        print(Fore.YELLOW + "⚠ NO THERMAL PRINTERS DETECTED")
        print("  Usable printers available:")
        for printer in usable_printers:
            print(f"  • {printer}")
        print()
    
    if unusable_printers:
        print(Fore.RED + "❌ PRINTER ISSUES DETECTED:")
        for printer, error in unusable_printers:
            print(f"  • {printer}")
            print(f"    {error}")
        print()
        print("HOW TO FIX:")
        print("  1. Check printer is powered ON and connected")
        print("  2. Remove and re-add the printer in Windows Settings")
        print("  3. Reinstall printer driver from manufacturer")
        print("  4. Restart the print spooler service:")
        print("     net stop spooler && net start spooler")
        print()
    
    # Default printer
    try:
        default = win32print.GetDefaultPrinter()
        is_usable, status = validate_printer(default)
        if is_usable:
            print(f"Default Printer: {Fore.GREEN}{default} ✓")
        else:
            print(f"Default Printer: {Fore.RED}{default} ✗ (NOT USABLE)")
    except:
        print("Default Printer: Not set")
    
    print("\n" + "=" * 70)
    print()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nDiagnostic cancelled.")
    except Exception as e:
        print(f"\n{Fore.RED}Error running diagnostic: {e}")
        import traceback
        traceback.print_exc()

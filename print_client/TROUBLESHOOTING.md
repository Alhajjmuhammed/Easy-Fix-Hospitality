# 🔧 Print Client Troubleshooting Guide

## Error 1905: "The specified printer has been deleted"

This error means Windows thinks the printer exists, but it's not actually available. This commonly happens after:
- Printer was unplugged and reconnected
- Printer drivers were partially uninstalled
- Windows updates changed printer configuration
- Printer is in an error state

---

## 🚀 Quick Fix Steps

### Step 1: Run Diagnostic Tool
```batch
cd print_client
DIAGNOSE_PRINTER.bat
```
This will show which printers are actually usable vs. just listed.

### Step 2: Fix the Broken Printer

#### Option A: Remove and Re-add Printer (Recommended)
1. Open **Settings** → **Devices** → **Printers & Scanners**
2. Find **RETSOL TP806** (or the broken printer)
3. Click **Remove Device**
4. Click **Add a printer or scanner**
5. Select your printer and click **Add Device**
6. Restart the print client

#### Option B: Update Printer Configuration on Server
If the broken printer can't be fixed immediately, use a working printer:

1. Go to: https://hospitality.easyfixsoft.com/admin_panel/printer_settings/
2. Change **Receipt Printer Name** from `RETSOL TP806` to `RETSOL TP806S` (or leave blank for auto-detect)
3. Save settings
4. Print client will automatically use the working printer

#### Option C: Use Auto-Detect (Easiest)
1. Go to printer settings on the website
2. **Clear/remove** the printer name fields (leave them empty)
3. The print client will automatically find and use any working thermal printer

---

## 🔍 Diagnostic Commands

### Check Print Spooler Service
```cmd
REM Check if running
sc query spooler

REM Restart if needed
net stop spooler
net start spooler
```

### List All Printers
```cmd
wmic printer list brief
```

### Check Printer Driver
1. Open **Control Panel** → **Devices and Printers**
2. Right-click the printer → **Printer Properties**
3. If you see errors or can't open properties → Driver is corrupted

---

## 🛠️ Advanced Fixes

### Fix 1: Reinstall Printer Driver
1. Download latest driver from RETSOL website
2. Uninstall current printer completely
3. Restart computer
4. Install fresh driver
5. Restart print client

### Fix 2: Clear Print Queue
```cmd
net stop spooler
del /Q /F /S "%systemroot%\System32\spool\PRINTERS\*"
net start spooler
```

### Fix 3: Check Printer Connection
- USB printer: Try different USB port
- Network printer: Check IP address, ping the printer
- Bluetooth printer: Re-pair the device

### Fix 4: Set Different Default Printer
```cmd
REM List printers
wmic printer get name,default

REM Set working printer as default
rundll32 printui.dll,PrintUIEntry /y /n "RETSOL TP806S"
```

---

## 📋 Common Issues

### Issue: "Printer appears in list but can't print"
**Cause:** Driver corruption or printer offline  
**Fix:** Remove and re-add printer, or use different printer

### Issue: "Auto-detect finds wrong printer"
**Cause:** Multiple printers installed  
**Fix:** Specify exact printer name in server settings

### Issue: "Print client retrieves jobs but doesn't print"
**Cause:** Printer validation fails (Error 1905)  
**Fix:** Run diagnostic tool, fix broken printers

### Issue: "Works on one computer but not another"
**Cause:** Different printer names or one printer is broken  
**Solution:** 
1. Run diagnostic on both computers
2. Update server settings to use working printer name
3. Or use auto-detect (leave printer name blank)

---

## ✅ Verification Steps

After fixing, verify it works:

1. **Stop print client** (close the window)
2. **Run diagnostic**: `DIAGNOSE_PRINTER.bat`
3. **Verify working printer** shows ✓ USABLE
4. **Start print client**: `start_print_client.bat`
5. **Place test order** on website
6. **Check print happens automatically**

---

## 🆘 Still Not Working?

If print client shows these logs, printer is the issue:
```
✓ Found matching printer for receipt: RETSOL TP806
ERROR - Print error: (1905, 'StartDocPrinter', 'The specified printer has been deleted.')
```

**This means:** Windows can see the printer but can't use it.

**Solution:** Either fix that specific printer OR change to a different working printer.

---

## 📞 Contact Support

If all fixes fail, provide these details:
1. Output from `DIAGNOSE_PRINTER.bat`
2. Print client logs (from `logs/` folder)
3. Screenshot of Windows Printers & Scanners page
4. What changed since it last worked

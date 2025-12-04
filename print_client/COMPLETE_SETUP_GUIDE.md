# 🖨️ Restaurant Print System - Complete Setup Guide
## Easy-Fix Hospitality

---

# PART 1: FOR RESTAURANT OWNERS (Self-Setup)

## What You Need
- Windows Computer (Windows 10 or 11)
- Thermal Receipt Printer (USB connected)
- Internet Connection
- Your Restaurant Login (username & password)

---

## Step 1: Install Python (One Time Only)

1. Open your web browser
2. Go to: **https://www.python.org/downloads/**
3. Click the yellow button **"Download Python"**
4. Open the downloaded file
5. ⚠️ **VERY IMPORTANT:** Check the box ☑️ **"Add Python to PATH"**
6. Click **"Install Now"**
7. Wait until finished, then click **"Close"**

✅ Python is now installed!

---

## Step 2: Download Print Client

1. Get the **print_client** folder from your system administrator
2. Copy it to your computer at: `C:\PrintClient`

The folder contains:
```
C:\PrintClient\
    ├── print_client.py
    ├── config.json
    ├── start_print_client.bat
    └── README.md
```

---

## Step 3: Install Required Software

1. Press **Windows Key + R** on your keyboard
2. Type `cmd` and press **Enter**
3. A black window opens (Command Prompt)
4. Type this exactly and press **Enter**:

```
pip install requests pywin32
```

5. Wait until you see "Successfully installed"
6. Close the window

✅ Software installed!

---

## Step 4: Get Your API Token

1. Open your web browser
2. Go to: **https://hospitality.easyfixsoft.com**
3. Click **Login**
4. Enter your username and password
5. Click **Printer Settings** (in the left menu)
6. You will see your **API Token** - a long code like this:
   ```
   272c3e2835d2523b6a1188b784ace3eafde658c7
   ```
7. Click **Copy** button next to the token

✅ Token copied!

---

## Step 5: Configure Print Client

1. Go to `C:\PrintClient` folder
2. Open the file `config.json` with Notepad
3. Replace the content with:

```json
{
    "server_url": "https://hospitality.easyfixsoft.com",
    "api_token": "PASTE_YOUR_TOKEN_HERE",
    "poll_interval": 5,
    "auto_detect_printer": true
}
```

4. Replace `PASTE_YOUR_TOKEN_HERE` with the token you copied
5. Save the file (Ctrl + S)
6. Close Notepad

**Example of completed config.json:**
```json
{
    "server_url": "https://hospitality.easyfixsoft.com",
    "api_token": "272c3e2835d2523b6a1188b784ace3eafde658c7",
    "poll_interval": 5,
    "auto_detect_printer": true
}
```

✅ Configuration done!

---

## Step 6: Connect Your Printer

1. Connect your thermal printer to the computer with USB cable
2. Turn ON the printer
3. Wait 10 seconds for Windows to detect it

✅ Printer ready!

---

## Step 7: Start Print Client

1. Go to `C:\PrintClient` folder
2. Double-click on **start_print_client.bat**
3. A black window opens with:

```
╔═══════════════════════════════════════════════════════════╗
║   Restaurant Print Client - Thermal Printer Service       ║
╚═══════════════════════════════════════════════════════════╝

Print Client Started
Server: https://hospitality.easyfixsoft.com
Printer: [Your Printer Name]
Poll Interval: 5 seconds
```

✅ **DONE! Your system is now running!**

---

## Daily Operation

### Every Morning:
1. Turn ON the computer
2. Turn ON the printer
3. Double-click **start_print_client.bat**
4. Leave the black window open all day

### Every Evening:
1. Close the black window (or press Ctrl+C)
2. Turn off the printer
3. Turn off the computer (optional)

---

# PART 2: IMPORTANT INFORMATION

## 🔐 Your Token is Private

- Your token is like a password
- It only shows YOUR restaurant's orders
- Do NOT share your token with other restaurants
- Each restaurant has their OWN different token

## 🔄 If Token is Compromised

1. Log in to admin panel
2. Go to **Printer Settings**
3. Click **Regenerate Token**
4. Copy the NEW token
5. Update your config.json with the new token
6. Restart Print Client

## 🖨️ What Gets Printed

| Order Type | When It Prints | Where |
|------------|----------------|-------|
| Kitchen Order (KOT) | When customer orders food | Kitchen Printer |
| Bar Order (BOT) | When customer orders drinks | Bar Printer |
| Receipt | When payment is completed | Receipt Printer |

---

# PART 3: TROUBLESHOOTING

## Problem: "Python is not recognized"

**Solution:**
1. Uninstall Python
2. Download Python again from python.org
3. When installing, CHECK ☑️ "Add Python to PATH"
4. Install again

## Problem: "Cannot connect to server"

**Solution:**
1. Check your internet connection
2. Try opening https://hospitality.easyfixsoft.com in browser
3. If website works, restart Print Client

## Problem: "Authentication failed"

**Solution:**
1. Log in to admin panel
2. Go to Printer Settings
3. Copy the token again
4. Update config.json with correct token
5. Save and restart Print Client

## Problem: "No printer detected"

**Solution:**
1. Check printer is turned ON
2. Check USB cable is connected
3. Unplug USB and plug back in
4. Check printer appears in Windows "Devices and Printers"

## Problem: Orders not printing

**Solution:**
1. Make sure black window (Print Client) is open
2. Check for error messages in the window
3. Restart Print Client
4. Check printer has paper

---

# PART 4: QUICK REFERENCE CARD

## Your Information (Fill In):

| Item | Your Value |
|------|------------|
| Website | https://hospitality.easyfixsoft.com |
| Your Username | _________________________ |
| Your Password | _________________________ |
| Your Token | _________________________ |
| Printer Name | _________________________ |

## Quick Commands:

| Action | What to Do |
|--------|------------|
| Start Printing | Double-click `start_print_client.bat` |
| Stop Printing | Close the black window or press Ctrl+C |
| Get New Token | Admin Panel → Printer Settings → Regenerate |

## Support Contact:

- Email: ___________________________
- Phone: ___________________________

---

# PART 5: SETUP CHECKLIST

Use this checklist when setting up:

- [ ] Python installed (with PATH checked)
- [ ] print_client folder copied to C:\PrintClient
- [ ] `pip install requests pywin32` completed
- [ ] Logged into admin panel
- [ ] Token copied from Printer Settings
- [ ] config.json updated with token
- [ ] Printer connected and turned on
- [ ] Print Client started successfully
- [ ] Test order printed successfully

---

**🎉 Congratulations! Your restaurant is now set up for automatic order printing!**

---

© 2025 Easy-Fix Hospitality - All Rights Reserved

# 🖨️ Print Client Setup Guide for Restaurant
## Easy-Fix Hospitality - Automatic Order Printing

---

## What This Does
When customers place orders on your website, this program automatically prints:
- **Kitchen Order Tickets (KOT)** - for the kitchen
- **Bar Order Tickets (BOT)** - for the bar
- **Receipts** - for customers

---

## Requirements
1. Windows PC (Windows 10 or 11)
2. Thermal receipt printer (connected via USB)
3. Internet connection

---

## Step 1: Install Python

1. Go to: **https://www.python.org/downloads/**
2. Click the big yellow button **"Download Python 3.x.x"**
3. Run the downloaded file
4. ⚠️ **IMPORTANT:** Check the box ☑️ **"Add Python to PATH"** at the bottom
5. Click **"Install Now"**
6. Wait for installation to complete
7. Click **"Close"**

---

## Step 2: Copy Print Client Folder

1. Copy the entire **print_client** folder to your computer
2. Put it somewhere easy to find, like: `C:\PrintClient`

The folder should contain these files:
- `print_client.py`
- `config.json`
- `start_print_client.bat`
- `README.md`

---

## Step 3: Install Required Packages

1. Open **Command Prompt**:
   - Press `Windows key + R`
   - Type `cmd` and press Enter

2. Type this command and press Enter:
```
pip install requests pywin32
```

3. Wait for it to finish (you'll see "Successfully installed...")

---

## Step 4: Connect Your Printer

1. Connect your thermal printer to the computer via USB
2. Turn on the printer
3. Make sure Windows recognizes it (you should see it in Devices and Printers)

---

## Step 5: Start the Print Client

**Option A: Double-click start_print_client.bat**

OR

**Option B: Run manually**
1. Open Command Prompt
2. Navigate to the print_client folder:
```
cd C:\PrintClient
```
3. Run:
```
python print_client.py
```

---

## Step 6: Verify It's Working

You should see:
```
╔═══════════════════════════════════════════════════════════╗
║   Restaurant Print Client - Thermal Printer Service       ║
╚═══════════════════════════════════════════════════════════╝

Print Client Started
Server: https://hospitality.easyfixsoft.com
Printer: [Your Printer Name]
Poll Interval: 5 seconds
```

---

## Step 7: Keep It Running

- **Leave the black window open** while the restaurant is operating
- The program checks for new orders every 5 seconds
- When a new order comes in, it prints automatically!

---

## Starting Each Day

Every day when you open the restaurant:
1. Turn on the computer
2. Turn on the printer
3. Double-click **start_print_client.bat**
4. Leave it running all day

---

## Troubleshooting

### "Python is not recognized"
- Reinstall Python and make sure to check "Add Python to PATH"

### "Cannot connect to server"
- Check your internet connection
- Make sure the website https://hospitality.easyfixsoft.com is working

### "Authentication failed"
- Contact support - your API token may need to be regenerated

### Printer not detected
- Make sure printer is turned on and connected via USB
- Try unplugging and plugging it back in
- Check if Windows sees the printer in "Devices and Printers"

### Orders not printing
1. Make sure the Print Client window is open and running
2. Check if there are any error messages in the window
3. Try restarting the Print Client

---

## Support Contact

If you have any issues, contact:
- Email: [Your Support Email]
- Phone: [Your Support Phone]

---

## Configuration File (config.json)

Your config.json file contains:
```json
{
    "server_url": "https://hospitality.easyfixsoft.com",
    "api_token": "YOUR_TOKEN_HERE",
    "poll_interval": 5,
    "auto_detect_printer": true
}
```

**Do not share your API token with anyone!**

---

© 2025 Easy-Fix Hospitality

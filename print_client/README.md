# Restaurant Print Client

This Windows application runs on your restaurant's local computer and automatically prints orders and receipts from the server to your thermal printer.

## Features

✅ **Auto-detect thermal printers** - Automatically finds your RETSOL TP806 or other thermal printers  
✅ **Real-time printing** - Polls server every 5 seconds for new print jobs  
✅ **Automatic retry** - Failed jobs are retried automatically  
✅ **Error logging** - All activity logged to files for troubleshooting  
✅ **Multi-restaurant support** - Each restaurant uses their own API token  

## System Requirements

- **Operating System**: Windows 7/8/10/11
- **Python**: 3.8 or higher
- **Thermal Printer**: Connected via USB or network
- **Internet**: Connection to your hosted server

## Installation

### Step 1: Install Python

1. Download Python from: https://www.python.org/downloads/
2. Run installer and **CHECK "Add Python to PATH"**
3. Click "Install Now"
4. Verify: Open Command Prompt and type `python --version`

### Step 2: Install Dependencies

Open Command Prompt in the `print_client` folder and run:

```powershell
pip install requests pywin32
```

### Step 3: Configure Settings

1. Copy `config.json.example` to `config.json`
2. Edit `config.json` with your settings:

```json
{
    "server_url": "https://hospitality.easyfixsoft.com",
    "api_token": "YOUR_API_TOKEN_HERE",
    "poll_interval": 5,
    "printer_name": null,
    "auto_detect_printer": true
}
```

**Configuration Options:**

- `server_url` - Your hosted server URL (e.g., `https://hospitality.easyfixsoft.com`)
- `api_token` - API authentication token (get from Printer Settings page)
- `poll_interval` - How often to check for new jobs (seconds)
- `printer_name` - Specific printer name (or `null` for auto-detect)
- `auto_detect_printer` - Automatically find thermal printer (recommended)

### Step 4: Get Your API Token

1. Log in to your restaurant dashboard
2. Go to **Admin Panel** → **Printer Settings**
3. Copy the **API Token** shown on the page
4. Paste the token into your `config.json`

**API Endpoint:** `https://hospitality.easyfixsoft.com/orders/api/print-jobs/pending/`

## Running the Print Client

### Manual Start (Testing)

1. Open Command Prompt in `print_client` folder
2. Run: `python print_client.py`
3. Check output for "Print Client Started"

You should see:

```
╔═══════════════════════════════════════════════════════════╗
║   Restaurant Print Client - Thermal Printer Service      ║
╚═══════════════════════════════════════════════════════════╝

Available Printers:
  1. RETSOL TP806
  2. Microsoft Print to PDF

Selected Printer: RETSOL TP806

============================================================
Print Client Started
Server: https://yourserver.com
Printer: RETSOL TP806
Poll Interval: 5 seconds
============================================================
```

### Auto-Start on Windows Boot (Recommended)

**Option 1: Task Scheduler (Simple)**

1. Press `Win + R`, type `taskschd.msc`, press Enter
2. Click **Create Basic Task**
3. Name: "Restaurant Print Client"
4. Trigger: **When the computer starts**
5. Action: **Start a program**
6. Program: `C:\Python\python.exe`
7. Arguments: `C:\path\to\print_client.py`
8. Start in: `C:\path\to\print_client`
9. Check **Run whether user is logged on or not**
10. Finish

**Option 2: Startup Folder (Easier)**

1. Press `Win + R`, type `shell:startup`, press Enter
2. Create shortcut to `print_client.py`
3. Edit shortcut properties:
   - Target: `C:\Python\python.exe C:\path\to\print_client.py`
   - Start in: `C:\path\to\print_client`

## Troubleshooting

### "Cannot connect to server"

- Check `server_url` in config.json
- Verify internet connection
- Ping server: `ping yourserver.com`

### "Authentication failed"

- Check `api_token` in config.json
- Regenerate token from admin panel
- Ensure no extra spaces in token

### "No thermal printer detected"

- Check printer is connected and powered on
- Verify printer drivers installed
- Set `printer_name` manually in config.json
- List printers: `python -c "import win32print; print(win32print.EnumPrinters(2))"`

### "Print error"

- Check printer paper
- Verify printer is not in error state
- Try test print from Windows
- Check printer properties in Control Panel

### View Logs

Logs are saved to `print_client/logs/` folder:

```powershell
cd logs
type print_client_20250614.log
```

## Testing

### Test Print from Server

1. Log in to cashier panel
2. Create test order
3. Check print client console - should show:
   ```
   Retrieved 1 pending job(s)
   Processing job #123 (kot)
   ✓ Job #123 completed successfully
   ```

### Check Print Queue

View pending jobs in admin panel:
- Go to **Admin** → **Print Jobs**
- Filter by Status: **Pending**
- Should see jobs waiting to be printed

## Support

- **Logs**: Check `logs/` folder for detailed error messages
- **Printer Issues**: Contact printer manufacturer support
- **Server Issues**: Contact system administrator
- **Software Issues**: Check GitHub repository

## Advanced Configuration

### Use Specific Printer

```json
{
    "printer_name": "RETSOL TP806",
    "auto_detect_printer": false
}
```

### Change Poll Frequency

```json
{
    "poll_interval": 3
}
```
(Check every 3 seconds instead of 5)

### Multiple Restaurants (Same Computer)

Run separate instances:

1. Create folders: `restaurant1/`, `restaurant2/`
2. Copy `print_client.py` to each folder
3. Create separate `config.json` with different API tokens
4. Run each instance separately

## Security Notes

- **Protect config.json** - Contains your API token
- **HTTPS Only** - Use SSL for server connection (recommended)
- **Firewall** - Allow print client through Windows Firewall
- **Token Rotation** - Regenerate tokens periodically

## Updates

To update print client:

1. Backup `config.json`
2. Download new `print_client.py`
3. Replace old file
4. Restore `config.json`
5. Restart print client

---

**Version**: 1.0.0  
**Author**: Restaurant Ordering System  
**License**: Proprietary

1. Install Python (manual - from website)
        ↓
2. Run SETUP.bat (automatic - installs packages + gets token)
        ↓
3. Run start_print_client.bat (every day - starts printing)
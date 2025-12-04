"""
Windows Print Client for Restaurant Ordering System
====================================================

This application runs on the restaurant's local computer and:
1. Polls the server for pending print jobs
2. Downloads print content
3. Prints to the local thermal printer
4. Reports success/failure back to the server

Setup Instructions:
1. Install dependencies: pip install requests
2. Configure settings in config.json
3. Run: python print_client.py
4. Or install as Windows service (see service_installer.py)
"""

import os
import sys
import time
import json
import logging
import requests
import win32print  # type: ignore
import win32ui  # type: ignore
from datetime import datetime
from typing import Optional, Dict, Any


# Configure logging
LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, f'print_client_{datetime.now().strftime("%Y%m%d")}.log')),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('PrintClient')


class PrintClientConfig:
    """Configuration manager for print client"""
    
    def __init__(self, config_file='config.json'):
        self.config_file = os.path.join(os.path.dirname(__file__), config_file)
        self.config = self.load_config()
    
    def load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file"""
        if not os.path.exists(self.config_file):
            # Create default config
            default_config = {
                "server_url": "http://localhost:8000",
                "api_token": "YOUR_API_TOKEN_HERE",
                "restaurant_id": None,
                "poll_interval": 5,
                "printer_name": None,
                "auto_detect_printer": True,
                "retry_failed_jobs": True,
                "max_retries": 3
            }
            self.save_config(default_config)
            logger.warning(f"Created default config at {self.config_file}")
            logger.warning("Please edit config.json with your server URL and API token")
            return default_config
        
        with open(self.config_file, 'r') as f:
            return json.load(f)
    
    def save_config(self, config: Dict[str, Any]):
        """Save configuration to JSON file"""
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=4)
    
    def get(self, key: str, default=None):
        """Get configuration value"""
        return self.config.get(key, default)


class ThermalPrinter:
    """Handles printing to thermal printer"""
    
    def __init__(self, printer_name: Optional[str] = None, auto_detect: bool = True):
        self.printer_name = printer_name
        self.auto_detect = auto_detect
        
        if auto_detect and not printer_name:
            self.printer_name = self.detect_printer()
        elif not printer_name:
            self.printer_name = win32print.GetDefaultPrinter()
        
        logger.info(f"Using printer: {self.printer_name}")
    
    def detect_printer(self) -> str:
        """Auto-detect thermal printer"""
        printers = [printer[2] for printer in win32print.EnumPrinters(2)]
        
        # Common thermal printer keywords
        thermal_keywords = ['thermal', 'pos', 'receipt', 'retsol', 'tp806', 'xprinter', 'epson tm']
        
        for printer in printers:
            printer_lower = printer.lower()
            if any(keyword in printer_lower for keyword in thermal_keywords):
                logger.info(f"Auto-detected thermal printer: {printer}")
                return printer
        
        # Fallback to default printer
        default = win32print.GetDefaultPrinter()
        logger.warning(f"No thermal printer detected, using default: {default}")
        return default
    
    def get_available_printers(self) -> list:
        """Get list of available printers"""
        return [printer[2] for printer in win32print.EnumPrinters(2)]
    
    def print_text(self, content: str) -> bool:
        """Print text content to thermal printer"""
        try:
            # Open printer
            hprinter = win32print.OpenPrinter(self.printer_name)
            
            try:
                # Start print job
                job_info = ("Print Job", None, "RAW")
                job_id = win32print.StartDocPrinter(hprinter, 1, job_info)
                
                try:
                    win32print.StartPagePrinter(hprinter)
                    
                    # Convert content to bytes (CP437 encoding for thermal printers)
                    content_bytes = content.encode('cp437', errors='replace')
                    
                    # Send to printer
                    win32print.WritePrinter(hprinter, content_bytes)
                    
                    win32print.EndPagePrinter(hprinter)
                    logger.info(f"Print job sent successfully (Job ID: {job_id})")
                    return True
                    
                finally:
                    win32print.EndDocPrinter(hprinter)
            finally:
                win32print.ClosePrinter(hprinter)
                
        except Exception as e:
            logger.error(f"Print error: {str(e)}")
            return False


class PrintClient:
    """Main print client application"""
    
    def __init__(self, config: PrintClientConfig):
        self.config = config
        self.server_url = config.get('server_url')
        self.api_token = config.get('api_token')
        self.poll_interval = config.get('poll_interval', 5)
        self.running = False
        
        # Initialize printer
        self.printer = ThermalPrinter(
            printer_name=config.get('printer_name'),
            auto_detect=config.get('auto_detect_printer', True)
        )
        
        # Setup session with authentication
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Token {self.api_token}',
            'Content-Type': 'application/json'
        })
    
    def get_pending_jobs(self) -> list:
        """Fetch pending print jobs from server"""
        try:
            url = f"{self.server_url}/orders/api/print-jobs/pending/"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 200:
                jobs = response.json()
                if jobs:
                    logger.info(f"Retrieved {len(jobs)} pending job(s)")
                return jobs
            elif response.status_code == 401:
                logger.error("Authentication failed. Check API token in config.json")
                return []
            else:
                logger.error(f"Failed to fetch jobs: {response.status_code}")
                return []
                
        except requests.exceptions.ConnectionError:
            logger.error(f"Cannot connect to server: {self.server_url}")
            return []
        except Exception as e:
            logger.error(f"Error fetching jobs: {str(e)}")
            return []
    
    def mark_job_printing(self, job_id: int) -> bool:
        """Mark job as printing"""
        try:
            url = f"{self.server_url}/orders/api/print-jobs/{job_id}/start_printing/"
            response = self.session.post(url, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error marking job {job_id} as printing: {str(e)}")
            return False
    
    def mark_job_completed(self, job_id: int) -> bool:
        """Mark job as completed"""
        try:
            url = f"{self.server_url}/orders/api/print-jobs/{job_id}/mark_completed/"
            response = self.session.post(url, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error marking job {job_id} as completed: {str(e)}")
            return False
    
    def mark_job_failed(self, job_id: int, error_message: str) -> bool:
        """Mark job as failed"""
        try:
            url = f"{self.server_url}/orders/api/print-jobs/{job_id}/mark_failed/"
            data = {'error_message': error_message}
            response = self.session.post(url, json=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error marking job {job_id} as failed: {str(e)}")
            return False
    
    def process_job(self, job: Dict[str, Any]) -> bool:
        """Process a single print job"""
        job_id = job.get('id')
        job_type = job.get('job_type')
        content = job.get('content')
        
        logger.info(f"Processing job #{job_id} ({job_type})")
        
        # Mark as printing
        if not self.mark_job_printing(job_id):
            logger.warning(f"Failed to mark job #{job_id} as printing, continuing anyway")
        
        # Print content
        success = self.printer.print_text(content)
        
        # Mark result
        if success:
            self.mark_job_completed(job_id)
            logger.info(f"✓ Job #{job_id} completed successfully")
            return True
        else:
            self.mark_job_failed(job_id, "Print error")
            logger.error(f"✗ Job #{job_id} failed to print")
            return False
    
    def run(self):
        """Main loop - poll and process jobs"""
        logger.info("=" * 60)
        logger.info("Print Client Started")
        logger.info(f"Server: {self.server_url}")
        logger.info(f"Printer: {self.printer.printer_name}")
        logger.info(f"Poll Interval: {self.poll_interval} seconds")
        logger.info("=" * 60)
        
        self.running = True
        
        try:
            while self.running:
                try:
                    # Fetch pending jobs
                    jobs = self.get_pending_jobs()
                    
                    # Process each job
                    for job in jobs:
                        if not self.running:
                            break
                        self.process_job(job)
                    
                    # Wait before next poll
                    time.sleep(self.poll_interval)
                    
                except KeyboardInterrupt:
                    logger.info("Received shutdown signal")
                    break
                except Exception as e:
                    logger.error(f"Error in main loop: {str(e)}")
                    time.sleep(self.poll_interval)
                    
        finally:
            self.running = False
            logger.info("Print Client Stopped")
    
    def stop(self):
        """Stop the print client"""
        self.running = False


def main():
    """Main entry point"""
    print("""
╔═══════════════════════════════════════════════════════════╗
║   Restaurant Print Client - Thermal Printer Service      ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Load configuration
    config = PrintClientConfig()
    
    # Check if config is valid
    if config.get('api_token') == 'YOUR_API_TOKEN_HERE':
        print("⚠ ERROR: Please configure your API token in config.json")
        print(f"Config file location: {config.config_file}")
        input("\nPress Enter to exit...")
        return
    
    # Show available printers
    printer = ThermalPrinter()
    printers = printer.get_available_printers()
    print("\nAvailable Printers:")
    for i, p in enumerate(printers, 1):
        print(f"  {i}. {p}")
    print(f"\nSelected Printer: {printer.printer_name}")
    print()
    
    # Create and run client
    client = PrintClient(config)
    
    try:
        client.run()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        client.stop()


if __name__ == '__main__':
    main()

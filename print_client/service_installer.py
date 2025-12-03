"""
Windows Service Installer for Print Client
===========================================

This script installs the print client as a Windows service
so it runs automatically on system startup.

Usage:
    Install:   python service_installer.py install
    Start:     python service_installer.py start
    Stop:      python service_installer.py stop
    Remove:    python service_installer.py remove
    
Note: Must run as Administrator
"""

import os
import sys
import win32serviceutil  # type: ignore
import win32service  # type: ignore
import win32event  # type: ignore
import servicemanager  # type: ignore
from print_client import PrintClient, PrintClientConfig, logger


class PrintClientService(win32serviceutil.ServiceFramework):
    """Windows Service for Print Client"""
    
    _svc_name_ = "RestaurantPrintClient"
    _svc_display_name_ = "Restaurant Print Client Service"
    _svc_description_ = "Automatic thermal printer service for restaurant orders and receipts"
    
    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.client = None
    
    def SvcStop(self):
        """Stop the service"""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        if self.client:
            self.client.stop()
        logger.info("Service stop requested")
    
    def SvcDoRun(self):
        """Run the service"""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        logger.info("Service started")
        
        try:
            # Load config and start client
            config = PrintClientConfig()
            self.client = PrintClient(config)
            
            # Run until stop event
            self.client.run()
            
        except Exception as e:
            logger.error(f"Service error: {str(e)}")
            servicemanager.LogErrorMsg(f"Service error: {str(e)}")


def main():
    """Main entry point for service installer"""
    if len(sys.argv) == 1:
        # No arguments - show usage
        print(__doc__)
        print("\nService Management Commands:")
        print("  python service_installer.py install   - Install as Windows service")
        print("  python service_installer.py start     - Start the service")
        print("  python service_installer.py stop      - Stop the service")
        print("  python service_installer.py restart   - Restart the service")
        print("  python service_installer.py remove    - Remove the service")
        print("\nNote: Must run as Administrator")
        return
    
    try:
        win32serviceutil.HandleCommandLine(PrintClientService)
    except Exception as e:
        print(f"Error: {str(e)}")
        print("\nMake sure you are running as Administrator")
        print("Right-click Command Prompt and select 'Run as Administrator'")


if __name__ == '__main__':
    main()

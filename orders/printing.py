"""
Server-side printing module for automatic KOT/BOT printing
Prints directly to thermal printer without browser dialog
"""

import sys
import platform
import logging

# Initialize logger for printing module
logger = logging.getLogger(__name__)

# Windows-only imports - only import on Windows
if platform.system() == 'Windows':
    try:
        import win32print  # type: ignore
        import win32ui  # type: ignore
        import win32con  # type: ignore
        WINDOWS_PRINTING_AVAILABLE = True
    except ImportError:
        WINDOWS_PRINTING_AVAILABLE = False
        win32print = None
        win32ui = None
        win32con = None
else:
    # Linux/Mac - Windows printing not available
    WINDOWS_PRINTING_AVAILABLE = False
    win32print = None
    win32ui = None
    win32con = None

from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from django.template.loader import render_to_string
from django.utils import timezone
from django.db.models import Sum
from decimal import Decimal
import textwrap


def get_restaurant_display_name(order):
    """
    Get restaurant name for printing - unified function.
    Handles both Restaurant model (for branches) and User model (legacy).
    Avoids duplicate database queries.
    
    Args:
        order: Order instance
    
    Returns:
        str: Restaurant name to display on prints
    """
    table = order.table_info
    
    # Prefer Restaurant model (for branches)
    if hasattr(table, 'restaurant') and table.restaurant:
        restaurant = table.restaurant
        # For branches, show main restaurant name
        if not restaurant.is_main_restaurant and restaurant.parent_restaurant:
            return restaurant.parent_restaurant.name
        return restaurant.name
    
    # Fallback to User model (legacy)
    if table.owner:
        # For branch owners using User model, try to find parent restaurant
        if table.owner.role and table.owner.role.name == 'branch_owner':
            try:
                from restaurant.models_restaurant import Restaurant
                branch_restaurant = Restaurant.objects.filter(
                    branch_owner=table.owner, 
                    is_main_restaurant=False
                ).first()
                if branch_restaurant and branch_restaurant.parent_restaurant:
                    return branch_restaurant.parent_restaurant.name
            except Exception:
                pass
        
        return table.owner.restaurant_name or "Restaurant"
    
    return "Restaurant"


def get_restaurant_print_settings(order):
    """
    Get printer settings for an order.
    Checks Restaurant model first (for branches), then falls back to User (owner).
    Each restaurant/branch can have independent printer settings.
    
    Args:
        order: Order instance
    
    Returns:
        dict: Printer settings including auto_print flags and printer names
    """
    table = order.table_info
    
    def normalize_printer_name(name):
        """Normalize printer name - return None for empty/invalid values"""
        if name is None or name == '' or name == 'None' or name.strip() == '':
            return None
        return name.strip()
    
    # First, try to get settings from Restaurant model (preferred for branches)
    if hasattr(table, 'restaurant') and table.restaurant:
        restaurant = table.restaurant
        return {
            'source': 'restaurant',
            'name': restaurant.name,
            'auto_print_kot': restaurant.auto_print_kot,
            'auto_print_bot': restaurant.auto_print_bot,
            'auto_print_buffet': getattr(restaurant, 'auto_print_buffet', False),
            'auto_print_service': getattr(restaurant, 'auto_print_service', False),
            'kitchen_printer_name': normalize_printer_name(restaurant.kitchen_printer_name),
            'bar_printer_name': normalize_printer_name(restaurant.bar_printer_name),
            'buffet_printer_name': normalize_printer_name(getattr(restaurant, 'buffet_printer_name', None)),
            'service_printer_name': normalize_printer_name(getattr(restaurant, 'service_printer_name', None)),
            'receipt_printer_name': normalize_printer_name(restaurant.receipt_printer_name),
            'restaurant_obj': restaurant,
            'owner': restaurant.branch_owner or restaurant.main_owner,
        }
    
    # Fallback to User (owner) settings
    owner = table.owner
    if owner:
        return {
            'source': 'owner',
            'name': owner.restaurant_name,
            'auto_print_kot': owner.auto_print_kot,
            'auto_print_bot': owner.auto_print_bot,
            'auto_print_buffet': getattr(owner, 'auto_print_buffet', False),
            'auto_print_service': getattr(owner, 'auto_print_service', False),
            'kitchen_printer_name': normalize_printer_name(owner.kitchen_printer_name),
            'bar_printer_name': normalize_printer_name(owner.bar_printer_name),
            'buffet_printer_name': normalize_printer_name(getattr(owner, 'buffet_printer_name', None)),
            'service_printer_name': normalize_printer_name(getattr(owner, 'service_printer_name', None)),
            'receipt_printer_name': normalize_printer_name(owner.receipt_printer_name),
            'restaurant_obj': None,
            'owner': owner,
        }
    
    # No settings found
    return {
        'source': None,
        'name': 'Unknown',
        'auto_print_kot': False,
        'auto_print_bot': False,
        'auto_print_buffet': False,
        'auto_print_service': False,
        'kitchen_printer_name': None,
        'bar_printer_name': None,
        'buffet_printer_name': None,
        'service_printer_name': None,
        'receipt_printer_name': None,
        'restaurant_obj': None,
        'owner': None,
    }


def create_print_job(restaurant, job_type, content, order=None, payment=None, printer_name=None):
    """
    Create a print job for remote printing
    Used when server is hosted and printer is on restaurant's local computer
    """
    from .models_printjob import PrintJob
    
    job = PrintJob.objects.create(
        restaurant=restaurant,
        job_type=job_type,
        content=content,
        order=order,
        payment=payment,
        printer_name=printer_name,
        status='pending'
    )
    
    restaurant_name = getattr(restaurant, 'restaurant_name', 'Unknown')
    logger.info(f" Created print job #{job.id} ({job_type}) for {restaurant_name} (printer: {printer_name or 'auto-detect'})")
    return job


class ThermalPrinter:
    """
    Direct thermal printer interface for Windows
    Automatically prints to default printer without user interaction
    NOTE: This class only works on Windows. On Linux/Mac, use the print queue system.
    """
    
    def __init__(self, printer_name=None):
        """
        Initialize printer
        
        Args:
            printer_name: Specific printer name, or None for auto-detection
        """
        if not WINDOWS_PRINTING_AVAILABLE:
            logger.warning(" Windows printing not available on this platform. Use print queue instead.")
            self.printer_name = None
            return
            
        if printer_name is None:
            # Auto-detect thermal printer
            self.printer_name = self._find_thermal_printer()
        else:
            self.printer_name = printer_name
    
    def _printer_exists(self, printer_name):
        """
        Check if a printer exists and can be opened
        
        Args:
            printer_name: Name of the printer to check
            
        Returns:
            bool: True if printer exists, False otherwise
        """
        if not printer_name or not WINDOWS_PRINTING_AVAILABLE:
            return False
        try:
            hPrinter = win32print.OpenPrinter(printer_name)
            win32print.ClosePrinter(hPrinter)
            return True
        except Exception as e:
            logger.error(f" Printer '{printer_name}' not found: {e}")
            return False
    
    def _get_printer_status(self, printer_name):
        """
        Get printer status code
        
        Args:
            printer_name: Name of the printer
            
        Returns:
            tuple: (status_code, status_text)
        """
        try:
            hPrinter = win32print.OpenPrinter(printer_name)
            try:
                printer_info = win32print.GetPrinter(hPrinter, 2)
                status = printer_info.get('Status', 0)
                
                # Status text for common codes
                status_texts = {
                    0: 'Ready',
                    1: 'Paused',
                    2: 'Error (may still work)',
                    128: 'Offline',
                    512: 'Busy',
                    1024: 'Printing',
                    8192: 'Waiting',
                    16384: 'Processing'
                }
                status_text = status_texts.get(status, f'Unknown ({status})')
                return status, status_text
            finally:
                win32print.ClosePrinter(hPrinter)
        except Exception as e:
            return -1, f'Error: {e}'
    
    def _is_printer_ready(self, printer_name):
        """
        Check if a printer is online and ready to print.
        NOTE: Many thermal printers report non-zero status even when working!
        Status 2 (Error) is common for cheap POS printers that work fine.
        
        Args:
            printer_name: Name of the printer to check
            
        Returns:
            bool: True if printer is likely ready, False if definitely not
        """
        try:
            hPrinter = win32print.OpenPrinter(printer_name)
            try:
                printer_info = win32print.GetPrinter(hPrinter, 2)
                status = printer_info.get('Status', 0)
                
                # CRITICAL STATUSES that mean printer definitely won't work:
                # 128 = Offline (disconnected)
                # 4096 = Not available
                # 8388608 = Server unknown
                critical_errors = [128, 4096, 8388608]
                
                # If printer has critical error, it's NOT ready
                if status in critical_errors:
                    logger.error(f" Printer '{printer_name}' is OFFLINE/UNAVAILABLE (status: {status})")
                    return False
                
                # For ALL other statuses (including 0=Ready, 2=Error, etc), consider it READY
                # Many thermal printers report status 2 even when working perfectly!
                if status == 0:
                    logger.info(f" Printer '{printer_name}' is READY (status: {status})")
                else:
                    logger.warning(f" Printer '{printer_name}' status={status} (will try anyway - many printers report errors when working)")
                
                return True
                
            finally:
                win32print.ClosePrinter(hPrinter)
                
        except Exception as e:
            logger.error(f" Cannot open printer '{printer_name}': {e}")
            return False
    
    def _find_thermal_printer(self):
        """
        Automatically find thermal printer that is ONLINE and READY
        Prioritizes: 
        1. Windows default printer (if it's a thermal printer and ready)
        2. Any other connected thermal printer that is ready
        3. Windows default printer as fallback
        
        Returns:
            str: Printer name
        """
        if not WINDOWS_PRINTING_AVAILABLE:
            return None
        
        # Extended list of thermal printer keywords (case-insensitive)
        thermal_keywords = [
            'POS', 'THERMAL', 'RECEIPT', 
            # Retsol models
            'RETSOL', 'TP806', 'TP80', 'TP58',
            # Epson models
            'EPSON', 'TM-T', 'TM-U', 'TM-M', 'TM-P',
            # Star Micronics
            'STAR', 'TSP', 'SP700', 'SM-',
            # Bixolon
            'BIXOLON', 'SRP-', 'SPP-',
            # Citizen
            'CITIZEN', 'CT-S', 'CT-E',
            # Other common brands
            'ZEBRA', 'ZD', 'ZT',
            'XPRINTER', 'XP-',
            'RONGTA', 'RP-',
            '80MM', '58MM',
            'GOOJPRT',
            'MUNBYN',
            'HOIN',
            'NETUM',
            'ISSYZONEPOS'
        ]
        
        logger.info("Searching for thermal printers...")
        
        # Get Windows default printer first
        default_printer = win32print.GetDefaultPrinter()
        logger.info(f"  Windows default printer: {default_printer}")
        
        # Get all local printers
        all_printers = []
        for printer_info in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL):
            all_printers.append(printer_info[2])
        
        logger.info(f"  Found {len(all_printers)} printer(s) installed")
        
        # Find ALL thermal printers (don't filter by status - they all work!)
        thermal_printers = []
        for printer in all_printers:
            printer_upper = printer.upper()
            is_thermal = any(keyword in printer_upper for keyword in thermal_keywords)
            
            if is_thermal:
                # Check if printer exists and can be opened
                if self._printer_exists(printer):
                    thermal_printers.append(printer)
                    logger.info(f" Found thermal printer: {printer}")
        
        # Check if Windows default is thermal - if so, use it
        default_upper = default_printer.upper()
        is_default_thermal = any(keyword in default_upper for keyword in thermal_keywords)
        
        if is_default_thermal and default_printer in thermal_printers:
            logger.info(f" Using Windows default thermal printer: {default_printer}")
            return default_printer
        
        # Use first available thermal printer
        if thermal_printers:
            selected = thermal_printers[0]
            logger.info(f" Auto-detected thermal printer: {selected}")
            return selected
        
        # Fallback: Use Windows default printer
        logger.warning(f" No thermal printer found, using Windows default: {default_printer}")
        return default_printer
    
    def get_available_printers(self):
        """Get list of all available printers"""
        if not WINDOWS_PRINTING_AVAILABLE:
            return []
        printers = []
        for printer_info in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL):
            printers.append(printer_info[2])  # Printer name
        return printers
    
    def print_text(self, text_content, job_name="Print Job"):
        """
        Print plain text directly to thermal printer
        
        Args:
            text_content: Text to print
            job_name: Name of print job
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not WINDOWS_PRINTING_AVAILABLE:
            logger.warning(" Windows printing not available. Use print queue instead.")
            return False
            
        if self.printer_name is None:
            logger.warning(" No printer configured.")
            return False
            
        try:
            # Open printer
            hPrinter = win32print.OpenPrinter(self.printer_name)
            
            try:
                # Start print job
                hJob = win32print.StartDocPrinter(hPrinter, 1, (job_name, None, "RAW"))
                
                try:
                    win32print.StartPagePrinter(hPrinter)
                    
                    # Convert text to bytes
                    raw_data = text_content.encode('utf-8', errors='ignore')
                    
                    # Send to printer
                    win32print.WritePrinter(hPrinter, raw_data)
                    win32print.EndPagePrinter(hPrinter)
                    
                    logger.info(f" Printed to {self.printer_name}: {job_name}")
                    return True
                    
                finally:
                    win32print.EndDocPrinter(hPrinter)
            finally:
                win32print.ClosePrinter(hPrinter)
                
        except Exception as e:
            logger.error(f" Print Error: {str(e)}")
            return False
    
    def print_kot(self, order):
        """
        Print Kitchen Order Ticket directly to thermal printer
        Uses kitchen-specific printer from restaurant/branch settings
        ALWAYS tries configured printer first if it exists!
        
        Args:
            order: Order instance
        
        Returns:
            bool: Success status
        """
        try:
            # Get printer settings for this specific restaurant/branch
            print_settings = get_restaurant_print_settings(order)
            printer_name = print_settings['kitchen_printer_name']
            
            # Determine which printer to use
            if printer_name:
                # ALWAYS try configured printer if it EXISTS (don't check status - it's unreliable!)
                if self._printer_exists(printer_name):
                    printer = ThermalPrinter(printer_name=printer_name)
                    status, status_text = self._get_printer_status(printer_name)
                    logger.info(f" Using configured kitchen printer: {printer_name} (status: {status_text})")
                else:
                    # Configured printer doesn't exist at all, fall back to auto-detect
                    logger.warning(f" Configured printer '{printer_name}' not found, auto-detecting...")
                    printer = ThermalPrinter()  # Auto-detect
            else:
                # No printer configured, use auto-detected
                printer = self
            
            # Generate KOT content
            content = printer._generate_kot_content(order)
            
            # Print with ESC/POS commands for thermal printer
            thermal_content = printer._format_for_thermal(content, "KOT")
            
            # Send to printer
            return printer.print_text(thermal_content, f"KOT-{order.order_number}")
            
        except Exception as e:
            logger.error(f" KOT Print Error: {str(e)}", exc_info=True)
            return False
    
    def print_bot(self, order):
        """
        Print Bar Order Ticket directly to thermal printer
        Uses bar-specific printer from restaurant/branch settings
        ALWAYS tries configured printer first if it exists!
        
        Args:
            order: Order instance
        
        Returns:
            bool: Success status
        """
        try:
            # Get printer settings for this specific restaurant/branch
            print_settings = get_restaurant_print_settings(order)
            printer_name = print_settings['bar_printer_name']
            
            # Determine which printer to use
            if printer_name:
                # ALWAYS try configured printer if it EXISTS (don't check status - it's unreliable!)
                if self._printer_exists(printer_name):
                    printer = ThermalPrinter(printer_name=printer_name)
                    status, status_text = self._get_printer_status(printer_name)
                    logger.info(f" Using configured bar printer: {printer_name} (status: {status_text})")
                else:
                    # Configured printer doesn't exist at all, fall back to auto-detect
                    logger.warning(f" Configured printer '{printer_name}' not found, auto-detecting...")
                    printer = ThermalPrinter()  # Auto-detect
            else:
                # No printer configured, use auto-detected
                printer = self
            
            # Generate BOT content
            content = printer._generate_bot_content(order)
            
            # Print with ESC/POS commands for thermal printer
            thermal_content = printer._format_for_thermal(content, "BOT")
            
            # Send to printer
            return printer.print_text(thermal_content, f"BOT-{order.order_number}")
            
        except Exception as e:
            logger.error(f" BOT Print Error: {str(e)}", exc_info=True)
            return False
    
    def print_receipt(self, payment):
        """
        Print Receipt directly to thermal printer
        Uses receipt-specific printer from restaurant/branch settings
        ALWAYS tries configured printer first if it exists!
        
        Args:
            payment: Payment instance
        
        Returns:
            bool: Success status
        """
        try:
            # Get printer settings for this specific restaurant/branch
            print_settings = get_restaurant_print_settings(payment.order)
            printer_name = print_settings['receipt_printer_name']
            
            # Determine which printer to use
            if printer_name:
                # ALWAYS try configured printer if it EXISTS (don't check status - it's unreliable!)
                if self._printer_exists(printer_name):
                    printer = ThermalPrinter(printer_name=printer_name)
                    status, status_text = self._get_printer_status(printer_name)
                    logger.info(f" Using configured receipt printer: {printer_name} (status: {status_text})")
                else:
                    # Configured printer doesn't exist at all, fall back to auto-detect
                    logger.warning(f" Configured printer '{printer_name}' not found, auto-detecting...")
                    printer = ThermalPrinter()  # Auto-detect
            else:
                # No printer configured, use auto-detected
                printer = self
            
            # Generate receipt content
            content = _generate_receipt_content(payment)
            
            # Print with ESC/POS commands for thermal printer
            thermal_content = printer._format_for_thermal(content, "RECEIPT")
            
            # Send to printer
            return printer.print_text(thermal_content, f"Receipt-{payment.order.order_number}")
            
        except Exception as e:
            logger.error(f" Receipt Print Error: {str(e)}", exc_info=True)
            return False
    
    def print_buffet(self, order):
        """
        Print Buffet Order Ticket directly to thermal printer
        Uses buffet-specific printer from restaurant/branch settings
        ALWAYS tries configured printer first if it exists!
        
        Args:
            order: Order instance
        
        Returns:
            bool: Success status
        """
        try:
            # Get printer settings for this specific restaurant/branch
            print_settings = get_restaurant_print_settings(order)
            printer_name = print_settings.get('buffet_printer_name')
            
            # Determine which printer to use
            if printer_name:
                # ALWAYS try configured printer if it EXISTS (don't check status - it's unreliable!)
                if self._printer_exists(printer_name):
                    printer = ThermalPrinter(printer_name=printer_name)
                    status, status_text = self._get_printer_status(printer_name)
                    logger.info(f" Using configured buffet printer: {printer_name} (status: {status_text})")
                else:
                    # Configured printer doesn't exist at all, fall back to auto-detect
                    logger.warning(f" Configured printer '{printer_name}' not found, auto-detecting...")
                    printer = ThermalPrinter()  # Auto-detect
            else:
                # No printer configured, use auto-detected
                printer = self
            
            # Generate BUFFET content
            content = printer._generate_buffet_content(order)
            
            # Print with ESC/POS commands for thermal printer
            thermal_content = printer._format_for_thermal(content, "BUFFET")
            
            # Send to printer
            return printer.print_text(thermal_content, f"BUFFET-{order.order_number}")
            
        except Exception as e:
            logger.error(f" BUFFET Print Error: {str(e)}", exc_info=True)
            return False
    
    def print_service(self, order):
        """
        Print Service Order Ticket directly to thermal printer
        Uses service-specific printer from restaurant/branch settings
        ALWAYS tries configured printer first if it exists!
        
        Args:
            order: Order instance
        
        Returns:
            bool: Success status
        """
        try:
            # Get printer settings for this specific restaurant/branch
            print_settings = get_restaurant_print_settings(order)
            printer_name = print_settings.get('service_printer_name')
            
            # Determine which printer to use
            if printer_name:
                # ALWAYS try configured printer if it EXISTS (don't check status - it's unreliable!)
                if self._printer_exists(printer_name):
                    printer = ThermalPrinter(printer_name=printer_name)
                    status, status_text = self._get_printer_status(printer_name)
                    logger.info(f" Using configured service printer: {printer_name} (status: {status_text})")
                else:
                    # Configured printer doesn't exist at all, fall back to auto-detect
                    logger.warning(f" Configured printer '{printer_name}' not found, auto-detecting...")
                    printer = ThermalPrinter()  # Auto-detect
            else:
                # No printer configured, use auto-detected
                printer = self
            
            # Generate SERVICE content
            content = printer._generate_service_content(order)
            
            # Print with ESC/POS commands for thermal printer
            thermal_content = printer._format_for_thermal(content, "SERVICE")
            
            # Send to printer
            return printer.print_text(thermal_content, f"SERVICE-{order.order_number}")
            
        except Exception as e:
            logger.error(f" SERVICE Print Error: {str(e)}", exc_info=True)
            return False
    
    def _generate_kot_content(self, order):
        """Generate KOT text content"""
        lines = []
        width = 48  # 80mm thermal printer - full width utilization
        
        # Header
        lines.append("=" * width)
        lines.append("KITCHEN ORDER TICKET (KOT)".center(width))
        lines.append("=" * width)
        
        # Restaurant info - use unified function
        restaurant_name = get_restaurant_display_name(order)
        
        lines.append("")
        lines.append(f"Restaurant: {restaurant_name}")
        lines.append(f"Order #: {order.order_number}")
        lines.append(f"Table: {order.table_info.tbl_no}")
        lines.append(f"Time: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
        
        # Show who placed the order
        ordered_by = order.ordered_by
        if ordered_by:
            if hasattr(ordered_by, 'is_waiter') and ordered_by.is_waiter():
                role = "Waiter"
            elif hasattr(ordered_by, 'is_cashier') and ordered_by.is_cashier():
                role = "Cashier"
            elif hasattr(ordered_by, 'is_customer_care') and ordered_by.is_customer_care():
                role = "Customer Care"
            elif hasattr(ordered_by, 'is_owner') and ordered_by.is_owner():
                role = "Owner"
            elif hasattr(ordered_by, 'is_customer') and ordered_by.is_customer():
                role = "Customer"
            else:
                role = "Staff"
            
            full_name = f"{ordered_by.first_name} {ordered_by.last_name}".strip()
            if not full_name:
                full_name = ordered_by.username
            
            lines.append(f"Ordered by: {full_name} ({role})")
        
        lines.append("-" * width)
        
        # Kitchen items only
        lines.append("")
        lines.append("KITCHEN ITEMS:")
        lines.append("-" * width)
        
        kitchen_items = [item for item in order.order_items.all() if item.product.station == 'kitchen']
        
        for item in kitchen_items:
            # Item name and quantity - left aligned
            qty_text = f"{item.quantity}x"
            lines.append(f"{qty_text:4} {item.product.name}")
            
            # Special instructions if any
            if order.special_instructions:
                wrapped = textwrap.wrap(f"Note: {order.special_instructions}", width=width-6)
                for line in wrapped:
                    lines.append(f"     {line}")
        
        # Footer
        lines.append("-" * width)
        total_items = len(kitchen_items)
        total_qty = sum(item.quantity for item in kitchen_items)
        lines.append(f"Total Items: {total_items:>2}  |  Total Qty: {total_qty:>2}")
        lines.append("-" * width)
        lines.append("For kitchen preparation only".center(width))
        lines.append("NOT FOR BILLING".center(width))
        lines.append("=" * width)
        
        return "\n".join(lines)
    
    def _generate_bot_content(self, order):
        """Generate BOT text content"""
        lines = []
        width = 48  # 80mm thermal printer - full width utilization
        
        # Header
        lines.append("=" * width)
        lines.append("BAR ORDER TICKET (BOT)".center(width))
        lines.append("=" * width)
        
        # Restaurant info - use unified function
        restaurant_name = get_restaurant_display_name(order)
        
        lines.append("")
        lines.append(f"Restaurant: {restaurant_name}")
        lines.append(f"Order #: {order.order_number}")
        lines.append(f"Table: {order.table_info.tbl_no}")
        lines.append(f"Time: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
        
        # Show who placed the order
        ordered_by = order.ordered_by
        if ordered_by:
            if hasattr(ordered_by, 'is_waiter') and ordered_by.is_waiter():
                role = "Waiter"
            elif hasattr(ordered_by, 'is_cashier') and ordered_by.is_cashier():
                role = "Cashier"
            elif hasattr(ordered_by, 'is_customer_care') and ordered_by.is_customer_care():
                role = "Customer Care"
            elif hasattr(ordered_by, 'is_owner') and ordered_by.is_owner():
                role = "Owner"
            elif hasattr(ordered_by, 'is_customer') and ordered_by.is_customer():
                role = "Customer"
            else:
                role = "Staff"
            
            full_name = f"{ordered_by.first_name} {ordered_by.last_name}".strip()
            if not full_name:
                full_name = ordered_by.username
            
            lines.append(f"Ordered by: {full_name} ({role})")
        
        lines.append("-" * width)
        
        # Bar items only
        lines.append("")
        lines.append("BAR ITEMS:")
        lines.append("-" * width)
        
        bar_items = [item for item in order.order_items.all() if item.product.station == 'bar']
        
        for item in bar_items:
            # Item name and quantity - left aligned
            qty_text = f"{item.quantity}x"
            lines.append(f"{qty_text:4} {item.product.name}")
            
            # Special instructions if any
            if order.special_instructions:
                wrapped = textwrap.wrap(f"Note: {order.special_instructions}", width=width-6)
                for line in wrapped:
                    lines.append(f"     {line}")
        
        # Footer
        lines.append("-" * width)
        total_items = len(bar_items)
        total_qty = sum(item.quantity for item in bar_items)
        lines.append(f"Total Items: {total_items:>2}  |  Total Qty: {total_qty:>2}")
        lines.append("-" * width)
        lines.append("For bar preparation only".center(width))
        lines.append("NOT FOR BILLING".center(width))
        lines.append("=" * width)
        
        return "\n".join(lines)
    
    def _generate_buffet_content(self, order):
        """Generate BUFFET text content"""
        lines = []
        width = 48  # 80mm thermal printer - full width utilization
        
        # Header
        lines.append("=" * width)
        lines.append("BUFFET ORDER TICKET".center(width))
        lines.append("=" * width)
        
        # Restaurant info - use unified function
        restaurant_name = get_restaurant_display_name(order)
        
        lines.append("")
        lines.append(f"Restaurant: {restaurant_name}")
        lines.append(f"Order #: {order.order_number}")
        lines.append(f"Table: {order.table_info.tbl_no}")
        lines.append(f"Time: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
        
        # Show who placed the order
        ordered_by = order.ordered_by
        if ordered_by:
            if hasattr(ordered_by, 'is_waiter') and ordered_by.is_waiter():
                role = "Waiter"
            elif hasattr(ordered_by, 'is_cashier') and ordered_by.is_cashier():
                role = "Cashier"
            elif hasattr(ordered_by, 'is_customer_care') and ordered_by.is_customer_care():
                role = "Customer Care"
            elif hasattr(ordered_by, 'is_owner') and ordered_by.is_owner():
                role = "Owner"
            elif hasattr(ordered_by, 'is_customer') and ordered_by.is_customer():
                role = "Customer"
            else:
                role = "Staff"
            
            full_name = f"{ordered_by.first_name} {ordered_by.last_name}".strip()
            if not full_name:
                full_name = ordered_by.username
            
            lines.append(f"Ordered by: {full_name} ({role})")
        
        lines.append("-" * width)
        
        # Buffet items only
        lines.append("")
        lines.append("BUFFET ITEMS:")
        lines.append("-" * width)
        
        buffet_items = [item for item in order.order_items.all() if item.product.station == 'buffet']
        
        for item in buffet_items:
            # Item name and quantity - left aligned
            qty_text = f"{item.quantity}x"
            lines.append(f"{qty_text:4} {item.product.name}")
            
            # Special instructions if any
            if order.special_instructions:
                wrapped = textwrap.wrap(f"Note: {order.special_instructions}", width=width-6)
                for line in wrapped:
                    lines.append(f"     {line}")
        
        # Footer
        lines.append("-" * width)
        total_items = len(buffet_items)
        total_qty = sum(item.quantity for item in buffet_items)
        lines.append(f"Total Items: {total_items:>2}  |  Total Qty: {total_qty:>2}")
        lines.append("-" * width)
        lines.append("For buffet station only".center(width))
        lines.append("NOT FOR BILLING".center(width))
        lines.append("=" * width)
        
        return "\n".join(lines)
    
    def _generate_service_content(self, order):
        """Generate SERVICE text content"""
        lines = []
        width = 48  # 80mm thermal printer - full width utilization
        
        # Header
        lines.append("=" * width)
        lines.append("SERVICE ORDER TICKET".center(width))
        lines.append("=" * width)
        
        # Restaurant info - use unified function
        restaurant_name = get_restaurant_display_name(order)
        
        lines.append("")
        lines.append(f"Restaurant: {restaurant_name}")
        lines.append(f"Order #: {order.order_number}")
        lines.append(f"Table: {order.table_info.tbl_no}")
        lines.append(f"Time: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
        
        # Show who placed the order
        ordered_by = order.ordered_by
        if ordered_by:
            if hasattr(ordered_by, 'is_waiter') and ordered_by.is_waiter():
                role = "Waiter"
            elif hasattr(ordered_by, 'is_cashier') and ordered_by.is_cashier():
                role = "Cashier"
            elif hasattr(ordered_by, 'is_customer_care') and ordered_by.is_customer_care():
                role = "Customer Care"
            elif hasattr(ordered_by, 'is_owner') and ordered_by.is_owner():
                role = "Owner"
            elif hasattr(ordered_by, 'is_customer') and ordered_by.is_customer():
                role = "Customer"
            else:
                role = "Staff"
            
            full_name = f"{ordered_by.first_name} {ordered_by.last_name}".strip()
            if not full_name:
                full_name = ordered_by.username
            
            lines.append(f"Ordered by: {full_name} ({role})")
        
        lines.append("-" * width)
        
        # Service items only
        lines.append("")
        lines.append("SERVICE ITEMS:")
        lines.append("-" * width)
        
        service_items = [item for item in order.order_items.all() if item.product.station == 'service']
        
        for item in service_items:
            # Item name and quantity - left aligned
            qty_text = f"{item.quantity}x"
            lines.append(f"{qty_text:4} {item.product.name}")
            
            # Special instructions if any
            if order.special_instructions:
                wrapped = textwrap.wrap(f"Note: {order.special_instructions}", width=width-6)
                for line in wrapped:
                    lines.append(f"     {line}")
        
        # Footer
        lines.append("-" * width)
        total_items = len(service_items)
        total_qty = sum(item.quantity for item in service_items)
        lines.append(f"Total Items: {total_items:>2}  |  Total Qty: {total_qty:>2}")
        lines.append("-" * width)
        lines.append("For service station only".center(width))
        lines.append("NOT FOR BILLING".center(width))
        lines.append("=" * width)
        
        return "\n".join(lines)
    
    def _format_for_thermal(self, content, ticket_type):
        """
        Format content with ESC/POS commands for thermal printer
        
        Args:
            content: Text content
            ticket_type: "KOT", "BOT", or "RECEIPT"
        
        Returns:
            str: Formatted content with ESC/POS commands
        """
        # ESC/POS commands
        ESC = chr(27)
        INIT = ESC + '@'  # Initialize printer
        BOLD_ON = ESC + 'E' + chr(1)  # Bold on
        BOLD_OFF = ESC + 'E' + chr(0)  # Bold off
        CENTER = ESC + 'a' + chr(1)  # Center align
        LEFT = ESC + 'a' + chr(0)  # Left align
        CUT = chr(29) + 'V' + chr(66) + chr(0)  # Cut paper
        LARGE = ESC + '!' + chr(16)  # Large text
        NORMAL = ESC + '!' + chr(0)  # Normal text
        
        # Cash drawer kick command - ESC p m t1 t2
        # m=0 (pin 2), t1=25 (on time), t2=250 (off time)
        # This opens the cash drawer connected to the printer
        OPEN_DRAWER = ESC + chr(112) + chr(0) + chr(25) + chr(250)
        
        # Build formatted content
        formatted = INIT  # Initialize
        formatted += CENTER + LARGE + BOLD_ON
        formatted += f"\n{ticket_type}\n"
        formatted += BOLD_OFF + NORMAL + LEFT
        formatted += content
        formatted += "\n\n\n"  # Add spacing before cut
        formatted += CUT  # Cut paper
        
        # Open cash drawer for RECEIPT only (not KOT/BOT)
        if ticket_type == "RECEIPT":
            formatted += OPEN_DRAWER
        
        return formatted


def auto_print_order(order):
    """
    Automatically print KOT and/or BOT based on order items
    Supports both local printing (direct) and remote printing (queue)
    Each restaurant/branch uses its own independent printer settings.
    
    Args:
        order: Order instance
    
    Returns:
        dict: Status of print operations
    """
    from django.conf import settings
    import sys
    import logging
    
    # Get Django logger
    logger = logging.getLogger('orders.printing')
    
    # VERBOSE DEBUG LOGGING - output to BOTH stdout and stderr
    logger.debug("=" * 60)
    logger.debug(f" AUTO_PRINT_ORDER CALLED for Order #{order.order_number}")
    logger.debug(f" WINDOWS_PRINTING_AVAILABLE = {WINDOWS_PRINTING_AVAILABLE}")
    logger.debug(f" platform.system() = {platform.system()}")
    logger.debug("=" * 60)
    sys.stdout.flush()
    
    # Also log to Django's logging system
    logger.warning(f"🖨️ AUTO_PRINT_ORDER CALLED for Order #{order.order_number}")
    logger.warning(f"🖨️ WINDOWS_PRINTING_AVAILABLE = {WINDOWS_PRINTING_AVAILABLE}")
    
    result = {
        'kot_printed': False,
        'bot_printed': False,
        'buffet_printed': False,
        'service_printed': False,
        'errors': []
    }
    
    try:
        # Get printer settings for this specific restaurant/branch
        print_settings = get_restaurant_print_settings(order)
        
        logger.debug(f" Print settings from {print_settings['source']}: {print_settings['name']}")
        logger.debug(f"auto_print_kot: {print_settings['auto_print_kot']}, auto_print_bot: {print_settings['auto_print_bot']}")
        logger.debug(f"auto_print_buffet: {print_settings.get('auto_print_buffet', False)}, auto_print_service: {print_settings.get('auto_print_service', False)}")
        sys.stdout.flush()
        
        # Check restaurant auto-print settings (check all station types)
        any_auto_print = (
            print_settings['auto_print_kot'] or 
            print_settings['auto_print_bot'] or 
            print_settings.get('auto_print_buffet', False) or 
            print_settings.get('auto_print_service', False)
        )
        if not any_auto_print:
            logger.warning(f" Auto-print disabled for {print_settings['name']}")
            return result
        
        # Check for items by station
        has_kitchen_items = any(item.product.station == 'kitchen' for item in order.order_items.all())
        has_bar_items = any(item.product.station == 'bar' for item in order.order_items.all())
        has_buffet_items = any(item.product.station == 'buffet' for item in order.order_items.all())
        has_service_items = any(item.product.station == 'service' for item in order.order_items.all())
        
        # Determine print mode
        use_queue = getattr(settings, 'USE_PRINT_QUEUE', False)
        
        # Get the owner for queue-based printing (PrintJob requires User)
        owner = print_settings['owner']
        
        if use_queue:
            # Queue-based printing for hosted deployment
            if has_kitchen_items and print_settings['auto_print_kot']:
                content = _generate_kot_content(order)
                printer_name = print_settings['kitchen_printer_name']
                job = create_print_job(owner, 'kot', content, order=order, printer_name=printer_name)
                result['kot_printed'] = True
                logger.info(f" Queued KOT print job #{job.id} for Order #{order.order_number} (printer: {printer_name or 'auto'})")
            
            if has_bar_items and print_settings['auto_print_bot']:
                content = _generate_bot_content(order)
                printer_name = print_settings['bar_printer_name']
                job = create_print_job(owner, 'bot', content, order=order, printer_name=printer_name)
                result['bot_printed'] = True
                logger.info(f" Queued BOT print job #{job.id} for Order #{order.order_number} (printer: {printer_name or 'auto'})")
            
            if has_buffet_items and print_settings.get('auto_print_buffet', False):
                content = _generate_buffet_content(order)
                printer_name = print_settings.get('buffet_printer_name')
                job = create_print_job(owner, 'buffet', content, order=order, printer_name=printer_name)
                result['buffet_printed'] = True
                logger.info(f" Queued BUFFET print job #{job.id} for Order #{order.order_number} (printer: {printer_name or 'auto'})")
            
            if has_service_items and print_settings.get('auto_print_service', False):
                content = _generate_service_content(order)
                printer_name = print_settings.get('service_printer_name')
                job = create_print_job(owner, 'service', content, order=order, printer_name=printer_name)
                result['service_printed'] = True
                logger.info(f" Queued SERVICE print job #{job.id} for Order #{order.order_number} (printer: {printer_name or 'auto'})")
        else:
            # Direct local printing - auto-detect ready printer
            # The ThermalPrinter class handles checking if configured printer is ready
            # and falls back to auto-detection if not
            logger.debug(f" ENTERING LOCAL PRINT MODE (USE_PRINT_QUEUE=False)")
            logger.debug(f" has_kitchen_items: {has_kitchen_items}, auto_print_kot: {print_settings['auto_print_kot']}")
            logger.debug(f" has_bar_items: {has_bar_items}, auto_print_bot: {print_settings['auto_print_bot']}")
            sys.stdout.flush()
            
            if has_kitchen_items and print_settings['auto_print_kot']:
                logger.debug(f" PRINTING KOT - Creating ThermalPrinter...")
                sys.stdout.flush()
                printer = ThermalPrinter()  # Auto-detect ready thermal printer
                logger.debug(f" ThermalPrinter created: printer_name={printer.printer_name}")
                sys.stdout.flush()
                success = printer.print_kot(order)
                logger.debug(f" print_kot() returned: {success}")
                sys.stdout.flush()
                result['kot_printed'] = success
                if success:
                    logger.info(f" KOT printed for Order #{order.order_number} (printer: {printer.printer_name})")
                else:
                    result['errors'].append("KOT print failed")
            
            if has_bar_items and print_settings['auto_print_bot']:
                logger.debug(f" PRINTING BOT - Creating ThermalPrinter...")
                sys.stdout.flush()
                printer = ThermalPrinter()  # Auto-detect ready thermal printer
                logger.debug(f" ThermalPrinter created: printer_name={printer.printer_name}")
                sys.stdout.flush()
                success = printer.print_bot(order)
                result['bot_printed'] = success
                if success:
                    logger.info(f" BOT printed for Order #{order.order_number} (printer: {printer.printer_name})")
                else:
                    result['errors'].append("BOT print failed")
            
            if has_buffet_items and print_settings.get('auto_print_buffet', False):
                logger.debug(f" PRINTING BUFFET - Creating ThermalPrinter...")
                sys.stdout.flush()
                printer = ThermalPrinter()  # Auto-detect ready thermal printer
                logger.debug(f" ThermalPrinter created: printer_name={printer.printer_name}")
                sys.stdout.flush()
                success = printer.print_buffet(order)
                result['buffet_printed'] = success
                if success:
                    logger.info(f" BUFFET printed for Order #{order.order_number} (printer: {printer.printer_name})")
                else:
                    result['errors'].append("BUFFET print failed")
            
            if has_service_items and print_settings.get('auto_print_service', False):
                logger.debug(f" PRINTING SERVICE - Creating ThermalPrinter...")
                sys.stdout.flush()
                printer = ThermalPrinter()  # Auto-detect ready thermal printer
                logger.debug(f" ThermalPrinter created: printer_name={printer.printer_name}")
                sys.stdout.flush()
                success = printer.print_service(order)
                result['service_printed'] = success
                if success:
                    logger.info(f" SERVICE printed for Order #{order.order_number} (printer: {printer.printer_name})")
                else:
                    result['errors'].append("SERVICE print failed")
        
    except Exception as e:
        result['errors'].append('Print operation failed')
        logger.error(f" Print error: {str(e)}", exc_info=True)
    
    return result


def auto_print_receipt(payment):
    """
    Automatically print receipt after payment
    Supports both local printing (direct) and remote printing (queue)
    Each restaurant/branch uses its own independent printer settings.
    
    Args:
        payment: Payment instance
    
    Returns:
        dict: Status of print operation
    """
    from django.conf import settings
    
    result = {
        'receipt_printed': False,
        'errors': []
    }
    
    try:
        # Get printer settings for this specific restaurant/branch
        print_settings = get_restaurant_print_settings(payment.order)
        
        logger.info(f" Receipt print settings from {print_settings['source']}: {print_settings['name']}")
        
        # Determine print mode
        use_queue = getattr(settings, 'USE_PRINT_QUEUE', False)
        
        # Get the owner for queue-based printing (PrintJob requires User)
        owner = print_settings['owner']
        
        if use_queue:
            # Queue-based printing for hosted deployment
            content = _generate_receipt_content(payment)
            printer_name = print_settings['receipt_printer_name']
            job = create_print_job(owner, 'receipt', content, order=payment.order, payment=payment, printer_name=printer_name)
            result['receipt_printed'] = True
            logger.info(f" Queued receipt print job #{job.id} for Payment #{payment.id} (printer: {printer_name or 'auto'})")
        else:
            # Direct local printing - auto-detect ready printer
            # The ThermalPrinter class handles checking if configured printer is ready
            # and falls back to auto-detection if not
            printer = ThermalPrinter()  # Auto-detect ready thermal printer
            success = printer.print_receipt(payment)
            result['receipt_printed'] = success
            if success:
                logger.info(f" Receipt printed for Payment #{payment.id} (printer: {printer.printer_name})")
            else:
                result['errors'].append("Receipt print failed")
        
    except Exception as e:
        result['errors'].append('Receipt print operation failed')
        logger.error(f" Receipt print error: {str(e)}", exc_info=True)
    
    return result


def auto_print_bill(order, printed_by=None):
    """
    Print bill for an order (before payment) - shows what customer owes
    Uses the same receipt printer settings.
    
    Args:
        order: Order instance
        printed_by: User who requested the bill print
    
    Returns:
        dict: Status of print operation
    """
    from django.conf import settings
    
    result = {
        'bill_printed': False,
        'errors': []
    }
    
    try:
        # Get printer settings for this specific restaurant/branch
        print_settings = get_restaurant_print_settings(order)
        
        logger.info(f" Bill print settings from {print_settings['source']}: {print_settings['name']}")
        
        # Determine print mode
        use_queue = getattr(settings, 'USE_PRINT_QUEUE', False)
        
        # Get the owner for queue-based printing (PrintJob requires User)
        owner = print_settings['owner']
        
        if use_queue:
            # Queue-based printing for hosted deployment
            content = _generate_bill_content(order, printed_by)
            printer_name = print_settings['receipt_printer_name']  # Use receipt printer for bills
            job = create_print_job(owner, 'bill', content, order=order, printer_name=printer_name)
            result['bill_printed'] = True
            logger.info(f" Queued bill print job #{job.id} for Order #{order.order_number} (printer: {printer_name or 'auto'})")
        else:
            # Direct local printing - use receipt printer (SAME as print_receipt method)
            printer_name = print_settings['receipt_printer_name']
            
            # Determine which printer to use - EXACT same logic as print_receipt
            if printer_name:
                # ALWAYS try configured printer if it EXISTS
                if WINDOWS_PRINTING_AVAILABLE:
                    temp_printer = ThermalPrinter()
                    if temp_printer._printer_exists(printer_name):
                        printer = ThermalPrinter(printer_name=printer_name)
                        logger.info(f" Using configured receipt printer for bill: {printer_name}")
                    else:
                        logger.warning(f" Configured printer '{printer_name}' not found, auto-detecting...")
                        printer = ThermalPrinter()  # Auto-detect
                else:
                    printer = ThermalPrinter()
            else:
                # No printer configured, use auto-detected
                printer = ThermalPrinter()
            
            # Generate bill content
            content = _generate_bill_content(order, printed_by)
            
            # Format for thermal printer (NO cash drawer kick for bills)
            thermal_content = printer._format_for_thermal(content, "BILL")
            
            # Send to printer
            success = printer.print_text(thermal_content, f"Bill-{order.order_number}")
            result['bill_printed'] = success
            
            if success:
                logger.info(f" Bill printed for Order #{order.order_number} (printer: {printer.printer_name})")
            else:
                result['errors'].append("Bill print failed")
        
    except Exception as e:
        result['errors'].append('Bill print operation failed')
        logger.error(f" Bill print error: {str(e)}", exc_info=True)
    
    return result


def _generate_bill_content(order, printed_by=None):
    """Generate bill text content for order (before payment) - shows what customer owes"""
    from decimal import Decimal
    from accounts.models import User
    
    lines = []
    width = 48  # 80mm thermal printer - full width utilization
    restaurant = order.table_info.owner
    
    # Get currency symbol for this owner/restaurant
    currency_symbol = '$'  # Default
    if isinstance(restaurant, User):
        currency_symbol = restaurant.get_currency_symbol()
    else:
        try:
            from restaurant.models_restaurant import Restaurant
            if isinstance(restaurant, Restaurant):
                owner = restaurant.branch_owner or restaurant.main_owner
                if owner:
                    currency_symbol = owner.get_currency_symbol()
        except Exception:
            pass
    
    # Get restaurant name - use main restaurant name for branch staff
    if restaurant.role and restaurant.role.name == 'branch_owner':
        from restaurant.models import Restaurant
        branch_restaurant = Restaurant.objects.filter(
            branch_owner=restaurant, 
            is_main_restaurant=False
        ).first()
        if branch_restaurant and branch_restaurant.parent_restaurant:
            restaurant_name = (branch_restaurant.parent_restaurant.name or "RESTAURANT NAME").upper()
        else:
            restaurant_name = (restaurant.restaurant_name or "RESTAURANT NAME").upper()
    else:
        restaurant_name = (restaurant.restaurant_name or "RESTAURANT NAME").upper()
    
    # Restaurant Header
    lines.append("=" * width)
    lines.append(restaurant_name.center(width))
    lines.append("=" * width)
    
    # Bill title
    lines.append("")
    lines.append("** BILL **".center(width))
    lines.append("")
    
    # Order details
    lines.append(f"Order: {order.order_number}")
    lines.append(f"Date: {timezone.now().strftime('%b %d, %Y')}")
    lines.append(f"Time: {timezone.now().strftime('%H:%M')}")
    lines.append(f"Table: {order.table_info.tbl_no or 'Takeaway'}")
    
    # Ordered by (person who created the order)
    ordered_by = order.ordered_by
    if ordered_by:
        if hasattr(ordered_by, 'is_waiter') and ordered_by.is_waiter():
            role = "Waiter"
        elif hasattr(ordered_by, 'is_cashier') and ordered_by.is_cashier():
            role = "Cashier"
        elif hasattr(ordered_by, 'is_customer_care') and ordered_by.is_customer_care():
            role = "Customer Care"
        elif hasattr(ordered_by, 'is_owner') and ordered_by.is_owner():
            role = "Owner"
        elif hasattr(ordered_by, 'is_customer') and ordered_by.is_customer():
            role = "Customer"
        else:
            role = "Staff"
        
        full_name = f"{ordered_by.first_name} {ordered_by.last_name}".strip()
        if not full_name:
            full_name = ordered_by.username
        lines.append(f"Ordered by: {full_name} ({role})")
    
    # Printed by (person who requested bill print)
    if printed_by:
        if hasattr(printed_by, 'is_cashier') and printed_by.is_cashier():
            print_role = "Cashier"
        elif hasattr(printed_by, 'is_customer_care') and printed_by.is_customer_care():
            print_role = "Customer Care"
        elif hasattr(printed_by, 'is_owner') and printed_by.is_owner():
            print_role = "Owner"
        else:
            print_role = "Staff"
        
        print_name = f"{printed_by.first_name} {printed_by.last_name}".strip()
        if not print_name:
            print_name = printed_by.username
        lines.append(f"Printed by: {print_name} ({print_role})")
    
    lines.append("-" * width)
    
    # Items section
    lines.append("ITEMS:")
    lines.append("-" * width)
    
    # Items list with better alignment
    for item in order.order_items.all():
        item_total = item.get_total_price()
        qty_str = f"{item.quantity}x"
        item_name = item.product.name[:width-16]  # Truncate long names
        price_str = f"{currency_symbol}{float(item_total):.2f}"
        
        # Format: "2x Item Name..................$10.00"
        name_section = f"{qty_str:4} {item_name}"
        dots_needed = width - len(name_section) - len(price_str)
        line = name_section + ("." * dots_needed) + price_str
        lines.append(line)
    
    # Separator
    lines.append("-" * width)
    
    # Totals section
    subtotal = order.get_subtotal()
    discount = order.get_total_discount() if hasattr(order, 'get_total_discount') else Decimal('0')
    tax_rate = restaurant.tax_rate
    tax_amount = order.get_tax_amount() if hasattr(order, 'get_tax_amount') else (subtotal * tax_rate)
    total = order.get_total() if hasattr(order, 'get_total') else (subtotal - discount + tax_amount)
    
    # Subtotal
    subtotal_label = "Subtotal:"
    subtotal_value = f"{currency_symbol}{float(subtotal):.2f}"
    spacing = width - len(subtotal_label) - len(subtotal_value)
    lines.append(subtotal_label + (" " * spacing) + subtotal_value)
    
    # Discount (if any)
    if discount > 0:
        discount_label = "Discount:"
        discount_value = f"-{currency_symbol}{float(discount):.2f}"
        spacing = width - len(discount_label) - len(discount_value)
        lines.append(discount_label + (" " * spacing) + discount_value)
    
    # Tax
    tax_percentage = float(tax_rate * 100)
    tax_label = f"Tax ({tax_percentage:.1f}%):"
    tax_value = f"{currency_symbol}{float(tax_amount):.2f}"
    spacing = width - len(tax_label) - len(tax_value)
    lines.append(tax_label + (" " * spacing) + tax_value)
    
    # Separator
    lines.append("-" * width)
    
    # Grand Total
    total_label = "TOTAL DUE:"
    total_value = f"{currency_symbol}{float(total):.2f}"
    spacing = width - len(total_label) - len(total_value)
    lines.append(total_label + (" " * spacing) + total_value)
    
    # Check for partial payments
    from django.db.models import Sum
    total_paid = order.payments.filter(is_voided=False).aggregate(
        total=Sum('amount'))['total'] or Decimal('0.00')
    
    if total_paid > 0:
        lines.append("-" * width)
        paid_label = "Amount Paid:"
        paid_value = f"{currency_symbol}{float(total_paid):.2f}"
        spacing = width - len(paid_label) - len(paid_value)
        lines.append(paid_label + (" " * spacing) + paid_value)
        
        remaining = total - total_paid
        remaining_label = "BALANCE DUE:"
        remaining_value = f"{currency_symbol}{float(remaining):.2f}"
        spacing = width - len(remaining_label) - len(remaining_value)
        lines.append(remaining_label + (" " * spacing) + remaining_value)
    
    # Separator
    lines.append("-" * width)
    
    # Footer
    lines.append("")
    lines.append("*** THIS IS NOT A RECEIPT ***".center(width))
    lines.append("Payment required".center(width))
    lines.append("")
    lines.append("Thank you for dining with us!".center(width))
    lines.append("=" * width)
    
    return "\n".join(lines)


def _generate_kot_content(order):
    """Generate KOT text content (standalone function for queue-based printing)"""
    lines = []
    width = 48  # 80mm thermal printer - full width utilization
    
    # Header
    lines.append("=" * width)
    lines.append("KITCHEN ORDER TICKET (KOT)".center(width))
    lines.append("=" * width)
    
    # Restaurant info - use unified function
    restaurant_name = get_restaurant_display_name(order)
    
    lines.append("")
    lines.append(f"Restaurant: {restaurant_name}")
    lines.append(f"Order #: {order.order_number}")
    lines.append(f"Table: {order.table_info.tbl_no}")
    lines.append(f"Time: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
    
    # Show who placed the order
    ordered_by = order.ordered_by
    if ordered_by:
        if hasattr(ordered_by, 'is_waiter') and ordered_by.is_waiter():
            role = "Waiter"
        elif hasattr(ordered_by, 'is_cashier') and ordered_by.is_cashier():
            role = "Cashier"
        elif hasattr(ordered_by, 'is_customer_care') and ordered_by.is_customer_care():
            role = "Customer Care"
        elif hasattr(ordered_by, 'is_owner') and ordered_by.is_owner():
            role = "Owner"
        elif hasattr(ordered_by, 'is_customer') and ordered_by.is_customer():
            role = "Customer"
        else:
            role = "Staff"
        
        full_name = f"{ordered_by.first_name} {ordered_by.last_name}".strip()
        if not full_name:
            full_name = ordered_by.username
        
        lines.append(f"Ordered by: {full_name} ({role})")
    
    lines.append("-" * width)
    
    # Kitchen items only
    lines.append("")
    lines.append("KITCHEN ITEMS:")
    lines.append("-" * width)
    
    kitchen_items = [item for item in order.order_items.all() if item.product.station == 'kitchen']
    
    for item in kitchen_items:
        # Item name and quantity - left aligned
        qty_text = f"{item.quantity}x"
        lines.append(f"{qty_text:4} {item.product.name}")
        
        # Special instructions if any
        if order.special_instructions:
            wrapped = textwrap.wrap(f"Note: {order.special_instructions}", width=width-6)
            for line in wrapped:
                lines.append(f"     {line}")
    
    # Footer
    lines.append("-" * width)
    total_items = len(kitchen_items)
    total_qty = sum(item.quantity for item in kitchen_items)
    lines.append(f"Total Items: {total_items:>2}  |  Total Qty: {total_qty:>2}")
    lines.append("-" * width)
    lines.append("For kitchen preparation only".center(width))
    lines.append("NOT FOR BILLING".center(width))
    lines.append("=" * width)
    
    return "\n".join(lines)


def _generate_bot_content(order):
    """Generate BOT text content (standalone function for queue-based printing)"""
    lines = []
    width = 48  # 80mm thermal printer - full width utilization
    
    # Header
    lines.append("=" * width)
    lines.append("BAR ORDER TICKET (BOT)".center(width))
    lines.append("=" * width)
    
    # Restaurant info - use unified function
    restaurant_name = get_restaurant_display_name(order)
    
    lines.append("")
    lines.append(f"Restaurant: {restaurant_name}")
    lines.append(f"Order #: {order.order_number}")
    lines.append(f"Table: {order.table_info.tbl_no}")
    lines.append(f"Time: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
    
    # Show who placed the order
    ordered_by = order.ordered_by
    if ordered_by:
        if hasattr(ordered_by, 'is_waiter') and ordered_by.is_waiter():
            role = "Waiter"
        elif hasattr(ordered_by, 'is_cashier') and ordered_by.is_cashier():
            role = "Cashier"
        elif hasattr(ordered_by, 'is_customer_care') and ordered_by.is_customer_care():
            role = "Customer Care"
        elif hasattr(ordered_by, 'is_owner') and ordered_by.is_owner():
            role = "Owner"
        elif hasattr(ordered_by, 'is_customer') and ordered_by.is_customer():
            role = "Customer"
        else:
            role = "Staff"
        
        full_name = f"{ordered_by.first_name} {ordered_by.last_name}".strip()
        if not full_name:
            full_name = ordered_by.username
        
        lines.append(f"Ordered by: {full_name} ({role})")
    
    lines.append("-" * width)
    
    # Bar items only
    lines.append("")
    lines.append("BAR ITEMS:")
    lines.append("-" * width)
    
    bar_items = [item for item in order.order_items.all() if item.product.station == 'bar']
    
    for item in bar_items:
        # Item name and quantity - left aligned
        qty_text = f"{item.quantity}x"
        lines.append(f"{qty_text:4} {item.product.name}")
        
        # Special instructions if any
        if order.special_instructions:
            wrapped = textwrap.wrap(f"Note: {order.special_instructions}", width=width-6)
            for line in wrapped:
                lines.append(f"     {line}")
    
    # Footer
    lines.append("-" * width)
    total_items = len(bar_items)
    total_qty = sum(item.quantity for item in bar_items)
    lines.append(f"Total Items: {total_items:>2}  |  Total Qty: {total_qty:>2}")
    lines.append("-" * width)
    lines.append("For bar preparation only".center(width))
    lines.append("NOT FOR BILLING".center(width))
    lines.append("=" * width)
    
    return "\n".join(lines)


def _generate_buffet_content(order):
    """Generate BUFFET text content (standalone function for queue-based printing)"""
    lines = []
    width = 48  # 80mm thermal printer - full width utilization
    
    # Header
    lines.append("=" * width)
    lines.append("BUFFET ORDER TICKET".center(width))
    lines.append("=" * width)
    
    # Restaurant info - use unified function
    restaurant_name = get_restaurant_display_name(order)
    
    lines.append("")
    lines.append(f"Restaurant: {restaurant_name}")
    lines.append(f"Order #: {order.order_number}")
    lines.append(f"Table: {order.table_info.tbl_no}")
    lines.append(f"Time: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
    
    # Show who placed the order
    ordered_by = order.ordered_by
    if ordered_by:
        if hasattr(ordered_by, 'is_waiter') and ordered_by.is_waiter():
            role = "Waiter"
        elif hasattr(ordered_by, 'is_cashier') and ordered_by.is_cashier():
            role = "Cashier"
        elif hasattr(ordered_by, 'is_customer_care') and ordered_by.is_customer_care():
            role = "Customer Care"
        elif hasattr(ordered_by, 'is_owner') and ordered_by.is_owner():
            role = "Owner"
        elif hasattr(ordered_by, 'is_customer') and ordered_by.is_customer():
            role = "Customer"
        else:
            role = "Staff"
        
        full_name = f"{ordered_by.first_name} {ordered_by.last_name}".strip()
        if not full_name:
            full_name = ordered_by.username
        
        lines.append(f"Ordered by: {full_name} ({role})")
    
    lines.append("-" * width)
    
    # Buffet items only
    lines.append("")
    lines.append("BUFFET ITEMS:")
    lines.append("-" * width)
    
    buffet_items = [item for item in order.order_items.all() if item.product.station == 'buffet']
    
    for item in buffet_items:
        # Item name and quantity - left aligned
        qty_text = f"{item.quantity}x"
        lines.append(f"{qty_text:4} {item.product.name}")
        
        # Special instructions if any
        if order.special_instructions:
            wrapped = textwrap.wrap(f"Note: {order.special_instructions}", width=width-6)
            for line in wrapped:
                lines.append(f"     {line}")
    
    # Footer
    lines.append("-" * width)
    total_items = len(buffet_items)
    total_qty = sum(item.quantity for item in buffet_items)
    lines.append(f"Total Items: {total_items:>2}  |  Total Qty: {total_qty:>2}")
    lines.append("-" * width)
    lines.append("For buffet station only".center(width))
    lines.append("NOT FOR BILLING".center(width))
    lines.append("=" * width)
    
    return "\n".join(lines)


def _generate_service_content(order):
    """Generate SERVICE text content (standalone function for queue-based printing)"""
    lines = []
    width = 48  # 80mm thermal printer - full width utilization
    
    # Header
    lines.append("=" * width)
    lines.append("SERVICE ORDER TICKET".center(width))
    lines.append("=" * width)
    
    # Restaurant info - use unified function
    restaurant_name = get_restaurant_display_name(order)
    
    lines.append("")
    lines.append(f"Restaurant: {restaurant_name}")
    lines.append(f"Order #: {order.order_number}")
    lines.append(f"Table: {order.table_info.tbl_no}")
    lines.append(f"Time: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
    
    # Show who placed the order
    ordered_by = order.ordered_by
    if ordered_by:
        if hasattr(ordered_by, 'is_waiter') and ordered_by.is_waiter():
            role = "Waiter"
        elif hasattr(ordered_by, 'is_cashier') and ordered_by.is_cashier():
            role = "Cashier"
        elif hasattr(ordered_by, 'is_customer_care') and ordered_by.is_customer_care():
            role = "Customer Care"
        elif hasattr(ordered_by, 'is_owner') and ordered_by.is_owner():
            role = "Owner"
        elif hasattr(ordered_by, 'is_customer') and ordered_by.is_customer():
            role = "Customer"
        else:
            role = "Staff"
        
        full_name = f"{ordered_by.first_name} {ordered_by.last_name}".strip()
        if not full_name:
            full_name = ordered_by.username
        
        lines.append(f"Ordered by: {full_name} ({role})")
    
    lines.append("-" * width)
    
    # Service items only
    lines.append("")
    lines.append("SERVICE ITEMS:")
    lines.append("-" * width)
    
    service_items = [item for item in order.order_items.all() if item.product.station == 'service']
    
    for item in service_items:
        # Item name and quantity - left aligned
        qty_text = f"{item.quantity}x"
        lines.append(f"{qty_text:4} {item.product.name}")
        
        # Special instructions if any
        if order.special_instructions:
            wrapped = textwrap.wrap(f"Note: {order.special_instructions}", width=width-6)
            for line in wrapped:
                lines.append(f"     {line}")
    
    # Footer
    lines.append("-" * width)
    total_items = len(service_items)
    total_qty = sum(item.quantity for item in service_items)
    lines.append(f"Total Items: {total_items:>2}  |  Total Qty: {total_qty:>2}")
    lines.append("-" * width)
    lines.append("For service station only".center(width))
    lines.append("NOT FOR BILLING".center(width))
    lines.append("=" * width)
    
    return "\n".join(lines)


def _generate_receipt_content(payment):
    """Generate receipt text content for payment - optimized for thermal printer"""
    from decimal import Decimal
    from accounts.models import User
    
    lines = []
    width = 48  # 80mm thermal printer - full width utilization
    order = payment.order
    restaurant = order.table_info.owner
    
    # Get currency symbol for this owner/restaurant
    currency_symbol = '$'  # Default
    if isinstance(restaurant, User):
        currency_symbol = restaurant.get_currency_symbol()
    else:
        # Try to get from restaurant object
        try:
            from restaurant.models_restaurant import Restaurant
            if isinstance(restaurant, Restaurant):
                owner = restaurant.branch_owner or restaurant.main_owner
                if owner:
                    currency_symbol = owner.get_currency_symbol()
        except Exception:
            pass
    
    # Get restaurant name - use main restaurant name for branch staff
    if restaurant.role and restaurant.role.name == 'branch_owner':
        # For branch owners, show the main restaurant name
        from restaurant.models import Restaurant
        branch_restaurant = Restaurant.objects.filter(
            branch_owner=restaurant, 
            is_main_restaurant=False
        ).first()
        if branch_restaurant and branch_restaurant.parent_restaurant:
            restaurant_name = (branch_restaurant.parent_restaurant.name or "RESTAURANT NAME").upper()
        else:
            restaurant_name = (restaurant.restaurant_name or "RESTAURANT NAME").upper()
    else:
        restaurant_name = (restaurant.restaurant_name or "RESTAURANT NAME").upper()
    
    # Restaurant Header - EXACTLY like HTML
    lines.append(restaurant_name.center(width))
    
    # Description - EXACTLY like HTML
    if restaurant.restaurant_description:
        lines.append(restaurant.restaurant_description.center(width))
    else:
        lines.append("Cashier Food & Service".center(width))
    
    # Dotted separator - EXACTLY like HTML (dots not dashes)
    lines.append("-" * width)
    # NO blank line here
    # Receipt number - right-aligned EXACTLY like HTML
    receipt_num = f"RECEIPT #{payment.id:06d}"
    lines.append(receipt_num.rjust(width))
    # NO blank line after receipt number
    # Order details - left-aligned EXACTLY like HTML
    lines.append(f"Order: {order.order_number}")
    lines.append(f"Date: {payment.created_at.strftime('%b %d, %Y')}")
    lines.append(f"Time: {payment.created_at.strftime('%H:%M')}")
    lines.append(f"Table: {order.table_info.tbl_no or 'Takeaway'}")
    
    # Processed by (with role) - exactly like HTML
    processor = payment.processed_by
    if processor:
        if hasattr(processor, 'is_cashier') and processor.is_cashier():
            role = "Cashier"
        elif hasattr(processor, 'is_customer_care') and processor.is_customer_care():
            role = "Customer Care"
        elif hasattr(processor, 'is_owner') and processor.is_owner():
            role = "Owner"
        else:
            role = "Processed by"
        
        full_name = f"{processor.first_name} {processor.last_name}".strip()
        if not full_name:
            full_name = processor.username
        lines.append(f"{role}: {full_name}")
    else:
        lines.append(f"Processed by: System")
    # NO blank line after role
    # Items section
    lines.append("ITEMS:")
    lines.append("-" * width)
    # Items list with better alignment
    for item in order.order_items.all():
        item_total = item.get_total_price()
        qty_str = f"{item.quantity}x"
        item_name = item.product.name[:width-16]  # Truncate long names
        price_str = f"{currency_symbol}{float(item_total):.2f}"
        
        # Format: "2x Item Name..................$10.00"
        name_section = f"{qty_str:4} {item_name}"
        dots_needed = width - len(name_section) - len(price_str)
        line = name_section + ("." * dots_needed) + price_str
        lines.append(line)
    
    # Dotted separator - EXACTLY like HTML
    lines.append("-" * width)
    # Totals section - EXACTLY like HTML
    subtotal = order.get_subtotal()
    discount = order.get_total_discount() if hasattr(order, 'get_total_discount') else Decimal('0')
    tax_rate = restaurant.tax_rate
    tax_amount = order.get_tax_amount() if hasattr(order, 'get_tax_amount') else (subtotal * tax_rate)
    total = order.get_total() if hasattr(order, 'get_total') else (subtotal - discount + tax_amount)
    
    # Subtotal - right-aligned EXACTLY like HTML
    subtotal_label = "Subtotal:"
    subtotal_value = f"{currency_symbol}{float(subtotal):.2f}"
    spacing = width - len(subtotal_label) - len(subtotal_value)
    lines.append(subtotal_label + (" " * spacing) + subtotal_value)
    
    # Discount (if any) - right-aligned EXACTLY like HTML
    if discount > 0:
        discount_label = "Discount:"
        discount_value = f"-{currency_symbol}{float(discount):.2f}"
        spacing = width - len(discount_label) - len(discount_value)
        lines.append(discount_label + (" " * spacing) + discount_value)
    
    # Tax - right-aligned EXACTLY like HTML
    tax_percentage = float(tax_rate * 100)
    tax_label = f"Tax ({tax_percentage:.1f}%):"
    tax_value = f"{currency_symbol}{float(tax_amount):.2f}"
    spacing = width - len(tax_label) - len(tax_value)
    lines.append(tax_label + (" " * spacing) + tax_value)
    
    # Dotted separator - EXACTLY like HTML
    lines.append("-" * width)
    
    # Grand Total - right-aligned EXACTLY like HTML
    total_label = "TOTAL:"
    total_value = f"{currency_symbol}{float(total):.2f}"
    spacing = width - len(total_label) - len(total_value)
    lines.append(total_label + (" " * spacing) + total_value)
    
    # Dotted separator - EXACTLY like HTML
    lines.append("-" * width)
    # NO blank line here
    # Payment section - EXACTLY like HTML
    lines.append("PAYMENT:")
    # NO blank line after PAYMENT:
    # Payment method - right-aligned EXACTLY like HTML
    method_names = {
        'cash': 'Cash',
        'card': 'Card',
        'digital': 'Digital Payment',
        'voucher': 'Voucher'
    }
    payment_method = method_names.get(payment.payment_method, payment.payment_method.title())
    
    method_label = "Method:"
    spacing = width - len(method_label) - len(payment_method)
    lines.append(method_label + (" " * spacing) + payment_method)
    
    # Amount paid - right-aligned EXACTLY like HTML
    amount_label = "Amount Paid:"
    amount_value = f"{currency_symbol}{float(payment.amount):.2f}"
    spacing = width - len(amount_label) - len(amount_value)
    lines.append(amount_label + (" " * spacing) + amount_value)
    
    # Reference number (if any) - right-aligned EXACTLY like HTML
    if payment.reference_number:
        ref_label = "Reference:"
        ref_value = payment.reference_number
        spacing = width - len(ref_label) - len(ref_value)
        lines.append(ref_label + (" " * spacing) + ref_value)
    
    # Change (for cash) - right-aligned EXACTLY like HTML
    if payment.payment_method == 'cash' and payment.amount > total:
        change = payment.amount - total
        change_label = "Change:"
        change_value = f"{currency_symbol}{float(change):.2f}"
        spacing = width - len(change_label) - len(change_value)
        lines.append(change_label + (" " * spacing) + change_value)
    
    # Remaining balance (for partial) - right-aligned EXACTLY like HTML
    total_paid = order.payments.filter(is_voided=False).aggregate(
        total=Sum('amount'))['total'] or Decimal('0.00')
    
    if total_paid < order.total_amount:
        remaining = order.total_amount - total_paid
        remaining_label = "Remaining:"
        remaining_value = f"${float(remaining):.2f}"
        spacing = width - len(remaining_label) - len(remaining_value)
        lines.append(remaining_label + (" " * spacing) + remaining_value)
    
    # Dotted separator - EXACTLY like HTML
    lines.append("-" * width)
    # Footer - centered EXACTLY like HTML
    lines.append("Thank you for dining with us!".center(width))
    lines.append("Please come again".center(width))
    
    return "\n".join(lines)

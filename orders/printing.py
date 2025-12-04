"""
Server-side printing module for automatic KOT/BOT printing
Prints directly to thermal printer without browser dialog
"""

import sys
import platform

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
            'kitchen_printer_name': normalize_printer_name(restaurant.kitchen_printer_name),
            'bar_printer_name': normalize_printer_name(restaurant.bar_printer_name),
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
            'kitchen_printer_name': normalize_printer_name(owner.kitchen_printer_name),
            'bar_printer_name': normalize_printer_name(owner.bar_printer_name),
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
        'kitchen_printer_name': None,
        'bar_printer_name': None,
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
    
    print(f"✓ Created print job #{job.id} ({job_type}) for {restaurant.restaurant_name} (printer: {printer_name or 'auto-detect'})")
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
            print("⚠ Windows printing not available on this platform. Use print queue instead.")
            self.printer_name = None
            return
            
        if printer_name is None:
            # Auto-detect thermal printer
            self.printer_name = self._find_thermal_printer()
        else:
            self.printer_name = printer_name
    
    def _find_thermal_printer(self):
        """
        Automatically find thermal printer
        Looks for common thermal printer names
        
        Returns:
            str: Printer name
        """
        if not WINDOWS_PRINTING_AVAILABLE:
            return None
            
        thermal_keywords = ['POS', 'THERMAL', 'RETSOL', 'TP806', 'TP80', 'TP58', 
                           'RECEIPT', 'EPSON', 'STAR', 'BIXOLON', 'CITIZEN']
        
        # Get all printers
        all_printers = []
        for printer_info in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL):
            all_printers.append(printer_info[2])
        
        # Try to find thermal printer by name
        for printer in all_printers:
            printer_upper = printer.upper()
            for keyword in thermal_keywords:
                if keyword in printer_upper:
                    print(f"✓ Auto-detected thermal printer: {printer}")
                    return printer
        
        # Fallback to default printer
        default = win32print.GetDefaultPrinter()
        print(f"⚠ No thermal printer found, using default: {default}")
        return default
    
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
            print("⚠ Windows printing not available. Use print queue instead.")
            return False
            
        if self.printer_name is None:
            print("⚠ No printer configured.")
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
                    
                    print(f"✓ Printed to {self.printer_name}: {job_name}")
                    return True
                    
                finally:
                    win32print.EndDocPrinter(hPrinter)
            finally:
                win32print.ClosePrinter(hPrinter)
                
        except Exception as e:
            print(f"✗ Print Error: {str(e)}")
            return False
    
    def print_kot(self, order):
        """
        Print Kitchen Order Ticket directly to thermal printer
        Uses kitchen-specific printer from restaurant/branch settings
        
        Args:
            order: Order instance
        
        Returns:
            bool: Success status
        """
        try:
            # Get printer settings for this specific restaurant/branch
            print_settings = get_restaurant_print_settings(order)
            printer_name = print_settings['kitchen_printer_name']
            
            # Use specific printer if configured
            if printer_name:
                printer = ThermalPrinter(printer_name=printer_name)
            else:
                printer = self  # Use current instance (auto-detected)
            
            # Generate KOT content
            content = printer._generate_kot_content(order)
            
            # Print with ESC/POS commands for thermal printer
            thermal_content = printer._format_for_thermal(content, "KOT")
            
            # Send to printer
            return printer.print_text(thermal_content, f"KOT-{order.order_number}")
            
        except Exception as e:
            print(f"✗ KOT Print Error: {str(e)}")
            return False
    
    def print_bot(self, order):
        """
        Print Bar Order Ticket directly to thermal printer
        Uses bar-specific printer from restaurant/branch settings
        
        Args:
            order: Order instance
        
        Returns:
            bool: Success status
        """
        try:
            # Get printer settings for this specific restaurant/branch
            print_settings = get_restaurant_print_settings(order)
            printer_name = print_settings['bar_printer_name']
            
            # Use specific printer if configured
            if printer_name:
                printer = ThermalPrinter(printer_name=printer_name)
            else:
                printer = self  # Use current instance (auto-detected)
            
            # Generate BOT content
            content = printer._generate_bot_content(order)
            
            # Print with ESC/POS commands for thermal printer
            thermal_content = printer._format_for_thermal(content, "BOT")
            
            # Send to printer
            return printer.print_text(thermal_content, f"BOT-{order.order_number}")
            
        except Exception as e:
            print(f"✗ BOT Print Error: {str(e)}")
            return False
    
    def print_receipt(self, payment):
        """
        Print Receipt directly to thermal printer
        Uses receipt-specific printer from restaurant/branch settings
        
        Args:
            payment: Payment instance
        
        Returns:
            bool: Success status
        """
        try:
            # Get printer settings for this specific restaurant/branch
            print_settings = get_restaurant_print_settings(payment.order)
            printer_name = print_settings['receipt_printer_name']
            
            # Use specific printer if configured
            if printer_name:
                printer = ThermalPrinter(printer_name=printer_name)
            else:
                printer = self  # Use current instance (auto-detected)
            
            # Generate receipt content
            content = _generate_receipt_content(payment)
            
            # Print with ESC/POS commands for thermal printer
            thermal_content = printer._format_for_thermal(content, "RECEIPT")
            
            # Send to printer
            return printer.print_text(thermal_content, f"Receipt-{payment.order.order_number}")
            
        except Exception as e:
            print(f"✗ Receipt Print Error: {str(e)}")
            return False
    
    def _generate_kot_content(self, order):
        """Generate KOT text content"""
        lines = []
        width = 32  # 80mm thermal printer ~32 chars
        
        # Header
        lines.append("=" * width)
        lines.append("KITCHEN ORDER TICKET (KOT)".center(width))
        lines.append("=" * width)
        lines.append("")
        
        # Restaurant info - use main restaurant name for branch staff
        restaurant = order.table_info.owner
        if restaurant.role.name == 'branch_owner':
            from restaurant.models import Restaurant
            branch_restaurant = Restaurant.objects.filter(
                branch_owner=restaurant, 
                is_main_restaurant=False
            ).first()
            if branch_restaurant and branch_restaurant.parent_restaurant:
                restaurant_name = branch_restaurant.parent_restaurant.name
            else:
                restaurant_name = restaurant.restaurant_name
        else:
            restaurant_name = restaurant.restaurant_name
        
        lines.append(f"Restaurant: {restaurant_name}")
        lines.append(f"Order #: {order.order_number}")
        lines.append(f"Table: {order.table_info.tbl_no}")
        lines.append(f"Time: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
        lines.append("")
        lines.append("-" * width)
        lines.append("")
        
        # Kitchen items only
        lines.append("KITCHEN ITEMS:")
        lines.append("")
        
        kitchen_items = [item for item in order.order_items.all() if item.product.station == 'kitchen']
        
        for item in kitchen_items:
            # Item name and quantity
            lines.append(f"{item.quantity}x {item.product.name}")
            
            # Special instructions if any
            if order.special_instructions:
                wrapped = textwrap.wrap(f"   Note: {order.special_instructions}", width=width-3)
                lines.extend(wrapped)
            
            lines.append("")
        
        # Footer
        lines.append("-" * width)
        lines.append(f"Total Items: {len(kitchen_items)}")
        lines.append(f"Total Qty: {sum(item.quantity for item in kitchen_items)}")
        lines.append("")
        lines.append("For kitchen preparation only")
        lines.append("NOT FOR BILLING")
        lines.append("=" * width)
        
        return "\n".join(lines)
    
    def _generate_bot_content(self, order):
        """Generate BOT text content"""
        lines = []
        width = 32  # 80mm thermal printer ~32 chars
        
        # Header
        lines.append("=" * width)
        lines.append("BAR ORDER TICKET (BOT)".center(width))
        lines.append("=" * width)
        lines.append("")
        
        # Restaurant info - use main restaurant name for branch staff
        restaurant = order.table_info.owner
        if restaurant.role.name == 'branch_owner':
            from restaurant.models import Restaurant
            branch_restaurant = Restaurant.objects.filter(
                branch_owner=restaurant, 
                is_main_restaurant=False
            ).first()
            if branch_restaurant and branch_restaurant.parent_restaurant:
                restaurant_name = branch_restaurant.parent_restaurant.name
            else:
                restaurant_name = restaurant.restaurant_name
        else:
            restaurant_name = restaurant.restaurant_name
        
        lines.append(f"Restaurant: {restaurant_name}")
        lines.append(f"Order #: {order.order_number}")
        lines.append(f"Table: {order.table_info.tbl_no}")
        lines.append(f"Time: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
        lines.append("")
        lines.append("-" * width)
        lines.append("")
        
        # Bar items only
        lines.append("BAR ITEMS:")
        lines.append("")
        
        bar_items = [item for item in order.order_items.all() if item.product.station == 'bar']
        
        for item in bar_items:
            # Item name and quantity
            lines.append(f"{item.quantity}x {item.product.name}")
            
            # Special instructions if any
            if order.special_instructions:
                wrapped = textwrap.wrap(f"   Note: {order.special_instructions}", width=width-3)
                lines.extend(wrapped)
            
            lines.append("")
        
        # Footer
        lines.append("-" * width)
        lines.append(f"Total Items: {len(bar_items)}")
        lines.append(f"Total Qty: {sum(item.quantity for item in bar_items)}")
        lines.append("")
        lines.append("For bar preparation only")
        lines.append("NOT FOR BILLING")
        lines.append("=" * width)
        
        return "\n".join(lines)
    
    def _format_for_thermal(self, content, ticket_type):
        """
        Format content with ESC/POS commands for thermal printer
        
        Args:
            content: Text content
            ticket_type: "KOT" or "BOT"
        
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
        
        # Build formatted content
        formatted = INIT  # Initialize
        formatted += CENTER + LARGE + BOLD_ON
        formatted += f"\n{ticket_type}\n"
        formatted += BOLD_OFF + NORMAL + LEFT
        formatted += content
        formatted += "\n\n\n"  # Add spacing before cut
        formatted += CUT  # Cut paper
        
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
    
    result = {
        'kot_printed': False,
        'bot_printed': False,
        'errors': []
    }
    
    try:
        # Get printer settings for this specific restaurant/branch
        print_settings = get_restaurant_print_settings(order)
        
        print(f"🖨️ Print settings from {print_settings['source']}: {print_settings['name']}")
        print(f"   auto_print_kot: {print_settings['auto_print_kot']}, auto_print_bot: {print_settings['auto_print_bot']}")
        
        # Check restaurant auto-print settings
        if not (print_settings['auto_print_kot'] or print_settings['auto_print_bot']):
            print(f"⚠ Auto-print disabled for {print_settings['name']}")
            return result
        
        # Check for kitchen items
        has_kitchen_items = any(item.product.station == 'kitchen' for item in order.order_items.all())
        
        # Check for bar items
        has_bar_items = any(item.product.station == 'bar' for item in order.order_items.all())
        
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
                print(f"✓ Queued KOT print job #{job.id} for Order #{order.order_number} (printer: {printer_name or 'auto'})")
            
            if has_bar_items and print_settings['auto_print_bot']:
                content = _generate_bot_content(order)
                printer_name = print_settings['bar_printer_name']
                job = create_print_job(owner, 'bot', content, order=order, printer_name=printer_name)
                result['bot_printed'] = True
                print(f"✓ Queued BOT print job #{job.id} for Order #{order.order_number} (printer: {printer_name or 'auto'})")
        else:
            # Direct local printing - use specific printer for this restaurant/branch
            if has_kitchen_items and print_settings['auto_print_kot']:
                printer_name = print_settings['kitchen_printer_name']
                printer = ThermalPrinter(printer_name=printer_name) if printer_name else ThermalPrinter()
                success = printer.print_kot(order)
                result['kot_printed'] = success
                if success:
                    print(f"✓ KOT printed for Order #{order.order_number} (printer: {printer.printer_name})")
                else:
                    result['errors'].append("KOT print failed")
            
            if has_bar_items and print_settings['auto_print_bot']:
                printer_name = print_settings['bar_printer_name']
                printer = ThermalPrinter(printer_name=printer_name) if printer_name else ThermalPrinter()
                success = printer.print_bot(order)
                result['bot_printed'] = success
                if success:
                    print(f"✓ BOT printed for Order #{order.order_number} (printer: {printer.printer_name})")
                else:
                    result['errors'].append("BOT print failed")
        
    except Exception as e:
        result['errors'].append(str(e))
        print(f"✗ Print error: {str(e)}")
        import traceback
        traceback.print_exc()
    
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
        
        print(f"🧾 Receipt print settings from {print_settings['source']}: {print_settings['name']}")
        
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
            print(f"✓ Queued receipt print job #{job.id} for Payment #{payment.id} (printer: {printer_name or 'auto'})")
        else:
            # Direct local printing - use specific printer for this restaurant/branch
            printer_name = print_settings['receipt_printer_name']
            printer = ThermalPrinter(printer_name=printer_name) if printer_name else ThermalPrinter()
            success = printer.print_receipt(payment)
            result['receipt_printed'] = success
            if success:
                print(f"✓ Receipt printed for Payment #{payment.id} (printer: {printer.printer_name})")
            else:
                result['errors'].append("Receipt print failed")
        
    except Exception as e:
        result['errors'].append(str(e))
        print(f"✗ Receipt print error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    return result


def _generate_kot_content(order):
    """Generate KOT text content (standalone function for queue-based printing)"""
    lines = []
    width = 32  # 80mm thermal printer ~32 chars
    
    # Header
    lines.append("=" * width)
    lines.append("KITCHEN ORDER TICKET (KOT)".center(width))
    lines.append("=" * width)
    lines.append("")
    
    # Restaurant info - use main restaurant name for branch staff
    restaurant = order.table_info.owner
    if restaurant.role.name == 'branch_owner':
        from restaurant.models import Restaurant
        branch_restaurant = Restaurant.objects.filter(
            branch_owner=restaurant, 
            is_main_restaurant=False
        ).first()
        if branch_restaurant and branch_restaurant.parent_restaurant:
            restaurant_name = branch_restaurant.parent_restaurant.name
        else:
            restaurant_name = restaurant.restaurant_name
    else:
        restaurant_name = restaurant.restaurant_name
    
    lines.append(f"Restaurant: {restaurant_name}")
    lines.append(f"Order #: {order.order_number}")
    lines.append(f"Table: {order.table_info.tbl_no}")
    lines.append(f"Time: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
    lines.append("")
    lines.append("-" * width)
    lines.append("")
    
    # Kitchen items only
    lines.append("KITCHEN ITEMS:")
    lines.append("")
    
    kitchen_items = [item for item in order.order_items.all() if item.product.station == 'kitchen']
    
    for item in kitchen_items:
        # Item name and quantity
        lines.append(f"{item.quantity}x {item.product.name}")
        
        # Special instructions if any
        if order.special_instructions:
            wrapped = textwrap.wrap(f"   Note: {order.special_instructions}", width=width-3)
            lines.extend(wrapped)
        
        lines.append("")
    
    # Footer
    lines.append("-" * width)
    lines.append(f"Total Items: {len(kitchen_items)}")
    lines.append(f"Total Qty: {sum(item.quantity for item in kitchen_items)}")
    lines.append("")
    lines.append("For kitchen preparation only")
    lines.append("NOT FOR BILLING")
    lines.append("=" * width)
    
    return "\n".join(lines)


def _generate_bot_content(order):
    """Generate BOT text content (standalone function for queue-based printing)"""
    lines = []
    width = 32  # 80mm thermal printer ~32 chars
    
    # Header
    lines.append("=" * width)
    lines.append("BAR ORDER TICKET (BOT)".center(width))
    lines.append("=" * width)
    lines.append("")
    
    # Restaurant info - use main restaurant name for branch staff
    restaurant = order.table_info.owner
    if restaurant.role.name == 'branch_owner':
        from restaurant.models import Restaurant
        branch_restaurant = Restaurant.objects.filter(
            branch_owner=restaurant, 
            is_main_restaurant=False
        ).first()
        if branch_restaurant and branch_restaurant.parent_restaurant:
            restaurant_name = branch_restaurant.parent_restaurant.name
        else:
            restaurant_name = restaurant.restaurant_name
    else:
        restaurant_name = restaurant.restaurant_name
    
    lines.append(f"Restaurant: {restaurant_name}")
    lines.append(f"Order #: {order.order_number}")
    lines.append(f"Table: {order.table_info.tbl_no}")
    lines.append(f"Time: {timezone.now().strftime('%d/%m/%Y %H:%M')}")
    lines.append("")
    lines.append("-" * width)
    lines.append("")
    
    # Bar items only
    lines.append("BAR ITEMS:")
    lines.append("")
    
    bar_items = [item for item in order.order_items.all() if item.product.station == 'bar']
    
    for item in bar_items:
        # Item name and quantity
        lines.append(f"{item.quantity}x {item.product.name}")
        
        # Special instructions if any
        if order.special_instructions:
            wrapped = textwrap.wrap(f"   Note: {order.special_instructions}", width=width-3)
            lines.extend(wrapped)
        
        lines.append("")
    
    # Footer
    lines.append("-" * width)
    lines.append(f"Total Items: {len(bar_items)}")
    lines.append(f"Total Qty: {sum(item.quantity for item in bar_items)}")
    lines.append("")
    lines.append("For bar preparation only")
    lines.append("NOT FOR BILLING")
    lines.append("=" * width)
    
    return "\n".join(lines)


def _generate_receipt_content(payment):
    """Generate receipt text content for payment - matches actual thermal printer output EXACTLY"""
    from decimal import Decimal
    
    lines = []
    width = 32  # Standard 80mm thermal printer width (~32 chars)
    order = payment.order
    restaurant = order.table_info.owner
    
    # Get restaurant name - use main restaurant name for branch staff
    if restaurant.role.name == 'branch_owner':
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
    # NO blank line after role
    # Items section - EXACTLY like HTML
    lines.append("ITEMS:")
    # NO blank line after ITEMS:
    # Items list
    for item in order.order_items.all():
        item_total = item.get_total_price()
        item_name = f"{item.quantity}x {item.product.name}"
        price_str = f"${float(item_total):.2f}"
        
        # Right-align price perfectly
        spacing = width - len(item_name) - len(price_str)
        line = item_name + (" " * spacing) + price_str
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
    subtotal_value = f"${float(subtotal):.2f}"
    spacing = width - len(subtotal_label) - len(subtotal_value)
    lines.append(subtotal_label + (" " * spacing) + subtotal_value)
    
    # Discount (if any) - right-aligned EXACTLY like HTML
    if discount > 0:
        discount_label = "Discount:"
        discount_value = f"-${float(discount):.2f}"
        spacing = width - len(discount_label) - len(discount_value)
        lines.append(discount_label + (" " * spacing) + discount_value)
    
    # Tax - right-aligned EXACTLY like HTML
    tax_percentage = float(tax_rate * 100)
    tax_label = f"Tax ({tax_percentage:.1f}%):"
    tax_value = f"${float(tax_amount):.2f}"
    spacing = width - len(tax_label) - len(tax_value)
    lines.append(tax_label + (" " * spacing) + tax_value)
    
    # Dotted separator - EXACTLY like HTML
    lines.append("-" * width)
    
    # Grand Total - right-aligned EXACTLY like HTML
    total_label = "TOTAL:"
    total_value = f"${float(total):.2f}"
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
    amount_value = f"${float(payment.amount):.2f}"
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
        change_value = f"${float(change):.2f}"
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

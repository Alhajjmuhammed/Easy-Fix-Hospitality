"""
Management command to list available printers on the system

Usage:
    python manage.py list_printers
"""

from django.core.management.base import BaseCommand
import sys


class Command(BaseCommand):
    help = 'List all available printers on this system'

    def handle(self, *args, **options):
        try:
            import win32print  # type: ignore
            
            self.stdout.write('=' * 70)
            self.stdout.write(self.style.SUCCESS('Available Printers on This System:'))
            self.stdout.write('=' * 70)
            
            printers = []
            for printer_info in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL):
                printers.append(printer_info[2])
            
            if not printers:
                self.stdout.write(self.style.WARNING('No printers found!'))
                self.stdout.write('')
                self.stdout.write('Make sure:')
                self.stdout.write('  1. Printers are installed and powered on')
                self.stdout.write('  2. Printer drivers are installed')
                self.stdout.write('  3. This is a Windows system')
                return
            
            # Get default printer
            try:
                default_printer = win32print.GetDefaultPrinter()
            except Exception:
                default_printer = None
            
            # Display printers
            for i, printer in enumerate(printers, 1):
                is_default = ' (DEFAULT)' if printer == default_printer else ''
                self.stdout.write(f'{i}. {printer}{is_default}')
            
            self.stdout.write('')
            self.stdout.write('=' * 70)
            self.stdout.write('How to Configure Multiple Printers:')
            self.stdout.write('=' * 70)
            self.stdout.write('1. Go to Admin Panel → Users → Select Restaurant Owner')
            self.stdout.write('2. Scroll to "Printer Configuration" section')
            self.stdout.write('3. Copy printer names exactly as shown above:')
            self.stdout.write('')
            self.stdout.write('   Kitchen Printer Name: [paste printer name for KOT]')
            self.stdout.write('   Bar Printer Name:     [paste printer name for BOT]')
            self.stdout.write('   Receipt Printer Name: [paste printer name for Receipts]')
            self.stdout.write('')
            self.stdout.write('4. Leave blank to use auto-detected printer for all')
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('✓ Configuration saved!'))
            
        except ImportError:
            self.stdout.write(self.style.ERROR('Error: win32print module not available'))
            self.stdout.write('')
            self.stdout.write('This command only works on Windows systems.')
            self.stdout.write('Install pywin32: pip install pywin32')
            sys.exit(1)
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
            sys.exit(1)

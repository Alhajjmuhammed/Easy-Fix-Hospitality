"""
Management command to help set up Redis for real-time functionality
"""
import subprocess
import sys
import platform
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Setup and configure Redis for real-time WebSocket functionality'

    def add_arguments(self, parser):
        parser.add_argument(
            '--install',
            action='store_true',
            help='Attempt to install Redis (Windows only)',
        )
        parser.add_argument(
            '--start',
            action='store_true',
            help='Start Redis server',
        )
        parser.add_argument(
            '--status',
            action='store_true',
            help='Check Redis server status',
        )

    def handle(self, *args, **options):
        if options['status']:
            self.check_redis_status()
        elif options['install']:
            self.install_redis()
        elif options['start']:
            self.start_redis()
        else:
            self.show_setup_instructions()

    def check_redis_status(self):
        """Check if Redis is running"""
        try:
            import redis
            r = redis.Redis(host='localhost', port=6379, db=0)
            r.ping()
            self.stdout.write(
                self.style.SUCCESS('✓ Redis is running and accessible')
            )
            return True
        except redis.ConnectionError:
            self.stdout.write(
                self.style.ERROR('✗ Redis is not running or not accessible')
            )
            return False
        except ImportError:
            self.stdout.write(
                self.style.ERROR('✗ Redis Python client is not installed')
            )
            return False

    def install_redis(self):
        """Install Redis based on the platform"""
        system = platform.system().lower()
        
        if system == 'windows':
            self.install_redis_windows()
        elif system == 'darwin':  # macOS
            self.install_redis_macos()
        elif system == 'linux':
            self.install_redis_linux()
        else:
            self.stdout.write(
                self.style.ERROR(f'Automatic Redis installation not supported for {system}')
            )

    def install_redis_windows(self):
        """Install Redis on Windows"""
        self.stdout.write('Installing Redis on Windows...')
        
        # Check if chocolatey is available
        try:
            subprocess.run(['choco', '--version'], check=True, capture_output=True)
            self.stdout.write('Found Chocolatey, installing Redis...')
            subprocess.run(['choco', 'install', 'redis-64', '-y'], check=True)
            self.stdout.write(
                self.style.SUCCESS('✓ Redis installed successfully via Chocolatey')
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Chocolatey not available, provide manual instructions
            self.stdout.write(
                self.style.WARNING('Chocolatey not found. Please install Redis manually:')
            )
            self.stdout.write('1. Download Redis for Windows from:')
            self.stdout.write('   https://github.com/tporadowski/redis/releases')
            self.stdout.write('2. Extract and run redis-server.exe')
            self.stdout.write('3. Or install using Windows Subsystem for Linux (WSL)')

    def install_redis_macos(self):
        """Install Redis on macOS"""
        try:
            subprocess.run(['brew', '--version'], check=True, capture_output=True)
            self.stdout.write('Found Homebrew, installing Redis...')
            subprocess.run(['brew', 'install', 'redis'], check=True)
            self.stdout.write(
                self.style.SUCCESS('✓ Redis installed successfully via Homebrew')
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.stdout.write(
                self.style.WARNING('Homebrew not found. Please install Redis manually:')
            )
            self.stdout.write('1. Install Homebrew: /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"')
            self.stdout.write('2. Run: brew install redis')

    def install_redis_linux(self):
        """Install Redis on Linux"""
        try:
            # Try apt-get first (Ubuntu/Debian)
            subprocess.run(['which', 'apt-get'], check=True, capture_output=True)
            self.stdout.write('Installing Redis via apt-get...')
            subprocess.run(['sudo', 'apt-get', 'update'], check=True)
            subprocess.run(['sudo', 'apt-get', 'install', '-y', 'redis-server'], check=True)
            self.stdout.write(
                self.style.SUCCESS('✓ Redis installed successfully via apt-get')
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            try:
                # Try yum (CentOS/RHEL)
                subprocess.run(['which', 'yum'], check=True, capture_output=True)
                self.stdout.write('Installing Redis via yum...')
                subprocess.run(['sudo', 'yum', 'install', '-y', 'redis'], check=True)
                self.stdout.write(
                    self.style.SUCCESS('✓ Redis installed successfully via yum')
                )
            except (subprocess.CalledProcessError, FileNotFoundError):
                self.stdout.write(
                    self.style.WARNING('Could not auto-install Redis. Please install manually:')
                )
                self.stdout.write('Ubuntu/Debian: sudo apt-get install redis-server')
                self.stdout.write('CentOS/RHEL: sudo yum install redis')

    def start_redis(self):
        """Start Redis server"""
        try:
            if platform.system().lower() == 'windows':
                # Windows - try to start redis service or run redis-server
                try:
                    subprocess.Popen(['redis-server'])
                    self.stdout.write('Started Redis server')
                except FileNotFoundError:
                    self.stdout.write(
                        self.style.ERROR('redis-server not found in PATH')
                    )
            else:
                # Unix-like systems
                subprocess.run(['redis-server', '--daemonize', 'yes'], check=True)
                self.stdout.write(
                    self.style.SUCCESS('✓ Redis server started in daemon mode')
                )
        except subprocess.CalledProcessError:
            self.stdout.write(
                self.style.ERROR('Failed to start Redis server')
            )
        except FileNotFoundError:
            self.stdout.write(
                self.style.ERROR('redis-server command not found')
            )

    def show_setup_instructions(self):
        """Show comprehensive setup instructions"""
        self.stdout.write(self.style.HTTP_INFO('=== Redis Setup for Real-time Features ==='))
        self.stdout.write('')
        
        # Check current status
        redis_running = self.check_redis_status()
        
        if not redis_running:
            self.stdout.write('')
            self.stdout.write(self.style.HTTP_INFO('Quick Setup Options:'))
            self.stdout.write('')
            
            system = platform.system().lower()
            if system == 'windows':
                self.stdout.write('Option 1 - Using Chocolatey (Recommended):')
                self.stdout.write('  1. Install Chocolatey: https://chocolatey.org/install')
                self.stdout.write('  2. Run: choco install redis-64 -y')
                self.stdout.write('  3. Start: redis-server')
                self.stdout.write('')
                self.stdout.write('Option 2 - Manual Installation:')
                self.stdout.write('  1. Download: https://github.com/tporadowski/redis/releases')
                self.stdout.write('  2. Extract and run redis-server.exe')
                self.stdout.write('')
                self.stdout.write('Option 3 - Windows Subsystem for Linux (WSL):')
                self.stdout.write('  1. Install WSL: wsl --install')
                self.stdout.write('  2. In WSL: sudo apt update && sudo apt install redis-server')
                self.stdout.write('  3. Start: redis-server --daemonize yes')
                
            elif system == 'darwin':  # macOS
                self.stdout.write('Using Homebrew (Recommended):')
                self.stdout.write('  1. Install Homebrew: /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"')
                self.stdout.write('  2. Run: brew install redis')
                self.stdout.write('  3. Start: redis-server --daemonize yes')
                
            elif system == 'linux':
                self.stdout.write('Ubuntu/Debian:')
                self.stdout.write('  sudo apt update && sudo apt install redis-server')
                self.stdout.write('  sudo systemctl start redis-server')
                self.stdout.write('')
                self.stdout.write('CentOS/RHEL:')
                self.stdout.write('  sudo yum install redis')
                self.stdout.write('  sudo systemctl start redis')
        
        self.stdout.write('')
        self.stdout.write(self.style.HTTP_INFO('Alternative: In-Memory Channels (Development Only)'))
        self.stdout.write('If you cannot install Redis, the system will fall back to')
        self.stdout.write('in-memory channels which work for single-server development.')
        self.stdout.write('')
        
        self.stdout.write(self.style.HTTP_INFO('Testing Redis Connection:'))
        self.stdout.write(f'  python manage.py setup_redis --status')
        self.stdout.write('')
        
        self.stdout.write(self.style.HTTP_INFO('Management Commands:'))
        self.stdout.write(f'  python manage.py setup_redis --install    # Attempt auto-install')
        self.stdout.write(f'  python manage.py setup_redis --start      # Start Redis server')
        self.stdout.write(f'  python manage.py setup_redis --status     # Check status')
        self.stdout.write('')

        # Show current Django Channels configuration
        channel_layers = getattr(settings, 'CHANNEL_LAYERS', {})
        if channel_layers:
            backend = channel_layers.get('default', {}).get('BACKEND', 'Not configured')
            self.stdout.write(f'Current Channels Backend: {backend}')
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('After Redis is running, restart your Django development server'))
        self.stdout.write(self.style.SUCCESS('to enable real-time WebSocket functionality!'))
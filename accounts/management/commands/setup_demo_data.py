"""
Django management command to set up demo data for Easy-Fix-Hospitality
Creates users, restaurants, menus, products, and tables
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from accounts.models import User, Role
from restaurant.models import TableInfo, MainCategory, SubCategory, Product
from restaurant.models_restaurant import Restaurant
from decimal import Decimal
import random
import uuid


class Command(BaseCommand):
    help = 'Sets up demo data: users, restaurants, menus, products, and tables'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS('🚀 Setting up demo data...'))
        
        with transaction.atomic():
            # Step 1: Create Roles
            self.create_roles()
            
            # Step 2: Create Users
            users = self.create_users()
            
            # Step 2.5: Create Restaurant Instance
            restaurant = self.create_restaurant(users['restaurant_owner'])
            
            # Step 3: Create Tables
            self.create_tables(users['restaurant_owner'])
            
            # Step 4: Create Menu Categories
            self.create_menu(users['restaurant_owner'])
            
        self.stdout.write(self.style.SUCCESS('✅ Demo data setup complete!'))
        self.print_summary()

    def create_roles(self):
        """Create all required roles"""
        self.stdout.write('📋 Creating roles...')
        
        roles_data = [
            ('administrator', 'System Administrator'),
            ('main_owner', 'Main Restaurant Owner (Multiple Branches)'),
            ('branch_owner', 'Branch Owner'),
            ('owner', 'Restaurant Owner'),
            ('customer_care', 'Customer Care Staff'),
            ('kitchen', 'Kitchen Staff'),
            ('bar', 'Bar Staff'),
            ('buffet', 'Buffet Staff'),
            ('service', 'Service Staff'),
            ('cashier', 'Cashier'),
            ('customer', 'Customer'),
        ]
        
        for role_name, description in roles_data:
            role, created = Role.objects.get_or_create(
                name=role_name,
                defaults={'description': description}
            )
            if created:
                self.stdout.write(f'  ✓ Created role: {role_name}')
            else:
                self.stdout.write(f'  - Role exists: {role_name}')

    def create_users(self):
        """Create demo users"""
        self.stdout.write('👥 Creating users...')
        
        users = {}
        
        # 1. Administrator
        admin_role = Role.objects.get(name='administrator')
        admin, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@easyfixhospitality.com',
                'first_name': 'System',
                'last_name': 'Admin',
                'role': admin_role,
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if created:
            admin.set_password('admin123')
            admin.save()
            self.stdout.write(f'  ✓ Created admin: admin / admin123')
        else:
            self.stdout.write(f'  - Admin exists: admin')
        users['admin'] = admin
        
        # 2. Restaurant Owner (Main Owner)
        owner_role = Role.objects.get(name='main_owner')
        restaurant_owner, created = User.objects.get_or_create(
            username='restaurant_owner',
            defaults={
                'email': 'owner@restaurant.com',
                'first_name': 'John',
                'last_name': 'Restaurant',
                'role': owner_role,
                'restaurant_name': 'The Grand Restaurant',
                'restaurant_description': 'Fine dining experience with exceptional cuisine',
                'phone_number': '+1234567890',
                'address': '123 Main Street, City Center',
                'tax_rate': Decimal('0.0800'),  # 8% tax
                'currency_code': 'USD',
                'auto_print_kot': True,
                'auto_print_bot': True,
            }
        )
        if created:
            restaurant_owner.set_password('owner123')
            restaurant_owner.save()
            self.stdout.write(f'  ✓ Created owner: restaurant_owner / owner123')
        else:
            self.stdout.write(f'  - Owner exists: restaurant_owner')
        users['restaurant_owner'] = restaurant_owner
        
        # 3. Kitchen Staff
        kitchen_role = Role.objects.get(name='kitchen')
        kitchen_staff, created = User.objects.get_or_create(
            username='kitchen_staff',
            defaults={
                'email': 'kitchen@restaurant.com',
                'first_name': 'Mike',
                'last_name': 'Chef',
                'role': kitchen_role,
                'owner': restaurant_owner,
                'phone_number': '+1234567891',
            }
        )
        if created:
            kitchen_staff.set_password('kitchen123')
            kitchen_staff.save()
            self.stdout.write(f'  ✓ Created kitchen staff: kitchen_staff / kitchen123')
        else:
            self.stdout.write(f'  - Kitchen staff exists: kitchen_staff')
        users['kitchen_staff'] = kitchen_staff
        
        # 4. Cashier
        cashier_role = Role.objects.get(name='cashier')
        cashier, created = User.objects.get_or_create(
            username='cashier',
            defaults={
                'email': 'cashier@restaurant.com',
                'first_name': 'Sarah',
                'last_name': 'Cashier',
                'role': cashier_role,
                'owner': restaurant_owner,
                'phone_number': '+1234567892',
            }
        )
        if created:
            cashier.set_password('cashier123')
            cashier.save()
            self.stdout.write(f'  ✓ Created cashier: cashier / cashier123')
        else:
            self.stdout.write(f'  - Cashier exists: cashier')
        users['cashier'] = cashier
        
        # 5. Bar Staff
        bar_role = Role.objects.get(name='bar')
        bar_staff, created = User.objects.get_or_create(
            username='bar_staff',
            defaults={
                'email': 'bar@restaurant.com',
                'first_name': 'Tom',
                'last_name': 'Bartender',
                'role': bar_role,
                'owner': restaurant_owner,
                'phone_number': '+1234567893',
            }
        )
        if created:
            bar_staff.set_password('bar123')
            bar_staff.save()
            self.stdout.write(f'  ✓ Created bar staff: bar_staff / bar123')
        else:
            self.stdout.write(f'  - Bar staff exists: bar_staff')
        users['bar_staff'] = bar_staff
        
        # 6. Customer
        customer_role = Role.objects.get(name='customer')
        customer, created = User.objects.get_or_create(
            username='customer',
            defaults={
                'email': 'customer@example.com',
                'first_name': 'Alice',
                'last_name': 'Customer',
                'role': customer_role,
                'owner': restaurant_owner,
                'phone_number': '+1234567894',
            }
        )
        if created:
            customer.set_password('customer123')
            customer.save()
            self.stdout.write(f'  ✓ Created customer: customer / customer123')
        else:
            self.stdout.write(f'  - Customer exists: customer')
        users['customer'] = customer
        
        return users

    def create_restaurant(self, main_owner):
        """Create Restaurant model instance"""
        self.stdout.write('🏢 Creating restaurant...')
        
        restaurant, created = Restaurant.objects.get_or_create(
            name='The Grand Restaurant',
            defaults={
                'description': 'Fine dining experience with exceptional cuisine',
                'address': '123 Main Street, Downtown, City Center, State 12345',
                'subscription_plan': 'PRO',
                'main_owner': main_owner,
                'branch_owner': main_owner,
                'is_main_restaurant': True,
                'qr_code': str(uuid.uuid4())[:8].upper(),
                'contact_phone': '+1234567890',
                'contact_email': 'info@grandrestaurant.com',
                'tax_rate': Decimal('0.0800'),
                'currency_code': 'USD',
                'is_active': True,
            }
        )
        
        if created:
            self.stdout.write(f'  ✓ Created: {restaurant.name} (PRO Plan)')
        else:
            self.stdout.write(f'  - Restaurant exists: {restaurant.name}')
            
        return restaurant

    def create_tables(self, owner):
        """Create restaurant tables"""
        self.stdout.write('🪑 Creating tables...')
        
        tables_data = [
            ('T1', 2),
            ('T2', 4),
            ('T3', 4),
            ('T4', 6),
            ('T5', 8),
            ('VIP-1', 4),
            ('VIP-2', 6),
            ('BAR-1', 2),
            ('BAR-2', 2),
            ('OUTDOOR-1', 4),
        ]
        
        for table_no, capacity in tables_data:
            table, created = TableInfo.objects.get_or_create(
                owner=owner,
                tbl_no=table_no,
                defaults={
                    'capacity': capacity,
                    'is_available': True,
                }
            )
            if created:
                self.stdout.write(f'  ✓ Created table: {table_no} (Capacity: {capacity})')

    def create_menu(self, owner):
        """Create menu categories and products"""
        self.stdout.write('🍽️  Creating menu...')
        
        # Main Categories
        categories_data = {
            'Appetizers': 'Start your meal with our delicious appetizers',
            'Main Course': 'Our signature main dishes',
            'Desserts': 'Sweet endings to your meal',
            'Beverages': 'Drinks and refreshments',
            'Bar Menu': 'Alcoholic beverages and cocktails',
        }
        
        categories = {}
        for cat_name, cat_desc in categories_data.items():
            category, created = MainCategory.objects.get_or_create(
                owner=owner,
                name=cat_name,
                defaults={
                    'description': cat_desc,
                    'is_active': True,
                }
            )
            if created:
                self.stdout.write(f'  ✓ Created category: {cat_name}')
            categories[cat_name] = category
        
        # Products for Appetizers
        appetizers = [
            ('Caesar Salad', 'Fresh romaine lettuce with caesar dressing', 8.99, 'kitchen'),
            ('Garlic Bread', 'Toasted bread with garlic butter', 5.99, 'kitchen'),
            ('Spring Rolls', 'Crispy vegetable spring rolls', 7.99, 'kitchen'),
            ('Bruschetta', 'Toasted bread with tomatoes and basil', 9.99, 'kitchen'),
            ('Chicken Wings', 'Spicy buffalo wings with ranch', 12.99, 'kitchen'),
        ]
        
        for name, desc, price, station in appetizers:
            Product.objects.get_or_create(
                main_category=categories['Appetizers'],
                name=name,
                defaults={
                    'description': desc,
                    'price': Decimal(str(price)),
                    'available_in_stock': random.randint(20, 50),
                    'is_available': True,
                    'preparation_time': random.randint(10, 20),
                    'station': station,
                }
            )
        
        # Products for Main Course
        main_courses = [
            ('Grilled Salmon', 'Atlantic salmon with herbs', 24.99, 'kitchen'),
            ('Ribeye Steak', '12oz premium ribeye steak', 34.99, 'kitchen'),
            ('Chicken Alfredo', 'Creamy pasta with grilled chicken', 18.99, 'kitchen'),
            ('Vegetable Curry', 'Mixed vegetables in curry sauce', 15.99, 'kitchen'),
            ('Beef Burger', 'Angus beef burger with fries', 16.99, 'kitchen'),
            ('BBQ Ribs', 'Slow-cooked pork ribs', 22.99, 'kitchen'),
            ('Margherita Pizza', 'Classic pizza with mozzarella', 14.99, 'kitchen'),
            ('Seafood Paella', 'Spanish rice with mixed seafood', 26.99, 'kitchen'),
        ]
        
        for name, desc, price, station in main_courses:
            Product.objects.get_or_create(
                main_category=categories['Main Course'],
                name=name,
                defaults={
                    'description': desc,
                    'price': Decimal(str(price)),
                    'available_in_stock': random.randint(20, 50),
                    'is_available': True,
                    'preparation_time': random.randint(25, 45),
                    'station': station,
                }
            )
        
        # Products for Desserts
        desserts = [
            ('Chocolate Cake', 'Rich chocolate layer cake', 7.99, 'kitchen'),
            ('Tiramisu', 'Classic Italian dessert', 8.99, 'kitchen'),
            ('Ice Cream Sundae', 'Three scoops with toppings', 6.99, 'kitchen'),
            ('Cheesecake', 'New York style cheesecake', 8.99, 'kitchen'),
            ('Apple Pie', 'Homemade apple pie with ice cream', 7.99, 'kitchen'),
        ]
        
        for name, desc, price, station in desserts:
            Product.objects.get_or_create(
                main_category=categories['Desserts'],
                name=name,
                defaults={
                    'description': desc,
                    'price': Decimal(str(price)),
                    'available_in_stock': random.randint(15, 30),
                    'is_available': True,
                    'preparation_time': random.randint(5, 15),
                    'station': station,
                }
            )
        
        # Products for Beverages
        beverages = [
            ('Coca Cola', 'Classic Coke', 2.99, 'bar'),
            ('Fresh Orange Juice', 'Freshly squeezed', 4.99, 'bar'),
            ('Iced Tea', 'Lemon iced tea', 3.99, 'bar'),
            ('Coffee', 'Espresso or Americano', 3.99, 'bar'),
            ('Mineral Water', 'Sparkling or still', 2.49, 'bar'),
        ]
        
        for name, desc, price, station in beverages:
            Product.objects.get_or_create(
                main_category=categories['Beverages'],
                name=name,
                defaults={
                    'description': desc,
                    'price': Decimal(str(price)),
                    'available_in_stock': random.randint(50, 100),
                    'is_available': True,
                    'preparation_time': 5,
                    'station': station,
                }
            )
        
        # Products for Bar Menu
        bar_items = [
            ('Mojito', 'Classic rum cocktail', 10.99, 'bar'),
            ('Margarita', 'Tequila with lime', 11.99, 'bar'),
            ('Whiskey Sour', 'Bourbon with lemon', 12.99, 'bar'),
            ('Cosmopolitan', 'Vodka cranberry cocktail', 11.99, 'bar'),
            ('Draft Beer', 'Local craft beer', 6.99, 'bar'),
            ('House Wine (Glass)', 'Red or White', 8.99, 'bar'),
        ]
        
        for name, desc, price, station in bar_items:
            Product.objects.get_or_create(
                main_category=categories['Bar Menu'],
                name=name,
                defaults={
                    'description': desc,
                    'price': Decimal(str(price)),
                    'available_in_stock': random.randint(30, 100),
                    'is_available': True,
                    'preparation_time': random.randint(3, 8),
                    'station': station,
                }
            )
        
        total_products = Product.objects.filter(main_category__owner=owner).count()
        self.stdout.write(f'  ✓ Created {total_products} products across 5 categories')

    def print_summary(self):
        """Print summary of created data"""
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('📊 DEMO DATA SUMMARY'))
        self.stdout.write('='*60)
        
        self.stdout.write('\n👥 LOGIN CREDENTIALS:')
        self.stdout.write('-'*60)
        
        credentials = [
            ('Administrator', 'admin', 'admin123', 'Full system access'),
            ('Restaurant Owner', 'restaurant_owner', 'owner123', 'Manage restaurant'),
            ('Kitchen Staff', 'kitchen_staff', 'kitchen123', 'View/manage orders'),
            ('Cashier', 'cashier', 'cashier123', 'Process payments'),
            ('Bar Staff', 'bar_staff', 'bar123', 'Manage bar orders'),
            ('Customer', 'customer', 'customer123', 'Place orders'),
        ]
        
        for role, username, password, access in credentials:
            self.stdout.write(f'  {role:20} | {username:20} | {password:15} | {access}')
        
        self.stdout.write('\n📍 ACCESS URLS:')
        self.stdout.write('-'*60)
        self.stdout.write('  Main Site:     http://localhost:8000/')
        self.stdout.write('  Admin Panel:   http://localhost:8000/secure-management-portal/')
        self.stdout.write('  Owner Dashboard: http://localhost:8000/admin-panel/')
        
        self.stdout.write('\n🍽️  RESTAURANT DETAILS:')
        self.stdout.write('-'*60)
        restaurant_count = Restaurant.objects.count()
        self.stdout.write(f'  Restaurants: {restaurant_count} (1 main restaurant created)')
        self.stdout.write('  Name:        The Grand Restaurant')
        self.stdout.write('  Plan:        PRO (Multi-Branch Support)')
        self.stdout.write('  Tables:      10 tables (T1-T5, VIP-1/2, BAR-1/2, OUTDOOR-1)')
        self.stdout.write('  Categories:  5 (Appetizers, Main Course, Desserts, Beverages, Bar)')
        total_products = Product.objects.filter(main_category__owner__username='restaurant_owner').count()
        self.stdout.write(f'  Products:    {total_products} items')
        
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('✅ You can now login and start using the system!'))
        self.stdout.write('='*60 + '\n')

# ðŸ½ï¸ Restaurant Ordering System - Complete Guide# ðŸ½ï¸ Restaurant Ordering System



[![Django](https://img.shields.io/badge/Django-4.2.7-green.svg)](https://www.djangoproject.com/)[![Django](https://img.shields.io/badge/Django-4.2.7-green.svg)](https://www.djangoproject.com/)

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)

[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Ready-blue.svg)](https://www.postgresql.org/)[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Ready-blue.svg)](https://www.postgresql.org/)

[![Production](https://img.shields.io/badge/Status-Production%20Ready-brightgreen.svg)](http://72.62.51.225)[![License](https://img.shields.io/badge/License-Open%20Source-green.svg)](LICENSE)



A comprehensive **multi-tenant restaurant management and ordering system** with real-time order tracking, QR code ordering, kitchen management, and advanced reporting.A comprehensive **multi-tenant restaurant management and ordering system** with real-time order tracking, QR code ordering, payment processing, waste management, and advanced reporting.



**Live Demo:** [http://72.62.51.225](http://72.62.51.225)---



---## ðŸš€ Quick Deploy to DigitalOcean



## ðŸ“‘ Table of Contents**Deploy in 5 minutes with ONE command!**



- [Features](#-features)```bash

- [Quick Start](#-quick-start-local-development)ssh root@YOUR_SERVER_IP

- [Deployment](#-deployment-to-digitalocean-vps)curl -sL https://raw.githubusercontent.com/Alhajjmuhammed/Easy-Fix-Hospitality/main/deploy.sh -o deploy.sh && chmod +x deploy.sh && ./deploy.sh

- [Git Workflow](#-git-workflow-local--vps)```

- [Access Credentials](#-access-credentials)

- [Commands Cheatsheet](#-commands-cheatsheet)### ðŸ“š Deployment Documentation

- [Troubleshooting](#-troubleshooting)

- ðŸŽ¯ **[QUICKSTART.md](QUICKSTART.md)** - Deploy in 5 minutes (for beginners)

---- ðŸŽ¨ **[VISUAL_GUIDE.md](VISUAL_GUIDE.md)** - Step-by-step visual guide

- ðŸ“˜ **[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)** - Complete deployment instructions

## âœ¨ Features- âœ… **[POST_DEPLOYMENT_CHECKLIST.md](POST_DEPLOYMENT_CHECKLIST.md)** - After deployment tasks

- ðŸ“ **[COMMANDS_CHEATSHEET.md](COMMANDS_CHEATSHEET.md)** - Quick command reference

### ðŸ¢ Multi-Tenant Architecture- ðŸ“– **[DEPLOYMENT_INDEX.md](DEPLOYMENT_INDEX.md)** - Documentation overview

- âœ… Multiple restaurants on one system

- âœ… Isolated data per restaurant owner---

- âœ… QR code-based restaurant access

- âœ… Universal customer system## âœ¨ Features



### ðŸ“± Customer Features### ðŸ¢ Multi-Tenant Architecture

- âœ… QR Code Ordering - Scan table QR to access menu- Multiple restaurants on one system

- âœ… Real-time Order Tracking - Live status updates- Isolated data per restaurant

- âœ… Shopping Cart with special instructions- QR code-based restaurant access

- âœ… Order History- Custom branding per restaurant



### ðŸ‘¨â€ðŸ³ Kitchen Management### ðŸ“± Customer Experience

- âœ… Real-time Dashboard- **QR Code Ordering** - Scan table QR code to access menu

- âœ… Order Status Management- **Real-time Order Tracking** - WebSocket-powered live updates

- âœ… Order Actions (Confirm, Cancel, Update)- **Shopping Cart** - Add/remove items, special instructions

- âœ… Multi-tenant Filtering- **Order History** - View past orders

- **Mobile-Friendly** - PWA (Progressive Web App) ready

### ðŸ’° Cashier/Admin Features

- âœ… Payment Processing### ðŸ‘¨â€ðŸ³ Kitchen Management

- âœ… Sales Reports (Excel export)- **Real-time Order Display** - New orders appear instantly

- âœ… Product Management- **Order Status Management** - Update status (pending â†’ preparing â†’ ready â†’ served)

- âœ… Staff Management- **WebSocket Notifications** - Audio/visual alerts for new orders

- âœ… Happy Hour Promotions- **Preparation Time** - Estimated cooking time per item



---### ðŸ’° Payment Processing

- **Multiple Payment Methods** - Cash, card, digital, voucher

## ðŸš€ Quick Start (Local Development)- **Split Bill** - Pay for specific items

- **Void/Refund** - Transaction reversal with audit trail

### 1. Clone & Install- **Payment History** - Complete transaction log

```bash

git clone https://github.com/Alhajjmuhammed/Easy-Fix-Hospitality.git### ðŸ“Š Reports & Analytics

cd Easy-Fix-Hospitality- **Sales Reports** - Daily, weekly, monthly, custom ranges

python -m venv venv- **Product Performance** - Best sellers, revenue by product

venv\Scripts\activate  # Windows- **Category Analysis** - Performance by category

pip install -r requirements.txt- **Payment Method Breakdown** - Cash vs card vs digital

```- **Export Options** - CSV, PDF, Excel



### 2. Setup & Run### ðŸ—‘ï¸ Waste Management

```bash- **Comprehensive Tracking** - Record all food waste

python manage.py migrate- **Cost Breakdown** - Ingredient, labor, overhead costs

python manage.py createsuperuser- **Waste Reasons** - Customer refused, quality issues, kitchen errors

python manage.py runserver- **Disposal Methods** - Track how waste is handled

```- **Reports** - Waste trends and cost analysis



Visit: http://127.0.0.1:8000### â° Happy Hour Promotions

- **Time-Based Discounts** - Automatic price adjustments

---- **Day-Specific** - Configure for specific weekdays

- **Flexible Targeting** - Apply to products, categories, or subcategories

## ðŸŒ Deployment to DigitalOcean VPS- **Dynamic Pricing** - Real-time price calculation



### Quick Deploy### ðŸ‘¥ Role-Based Access Control

```bash- **Administrator** - Full system access, all restaurants

ssh root@YOUR_SERVER_IP- **Owner** - Restaurant management, staff creation

curl -sL https://raw.githubusercontent.com/Alhajjmuhammed/Easy-Fix-Hospitality/main/deploy.sh -o deploy.sh- **Kitchen Staff** - Order preparation and status updates

chmod +x deploy.sh- **Customer Care** - Customer support and order assistance

./deploy.sh- **Cashier** - Payment processing and waste recording

```- **Customer** - Browse menu and place orders



### Manual Steps---



**1. Install Dependencies:**## ðŸ› ï¸ Technology Stack

```bash

apt update && apt upgrade -y### Backend

apt install -y python3 python3-pip python3-venv postgresql nginx git- **Django 4.2.7** - Web framework

```- **PostgreSQL** - Production database

- **Channels 4.0.0** - WebSocket support

**2. Setup PostgreSQL:**- **Redis** - Caching and channel layer

```bash- **Gunicorn** - WSGI server

sudo -u postgres psql- **Daphne** - ASGI server for WebSocket

CREATE DATABASE restaurant_db;

CREATE USER restaurant_user WITH PASSWORD 'YourPassword';### Frontend

GRANT ALL PRIVILEGES ON DATABASE restaurant_db TO restaurant_user;- **Bootstrap 5.3.2** - UI framework

\q- **JavaScript** - Real-time features

```- **PWA** - Progressive Web App capabilities



**3. Clone & Configure:**### Infrastructure

```bash- **Nginx** - Web server & reverse proxy

mkdir -p /var/www/restaurant- **Systemd** - Service management

cd /var/www/restaurant- **Ubuntu 24.04 LTS** - Operating system

git clone https://github.com/Alhajjmuhammed/Easy-Fix-Hospitality.git .

python3 -m venv venv### Additional Libraries

source venv/bin/activate- **Pillow** - Image processing

pip install -r requirements.txt gunicorn psycopg2-binary python-decouple- **QRCode** - QR code generation

```- **ReportLab** - PDF generation

- **Pandas** - Data analysis

**4. Create .env:**- **OpenPyXL** - Excel export

```bash

cat > .env << EOF---

DEBUG=False

SECRET_KEY=your-secret-key## ðŸ“‹ System Requirements

ALLOWED_HOSTS=YOUR_IP

DB_NAME=restaurant_db### Minimum (Testing)

DB_USER=restaurant_user- 1 GB RAM

DB_PASSWORD=YourPassword- 25 GB Disk

DB_HOST=localhost- 1 CPU Core

DB_PORT=5432

EOF### Recommended (Production)

```- 2 GB RAM

- 50 GB Disk

**5. Migrate & Collect Static:**- 2 CPU Cores

```bash

export DJANGO_SETTINGS_MODULE=restaurant_system.production_settings---

python manage.py migrate

python manage.py collectstatic --noinput## ðŸŽ¯ Quick Start

```

### For Complete Beginners

**6. Create Gunicorn Service:**

```bash1. **Connect to your server**:

cat > /etc/systemd/system/restaurant-gunicorn.service << EOF   ```bash

[Unit]   ssh root@72.62.51.225

Description=Restaurant System Gunicorn   ```

After=network.target

2. **Run deployment script**:

[Service]   ```bash

User=root   curl -sL https://raw.githubusercontent.com/Alhajjmuhammed/Easy-Fix-Hospitality/main/deploy.sh -o deploy.sh

WorkingDirectory=/var/www/restaurant   chmod +x deploy.sh

Environment="PATH=/var/www/restaurant/venv/bin"   ./deploy.sh

Environment="DJANGO_SETTINGS_MODULE=restaurant_system.production_settings"   ```

ExecStart=/var/www/restaurant/venv/bin/gunicorn --workers 3 --bind unix:/var/www/restaurant/restaurant.sock restaurant_system.wsgi:application

3. **Create admin user**:

[Install]   ```bash

WantedBy=multi-user.target   cd /var/www/restaurant

EOF   source venv/bin/activate

   python manage.py createsuperuser

systemctl start restaurant-gunicorn   ```

systemctl enable restaurant-gunicorn

```4. **Access your website**:

   ```

**7. Configure Nginx:**   http://YOUR_SERVER_IP

```bash   ```

cat > /etc/nginx/sites-available/restaurant << EOF

server {**ðŸ“– For detailed instructions, see [QUICKSTART.md](QUICKSTART.md)**

    listen 80;

    server_name YOUR_IP;---

    

    location /static/ {## ðŸ“Š Project Structure

        alias /var/www/restaurant/staticfiles/;

    }```

    restaurant-ordering-system/

    location /media/ {â”œâ”€â”€ accounts/              # User authentication & roles

        alias /var/www/restaurant/media/;â”œâ”€â”€ admin_panel/          # Owner/admin management

    }â”œâ”€â”€ cashier/              # Payment processing

    â”œâ”€â”€ orders/               # Order management & WebSocket

    location / {â”œâ”€â”€ reports/              # Analytics & reporting

        proxy_pass http://unix:/var/www/restaurant/restaurant.sock;â”œâ”€â”€ restaurant/           # Menu & product management

        proxy_set_header Host \$host;â”œâ”€â”€ system_admin/         # System administrator functions

        proxy_set_header X-Real-IP \$remote_addr;â”œâ”€â”€ waste_management/     # Food waste tracking

    }â”œâ”€â”€ restaurant_system/    # Django project settings

}â”œâ”€â”€ templates/            # HTML templates

EOFâ”œâ”€â”€ static/              # CSS, JS, images

â”œâ”€â”€ media/               # Uploaded files

ln -s /etc/nginx/sites-available/restaurant /etc/nginx/sites-enabled/â””â”€â”€ deploy.sh            # Automated deployment script

nginx -t```

systemctl restart nginx

```---



**âœ… Done!** Visit: http://YOUR_IP## ðŸ” Security Features



---- âœ… CSRF protection

- âœ… XSS protection

## ðŸ”„ Git Workflow (Local â†” VPS)- âœ… SQL injection prevention (Django ORM)

- âœ… Secure password hashing

### âœ… Same Code Works on SQLite3 (Local) & PostgreSQL (VPS)!- âœ… Role-based access control

- âœ… Firewall configuration

### Local â†’ VPS- âœ… SSL/HTTPS ready

```bash

# 1. Develop locally (Windows + SQLite3)---

python manage.py runserver

## ðŸŒ Access Points

# 2. Push to GitHub

git add .After deployment:

git commit -m "New feature"

git push origin main| Service | URL |

|---------|-----|

# 3. Deploy to VPS| Main Website | `http://YOUR_IP/` |

ssh root@72.62.51.225| Login | `http://YOUR_IP/accounts/login/` |

cd /var/www/restaurant| Admin Panel | `http://YOUR_IP/admin-panel/` |

git pull origin main| System Admin | `http://YOUR_IP/system-admin/` |

source venv/bin/activate| Kitchen | `http://YOUR_IP/orders/kitchen/` |

python manage.py migrate| Cashier | `http://YOUR_IP/cashier/` |

python manage.py collectstatic --noinput| Reports | `http://YOUR_IP/reports/` |

systemctl restart restaurant-gunicorn

```---



### VPS â†’ Local## ðŸ”„ Updating

```bash

# 1. Hotfix on VPSWhen you push changes to GitHub:

ssh root@72.62.51.225

cd /var/www/restaurant```bash

nano orders/views.pyssh root@YOUR_SERVER_IP

git commit -am "Hotfix"cd /var/www/restaurant

git push origin maingit pull origin main

source venv/bin/activate

# 2. Pull locallypip install -r requirements.txt

git pull origin mainpython manage.py migrate

python manage.py runserverpython manage.py collectstatic --noinput

```sudo systemctl restart restaurant restaurant-daphne

```

**No code modifications needed! Django handles database differences automatically.**

---

---

## ðŸ†˜ Troubleshooting

## ðŸ” Access Credentials

### Website not loading?

### Live System: http://72.62.51.225```bash

sudo systemctl restart restaurant nginx

| Role | Username | Password | Access |curl -I http://localhost

|------|----------|----------|--------|```

| **Admin** | admin | admin123 | Full system |

| **Owner** | restaurant_a | rest123 | Restaurant A |### View logs

| **Kitchen** | kitchen_a | kitchen123 | Kitchen Dashboard |```bash

| **Customer Care** | care_a | care123 | Order Management |sudo journalctl -u restaurant -f

| **Customer** | customer_universal | customer123 | Can order from any restaurant |sudo tail -f /var/log/nginx/restaurant_error.log

```

### Creating New Users

```bash### Run health check

ssh root@72.62.51.225```bash

cd /var/www/restaurantcd /var/www/restaurant

source venv/bin/activatesudo ./health-check.sh

python manage.py shell```



from accounts.models import User, Role**ðŸ“– For more help, see [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)**

owner_role = Role.objects.get(name='owner')

User.objects.create_user(---

    username='new_restaurant',

    password='password123',## ðŸ“± Demo Flow

    role=owner_role,

    restaurant_name='My Restaurant',1. **Admin** creates restaurant owner

    restaurant_qr_code='MYREST-2024'2. **Owner** adds menu items with photos

)3. **Owner** creates tables and generates QR codes

```4. **Customer** scans QR code with phone

5. **Customer** browses menu and places order

---6. **Kitchen** receives order in real-time

7. **Kitchen** updates status as they cook

## ðŸ“ Commands Cheatsheet8. **Customer** sees live status updates

9. **Cashier** processes payment

### Local Development10. **Owner** views sales reports

```bash

python manage.py runserver              # Start server---

python manage.py makemigrations         # Create migrations

python manage.py migrate                # Apply migrations## ðŸŽ“ Documentation

python manage.py createsuperuser        # Create admin

python manage.py collectstatic          # Collect static files- **[ACCESS_GUIDE.md](ACCESS_GUIDE.md)** - User roles and access

python manage.py shell                  # Django shell- **[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)** - Full deployment instructions

```- **[COMMANDS_CHEATSHEET.md](COMMANDS_CHEATSHEET.md)** - Quick reference



### VPS Management---

```bash

# Service Control## ðŸ¤ Contributing

systemctl start restaurant-gunicorn     # Start

systemctl stop restaurant-gunicorn      # StopThis project is open for contributions. Feel free to:

systemctl restart restaurant-gunicorn   # Restart- Report bugs

systemctl status restaurant-gunicorn    # Status- Suggest features

- Submit pull requests

# Logs- Improve documentation

journalctl -u restaurant-gunicorn -f    # Service logs

tail -f /var/log/nginx/error.log        # Nginx errors---



# Deployment## ðŸ“„ License

cd /var/www/restaurant

git pull origin mainOpen Source - Free to use and modify

source venv/bin/activate

python manage.py migrate---

python manage.py collectstatic --noinput

systemctl restart restaurant-gunicorn## ðŸ™ Acknowledgments

```

Built with Django, PostgreSQL, Nginx, Redis, and Channels.

### Git Commands

```bash---

git status                              # Check status

git add .                               # Stage all## ðŸ“§ Support

git commit -m "Message"                 # Commit

git push origin main                    # Push- **Documentation**: Check the guides folder

git pull origin main                    # Pull- **Issues**: Open a GitHub issue

git log --oneline -10                   # View history- **Logs**: Use `sudo journalctl -u restaurant -f`

```

---

---

## â­ Quick Links

## ðŸ”§ Troubleshooting

- [Deploy in 5 Minutes](QUICKSTART.md)

### Orders Not Showing in Kitchen?- [Visual Step-by-Step Guide](VISUAL_GUIDE.md)

**Check filtering logic:**- [Complete Documentation](DEPLOYMENT_INDEX.md)

```python- [Command Reference](COMMANDS_CHEATSHEET.md)

# âœ… CORRECT- [Health Check Script](health-check.sh)

orders = Order.objects.filter(table_info__owner=request.user.owner)

---

# âŒ WRONG

orders = Order.objects.filter(ordered_by__owner=request.user.owner)**ðŸŽ‰ Ready to deploy? Start with [QUICKSTART.md](QUICKSTART.md)!**

```

---

### Static Files Not Loading?

```bash*Made with â¤ï¸ for Restaurant Owners*
python manage.py collectstatic --noinput
systemctl restart restaurant-gunicorn
systemctl restart nginx
```

### Database Connection Error?
```bash
cat /var/www/restaurant/.env | grep DB_
systemctl status postgresql
sudo -u postgres psql restaurant_db
```

### Service Won't Start?
```bash
systemctl status restaurant-gunicorn -l
journalctl -u restaurant-gunicorn -n 50
```

### Git Push Rejected?
```bash
git pull origin main --no-edit
git push origin main
```

---

## ðŸ†˜ Support Information

- **VPS IP:** 72.62.51.225
- **SSH:** `ssh root@72.62.51.225`
- **Project Path:** `/var/www/restaurant`
- **Repository:** [GitHub](https://github.com/Alhajjmuhammed/Easy-Fix-Hospitality)

### Database Backup
```bash
# Backup
pg_dump -U restaurant_user restaurant_db > backup_$(date +%Y%m%d).sql

# Restore
psql -U restaurant_user restaurant_db < backup.sql
```

---

## ðŸ“Š System Architecture

### Multi-Tenant Design
```
Customer (Universal) â†’ Scans QR Code â†’ Order at Table â†’ Restaurant Receives Order
                                           â†“
                                    Kitchen Dashboard
                                    (Filtered by table_info__owner)
```

### Key Relationships
- **Order belongs to Table** (table_info)
- **Table belongs to Restaurant Owner** (owner)
- **Kitchen Staff belongs to Restaurant Owner** (owner)
- **Filtering:** `table_info__owner` (NOT `ordered_by__owner`)

---

## âœ… Status

- âœ… **Local Development:** Fully functional (SQLite3)
- âœ… **Production VPS:** Deployed & operational (PostgreSQL)
- âœ… **Git Workflow:** Seamless sync
- âœ… **Multi-tenant:** Working with correct filtering
- âœ… **Kitchen Dashboard:** Tested & operational

**System is production-ready!** ðŸš€

---

**Last Updated:** October 6, 2025  
**Live Demo:** http://72.62.51.225


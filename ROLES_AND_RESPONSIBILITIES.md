# 🎭 COMPLETE ROLES & RESPONSIBILITIES GUIDE
## Easy Fix Hospitality Management System

Last Updated: January 30, 2026

---

## 📋 **TABLE OF CONTENTS**
1. [Role Overview](#role-overview)
2. [Detailed Role Permissions](#detailed-role-permissions)
3. [Access Control Matrix](#access-control-matrix)
4. [System Architecture](#system-architecture)

---

## 🎯 **ROLE OVERVIEW**

The system has **11 distinct roles** organized in a hierarchical structure:

```
┌─────────────────────────────────────────────────────────────┐
│                    ADMINISTRATOR                            │
│           (System-wide access, all restaurants)             │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┴───────────────────┐
        │                                       │
┌───────┴────────┐                    ┌────────┴────────┐
│  MAIN OWNER    │                    │  BRANCH OWNER   │
│ (Multi-branch) │────manages────────▶│  (Single loc.)  │
└────────────────┘                    └─────────────────┘
        │                                       │
        └───────────────────┬───────────────────┘
                            │
        ┌───────────────────┴───────────────────┐
        │           STAFF MEMBERS               │
        ├───────────────────────────────────────┤
        │ • Customer Care  • Cashier            │
        │ • Kitchen        • Bar                │
        │ • Buffet         • Service            │
        │ • Customer (registered guests)        │
        └───────────────────────────────────────┘
```

---

## 👥 **DETAILED ROLE PERMISSIONS**

### **1. 👑 ADMINISTRATOR** (`administrator`)

**Highest Level:** Full system access across all restaurants

**Primary Responsibilities:**
- ✅ System-wide configuration and monitoring
- ✅ Manage all restaurants, owners, and users
- ✅ Access all data across all restaurants
- ✅ View aggregated analytics and reports
- ✅ System maintenance and troubleshooting

**Access Rights:**
- 🌐 **Dashboard:** System-wide admin dashboard
- 👥 **Users:** Create/edit/delete ALL users (any restaurant)
- 🏢 **Restaurants:** Manage all restaurants and branches
- 📦 **Products:** View/manage products across all restaurants
- 📋 **Orders:** View all orders from all restaurants
- 💰 **Payments:** Access all payment records
- 📊 **Reports:** System-wide analytics and reports
- 🗑️ **Waste:** View waste records across restaurants
- ⚙️ **Settings:** System configuration and security settings

**Key Features:**
- No data filtering by owner
- Can switch between any restaurant context
- Bypass subscription checks
- Access to system_admin module

**URL Access:**
- `/secure-management-portal/` (System Admin)
- `/admin-panel/` (Admin Panel - all restaurants)
- All other modules (full access)

---

### **2. 🏢 MAIN OWNER** (`main_owner`)

**Multi-Restaurant Owner:** Can manage multiple locations/branches

**Primary Responsibilities:**
- ✅ Create and manage branches
- ✅ Assign branch owners/managers
- ✅ Set restaurant-wide policies (tax, currency, pricing)
- ✅ Hire and manage staff across all locations
- ✅ View consolidated reports from all branches
- ✅ Control subscription and billing

**Access Rights:**
- 🏢 **Branches:** Create/manage multiple branches
- 👥 **Users:** Create branch owners, staff for all locations
- 📦 **Products:** Manage menu across all branches (optional sync)
- 🍽️ **Tables:** Configure tables for all locations
- 📋 **Orders:** View orders from all owned branches
- 💰 **Payments:** Manage payments across branches
- 📊 **Reports:** Consolidated reports (all branches)
- 💳 **Subscription:** Manage billing and subscription
- ⚙️ **Settings:** Restaurant-wide configuration

**Key Features:**
- Can assign branch owners to specific locations
- Currency and tax settings apply to all branches
- Subscription controls all branches
- Auto-print settings for main restaurant

**URL Access:**
- `/admin-panel/` (Admin Dashboard)
- `/admin-panel/branches/` (Branch Management)
- `/reports/` (Main Owner Reports)
- All management modules

**Restrictions:**
- Cannot access other main owners' restaurants
- Subscription required for multi-branch access

---

### **3. 🏪 BRANCH OWNER** (`branch_owner`)

**Single Location Manager:** Manages one specific branch under main owner

**Primary Responsibilities:**
- ✅ Manage assigned branch operations
- ✅ Hire and supervise branch staff
- ✅ Monitor branch performance
- ✅ Handle local customer service
- ✅ Manage branch-specific inventory
- ✅ View branch-specific reports

**Access Rights:**
- 👥 **Users:** Create/manage staff for assigned branch only
- 📦 **Products:** Manage branch menu (may sync with main)
- 🍽️ **Tables:** Configure branch tables
- 📋 **Orders:** View/manage branch orders only
- 💰 **Payments:** Manage branch payments
- 📊 **Reports:** Branch-specific reports only
- ⚙️ **Settings:** Limited branch-level settings

**Key Features:**
- Linked to parent main owner
- Inherits currency and tax from main owner
- Can have independent auto-print settings
- Staff belong to branch context

**URL Access:**
- `/admin-panel/` (Branch Dashboard - filtered to branch)
- `/reports/` (Branch Reports)
- Management modules (branch-scoped)

**Restrictions:**
- Cannot create other branches
- Cannot modify main owner settings
- Cannot access other branches' data
- No subscription management

---

### **4. 🏛️ OWNER** (`owner`)

**Legacy Role:** Backward compatibility for existing single-restaurant owners

**Status:** Being phased out in favor of main_owner/branch_owner

**Primary Responsibilities:**
- ✅ Manage single restaurant
- ✅ Hire and manage staff
- ✅ Configure restaurant settings
- ✅ View restaurant reports

**Access Rights:**
- Same as main_owner but for single location only
- No branch creation capabilities

**Key Features:**
- Treated as main_owner in most checks
- Cannot create branches (legacy limitation)

**URL Access:**
- `/admin-panel/`
- `/reports/`
- All management modules

**Note:** New users should be created as `main_owner` or `branch_owner`

---

### **5. 🎧 CUSTOMER CARE** (`customer_care`)

**Front-Line Service:** Customer interaction and order management

**Primary Responsibilities:**
- ✅ Take customer orders (in-person, phone)
- ✅ Manage table assignments
- ✅ Update order statuses
- ✅ Handle customer inquiries and complaints
- ✅ Process order modifications
- ✅ View their own order history
- ✅ Print KOT/BOT tickets

**Access Rights:**
- 📋 **Orders:** 
  - ✅ Create new orders
  - ✅ View all restaurant orders
  - ✅ Update order status
  - ✅ Add/remove items from orders
  - ✅ Print order tickets
- 🍽️ **Tables:** View table status
- 👥 **Customers:** Basic customer info (name, table)
- 📊 **Reports:** Personal order reports only
- 💰 **Payments:** View payment status (cannot process)

**Key Features:**
- Can place orders on behalf of customers
- Auto-print KOT/BOT when enabled
- See all orders but can only modify own orders
- Cannot process payments (refer to cashier)

**URL Access:**
- `/orders/` (Order Management)
- `/orders/customer-care/reports/` (Personal Reports)
- `/cashier/` (View only - cannot process payments)

**Restrictions:**
- ❌ Cannot process payments
- ❌ Cannot manage users or products
- ❌ Cannot access admin dashboard
- ❌ Cannot modify other staff's orders
- ❌ No financial reports access

---

### **6. 💰 CASHIER** (`cashier`)

**Payment Specialist:** Financial transactions and billing

**Primary Responsibilities:**
- ✅ Process customer payments
- ✅ Issue receipts and bills
- ✅ Handle cash/card/mobile payments
- ✅ Process refunds and voids
- ✅ View payment reports
- ✅ Manage receipts printing
- ✅ Monitor unpaid orders

**Access Rights:**
- 💰 **Payments:**
  - ✅ Process payments (full/partial)
  - ✅ Void payments (with reason)
  - ✅ Issue receipts
  - ✅ Print bills
- 📋 **Orders:** View all orders (payment context)
- 📊 **Reports:** 
  - ✅ Personal cashier reports
  - ✅ Payment summaries
  - ✅ Daily cash totals
- 🧾 **Receipts:** Manage receipt printing

**Key Features:**
- Can process multiple payment methods
- Payment history tracking
- Auto-print receipts when enabled
- View all restaurant orders for payment purposes
- Can see which staff processed which payments

**URL Access:**
- `/cashier/` (Cashier Dashboard)
- `/cashier/reports/` (Cashier Reports)
- `/orders/` (View only)

**Restrictions:**
- ❌ Cannot create/modify orders
- ❌ Cannot manage products or users
- ❌ Cannot access admin dashboard
- ❌ Cannot view other cashiers' detailed reports (only aggregated)

---

### **7. 👨‍🍳 KITCHEN STAFF** (`kitchen`)

**Food Preparation:** Kitchen operations and KOT management

**Primary Responsibilities:**
- ✅ Receive Kitchen Order Tickets (KOT)
- ✅ Update order preparation status
- ✅ Mark items as prepared/ready
- ✅ Communicate with service staff
- ✅ Monitor order queue

**Access Rights:**
- 📋 **Orders:** 
  - ✅ View kitchen orders (food items only)
  - ✅ Update preparation status
  - ✅ Mark items ready for service
- 🖨️ **Printing:** Receive auto-printed KOTs

**Key Features:**
- Sees only kitchen-station items
- Real-time order updates via WebSocket
- Auto-receives KOT prints
- Status updates: Preparing → Ready

**URL Access:**
- `/orders/kitchen/` (Kitchen Dashboard)
- Limited order views

**Restrictions:**
- ❌ Cannot see bar/buffet/service items
- ❌ Cannot modify order details
- ❌ Cannot see prices or payments
- ❌ No reporting access
- ❌ No admin access

---

### **8. 🍹 BAR STAFF** (`bar`)

**Beverage Service:** Bar operations and BOT management

**Primary Responsibilities:**
- ✅ Receive Bar Order Tickets (BOT)
- ✅ Prepare drinks and beverages
- ✅ Update drink preparation status
- ✅ Monitor bar order queue

**Access Rights:**
- 📋 **Orders:** 
  - ✅ View bar orders (drinks only)
  - ✅ Update preparation status
  - ✅ Mark items ready for service
- 🖨️ **Printing:** Receive auto-printed BOTs

**Key Features:**
- Sees only bar-station items
- Real-time order updates
- Auto-receives BOT prints
- Status updates: Preparing → Ready

**URL Access:**
- `/orders/bar/` (Bar Dashboard)
- Limited order views

**Restrictions:**
- ❌ Cannot see kitchen/buffet/service items
- ❌ Cannot modify order details
- ❌ Cannot see prices or payments
- ❌ No reporting access
- ❌ No admin access

---

### **9. 🍽️ BUFFET STAFF** (`buffet`)

**Buffet Service:** Buffet operations and ticket management

**Primary Responsibilities:**
- ✅ Receive Buffet Order Tickets
- ✅ Manage buffet service
- ✅ Update buffet item status
- ✅ Monitor buffet queue

**Access Rights:**
- 📋 **Orders:** 
  - ✅ View buffet orders only
  - ✅ Update service status
  - ✅ Mark items served
- 🖨️ **Printing:** Receive auto-printed buffet tickets

**Key Features:**
- Sees only buffet-station items
- Real-time order updates
- Auto-receives buffet ticket prints

**URL Access:**
- `/orders/buffet/` (Buffet Dashboard)
- Limited order views

**Restrictions:**
- ❌ Cannot see other stations' items
- ❌ Cannot modify order details
- ❌ No financial access
- ❌ No reporting or admin access

---

### **10. 🛎️ SERVICE STAFF** (`service`)

**Table Service:** Waitstaff and service operations

**Primary Responsibilities:**
- ✅ Receive Service Order Tickets
- ✅ Serve food and drinks to tables
- ✅ Update service status
- ✅ Monitor service queue

**Access Rights:**
- 📋 **Orders:** 
  - ✅ View service orders only
  - ✅ Update service status
  - ✅ Mark items served
- 🖨️ **Printing:** Receive auto-printed service tickets

**Key Features:**
- Sees only service-station items
- Real-time order updates
- Auto-receives service ticket prints

**URL Access:**
- `/orders/service/` (Service Dashboard)
- Limited order views

**Restrictions:**
- ❌ Cannot see other stations' items
- ❌ Cannot modify order details
- ❌ No financial access
- ❌ No reporting or admin access

---

### **11. 🧑 CUSTOMER** (`customer`)

**Guest Access:** Limited customer-facing features

**Primary Responsibilities:**
- ✅ View own order history
- ✅ Check order status
- ✅ Access QR code menu

**Access Rights:**
- 📋 **Orders:** View own orders only
- 🍽️ **Menu:** Browse menu via QR code

**Key Features:**
- QR code scanning for menu access
- Order tracking
- Minimal system access

**URL Access:**
- `/menu/` (QR Code Menu)
- `/my-orders/` (Personal order history)

**Restrictions:**
- ❌ Cannot place orders directly
- ❌ No admin access
- ❌ No staff features
- ❌ Limited to own data only

---

## 📊 **ACCESS CONTROL MATRIX**

| Module/Feature | Admin | Main Owner | Branch Owner | Owner | Customer Care | Cashier | Kitchen | Bar | Buffet | Service | Customer |
|----------------|-------|------------|--------------|-------|---------------|---------|---------|-----|--------|---------|----------|
| **ADMIN PANEL** |
| Dashboard | ✅ All | ✅ All | ✅ Branch | ✅ Own | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| User Management | ✅ All | ✅ All | ✅ Branch | ✅ Own | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Product Management | ✅ All | ✅ All | ✅ Branch | ✅ Own | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Category Management | ✅ All | ✅ All | ✅ Branch | ✅ Own | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Table Management | ✅ All | ✅ All | ✅ Branch | ✅ Own | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Branch Management | ✅ All | ✅ All | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **ORDERS** |
| Create Orders | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| View All Orders | ✅ All | ✅ All | ✅ Branch | ✅ Own | ✅ Own Rest | ✅ Own Rest | ✅ Kitchen | ✅ Bar | ✅ Buffet | ✅ Service | ✅ Own |
| Update Order Status | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ Kitchen | ✅ Bar | ✅ Buffet | ✅ Service | ❌ |
| Cancel Orders | ✅ | ✅ | ✅ | ✅ | ✅ Own | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Print KOT/BOT | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Auto | Auto | Auto | Auto | ❌ |
| **PAYMENTS** |
| Process Payments | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| View Payments | ✅ All | ✅ All | ✅ Branch | ✅ Own | 👁️ View | ✅ All | ❌ | ❌ | ❌ | ❌ | ✅ Own |
| Void Payments | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Print Receipts | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **REPORTS** |
| Sales Reports | ✅ All | ✅ All | ✅ Branch | ✅ Own | ✅ Personal | ✅ Personal | ❌ | ❌ | ❌ | ❌ | ❌ |
| Payment Reports | ✅ All | ✅ All | ✅ Branch | ✅ Own | ❌ | ✅ Personal | ❌ | ❌ | ❌ | ❌ | ❌ |
| Staff Performance | ✅ All | ✅ All | ✅ Branch | ✅ Own | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Export Reports | ✅ | ✅ | ✅ | ✅ | ✅ Own | ✅ Own | ❌ | ❌ | ❌ | ❌ | ❌ |
| **WASTE MANAGEMENT** |
| Record Waste | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| View Waste Reports | ✅ All | ✅ All | ✅ Branch | ✅ Own | 👁️ View | 👁️ View | ❌ | ❌ | ❌ | ❌ | ❌ |
| **SETTINGS** |
| Restaurant Settings | ✅ All | ✅ All | ⚙️ Limited | ✅ Own | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Currency Settings | ✅ All | ✅ All | ❌ | ✅ Own | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Tax Settings | ✅ All | ✅ All | ❌ | ✅ Own | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Auto-Print Settings | ✅ All | ✅ All | ✅ Branch | ✅ Own | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Printer Settings | ✅ All | ✅ All | ✅ Branch | ✅ Own | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Profile Settings | ✅ | ✅ | ✅ | ✅ | ✅ Own | ✅ Own | ✅ Own | ✅ Own | ✅ Own | ✅ Own | ✅ Own |
| **SUBSCRIPTION** |
| Manage Subscription | ✅ All | ✅ Own | ❌ | ✅ Own | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| View Billing | ✅ All | ✅ Own | ❌ | ✅ Own | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

**Legend:**
- ✅ Full Access
- 👁️ View Only
- ⚙️ Limited Access
- ❌ No Access
- "All" = All restaurants in system
- "Own" = Own restaurant only
- "Branch" = Assigned branch only
- "Personal" = Own records only

---

## 🔐 **SYSTEM ARCHITECTURE**

### **Role Hierarchy Flow**

```python
# Role inheritance and permissions
def can_access_resource(user, resource, action):
    if user.is_administrator():
        return True  # Full access
    
    if user.is_main_owner():
        # Can access all branches they own
        return resource.owner == user
    
    if user.is_branch_owner():
        # Can only access their assigned branch
        return resource.branch == user.assigned_branch
    
    if user.is_staff():  # cashier, customer_care, etc.
        # Can access only within their owner's scope
        return resource.owner == user.get_owner()
    
    return False
```

### **Currency & Tax Inheritance**

```
Main Owner Sets:
├─ Currency: GBP (£)
├─ Tax: 8%
│
├─▶ Branch 1 (inherits £, 8%)
│   ├─ Cashier A (uses £, 8%)
│   └─ Customer Care B (uses £, 8%)
│
└─▶ Branch 2 (inherits £, 8%)
    ├─ Cashier C (uses £, 8%)
    └─ Customer Care D (uses £, 8%)
```

### **Data Filtering**

```python
# How each role sees data
Administrator:     Order.objects.all()  # Everything
Main Owner:        Order.objects.filter(table_info__owner=user)  # All branches
Branch Owner:      Order.objects.filter(table_info__restaurant=user.branch)  # Own branch
Customer Care:     Order.objects.filter(table_info__owner=user.owner)  # Owner's restaurant
Cashier:           Order.objects.filter(table_info__owner=user.owner)  # Owner's restaurant
Kitchen Staff:     Order.objects.filter(order_items__product__station='kitchen')  # Kitchen only
Customer:          Order.objects.filter(ordered_by=user)  # Own orders only
```

---

## 🎯 **COMMON WORKFLOWS**

### **1. Order Processing Workflow**

```
Customer Care → Create Order
    ↓
Auto-Print KOT → Kitchen Staff (receives, prepares)
Auto-Print BOT → Bar Staff (receives, prepares)
    ↓
Kitchen/Bar → Mark items as "Ready"
    ↓
Service Staff → Serve to customer
    ↓
Cashier → Process Payment → Print Receipt
```

### **2. Multi-Branch Setup**

```
1. Main Owner creates account
2. Sets currency, tax, restaurant name
3. Creates Branch 1, assigns Branch Owner A
4. Creates Branch 2, assigns Branch Owner B
5. Branch Owner A hires staff for Branch 1
6. Branch Owner B hires staff for Branch 2
7. Main Owner views consolidated reports from both branches
```

### **3. Staff Hierarchy Example**

```
Tropicana Restaurant (Main Owner: John)
    Currency: GBP (£)
    Tax: 8%
    
    Branch: Downtown
        Branch Owner: Sarah
        └─ Staff:
           ├─ Customer Care: Mike (takes orders)
           ├─ Cashier: Lisa (processes payments)
           ├─ Kitchen: Tom (prepares food)
           └─ Bar: Emma (prepares drinks)
    
    Branch: Airport
        Branch Owner: David
        └─ Staff:
           ├─ Customer Care: Anna
           ├─ Cashier: Bob
           ├─ Kitchen: Chris
           └─ Bar: Diana
```

---

## 📝 **NOTES**

1. **Role Assignment:** Only administrators and owners can assign roles to users

2. **Currency Inheritance:** All staff automatically use their owner's currency settings

3. **Subscription:** Main owners control subscription; branch owners depend on main owner's active subscription

4. **Auto-Print:** Each restaurant/branch can have independent auto-print settings

5. **Reports:** Staff can only see their own activity reports; owners see all staff reports

6. **Data Isolation:** Each restaurant's data is strictly isolated; only administrators can cross restaurant boundaries

7. **Legacy Support:** "Owner" role maintained for backward compatibility with existing accounts

---

## ✅ **SECURITY FEATURES**

- ✅ Role-based access control (RBAC)
- ✅ Owner-based data filtering
- ✅ Session timeout (15 minutes)
- ✅ Failed login tracking (Django Axes)
- ✅ CSRF protection
- ✅ Password hashing (Argon2)
- ✅ API token authentication (for print clients)
- ✅ Subscription-based access control

---

**END OF ROLES & RESPONSIBILITIES DOCUMENT**

For technical implementation details, see:
- `accounts/models.py` - Role model and user methods
- `accounts/views.py` - Authentication and access control
- `admin_panel/views.py` - Owner/admin functionality
- `orders/views.py` - Order processing permissions
- `cashier/views.py` - Payment processing permissions

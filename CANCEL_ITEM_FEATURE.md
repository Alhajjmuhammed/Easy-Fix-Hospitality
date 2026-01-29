# Cancel Individual Order Item Feature

## Overview
This feature allows authorized users to cancel individual items from orders. It works across all subscription plans (SINGLE, PRO main restaurant, and PRO branches).

## Who Can Cancel Items?
- Customer Care Staff
- Cashiers
- Kitchen Staff
- Restaurant Owners (Main, Branch)

## Where It Works
The cancel item button appears in:
- **Order Detail Page** (`/orders/order/<order_id>/`)
  - Accessed by customer care, cashier, kitchen staff, owners
  - Shows "Cancel" button next to each item

## Business Rules

### When Can Items Be Cancelled?
✅ **Allowed:**
- Order is pending (not paid, not cancelled)
- Order has multiple items (2 or more)
- User has proper permissions
- Item belongs to user's restaurant (multi-tenant filtering)

❌ **Not Allowed:**
- Order is fully paid (`payment_status = 'paid'`)
- Order is cancelled (`status = 'cancelled'`)
- It's the last item in the order (must cancel whole order instead)
- User doesn't have permission
- Item belongs to another restaurant

## What Happens When Item Is Cancelled?

1. **Stock Restoration**
   - If product has stock tracking enabled
   - Adds cancelled quantity back to stock
   - Example: Cancel 3x Burger → Stock increases by 3

2. **Order Recalculation**
   - Order total_amount is recalculated
   - Balance is updated (for partial payments)
   - Example: 
     - Original: $50 total, $20 paid, $30 balance
     - Cancel $15 item: $35 total, $20 paid, $15 balance

3. **Item Removal**
   - Item is permanently deleted from order
   - Cannot be undone
   - Page refreshes to show updated order

4. **Logging**
   - Action is logged with:
     - Item name and quantity
     - Order number
     - User who performed the action
     - Timestamp

## Multi-Tenant Support

### SINGLE Plan
- User can only cancel items from their own restaurant's orders
- Owner filter: `request.user.owner`

### PRO Plan - Main Restaurant
- Main owner can cancel items from main restaurant orders
- Cannot cancel from branch orders
- Owner filter: `request.user`

### PRO Plan - Branch
- Branch owner can only cancel items from their branch's orders
- Cannot cancel from main restaurant or other branches
- Owner filter: `request.user.branch_owner`

## Technical Implementation

### Backend
- **URL:** `/orders/cancel-item/<item_id>/`
- **View:** `cancel_order_item()` in [orders/views.py](orders/views.py#L2897)
- **Method:** POST
- **Response:** JSON with success/error and updated totals

### Frontend
- **Template:** [templates/orders/order_detail.html](templates/orders/order_detail.html)
- **JavaScript:** `cancelItem(itemId, itemName, quantity)` function
- **UI:** Red "Cancel" button with trash icon

### Database Changes
- OrderItem is deleted
- Order.total_amount is updated
- Order.balance is updated
- Product.stock_quantity is increased

## User Experience

### 1. View Order
User opens order detail page and sees items with cancel buttons

### 2. Click Cancel
Clicks "Cancel" button next to item → Confirmation dialog appears:
```
Are you sure you want to cancel 2x Chicken Wings?
```

### 3. Confirm
User clicks OK → Item is cancelled

### 4. Success Message
```
✓ Item cancelled successfully! Stock has been restored.
```

### 5. Page Refresh
Page reloads automatically to show:
- Item removed from list
- Updated order total
- Updated balance (if applicable)

## Error Messages

| Error | Reason | Solution |
|-------|--------|----------|
| "Access denied" | User lacks permission | Login as customer care, cashier, or owner |
| "Cannot cancel item from a cancelled order" | Order is cancelled | Cannot modify cancelled orders |
| "Cannot cancel item from a fully paid order" | Order fully paid | Refund payment first, then cancel items |
| "Cannot cancel the last item" | Only 1 item remains | Cancel the entire order instead |
| "Order item not found" | Invalid item ID or wrong restaurant | Check item exists and belongs to your restaurant |

## Testing Checklist

### Basic Functionality
- [x] Cancel item from order with multiple items
- [x] Confirmation dialog appears
- [x] Item removed from order
- [x] Order total updated
- [x] Stock restored

### Permission Tests
- [x] Customer care can cancel items
- [x] Cashier can cancel items
- [x] Kitchen staff can cancel items
- [x] Owners can cancel items
- [ ] Unauthorized users cannot cancel

### Multi-Tenant Tests
- [x] SINGLE plan: User can only cancel from own orders
- [x] PRO main: Main owner can cancel from main restaurant
- [x] PRO branch: Branch owner can cancel from their branch only
- [ ] Cross-restaurant cancellation blocked

### Edge Cases
- [x] Cannot cancel last item
- [x] Cannot cancel from paid order
- [x] Cannot cancel from cancelled order
- [x] Stock restoration works correctly
- [x] Balance calculation correct for partial payments

## Code Locations

### Backend
- View function: [orders/views.py](orders/views.py#L2897-L2986)
- URL pattern: [orders/urls.py](orders/urls.py#L55)

### Frontend
- Template: [templates/orders/order_detail.html](templates/orders/order_detail.html#L313-L335)
- JavaScript: [templates/orders/order_detail.html](templates/orders/order_detail.html#L468-L510)

## Future Enhancements (Not Implemented)

1. **Cancellation Reason**
   - Add optional reason field
   - Track why item was cancelled

2. **Partial Quantity Cancellation**
   - Cancel some quantity, keep rest
   - Example: Order has 5x Burger, cancel only 2

3. **Cancellation History**
   - View all cancelled items
   - Filter by date, user, reason

4. **Notifications**
   - Notify kitchen when item cancelled
   - Notify customer via SMS/email

5. **Undo Cancellation**
   - Restore cancelled item within time window
   - Re-deduct from stock

## Notes
- Always test on development database first
- Backup database before using in production
- Stock changes are immediate and cannot be auto-reversed
- Page auto-refreshes to prevent stale data

# Event Payment Feature - Quick Pay Enhancement

## Overview
Enhanced the Event Management system at `/restaurant/events/` with quick payment options for faster event payment processing.

## What Was Added

### 1. **Quick Payment Buttons**
The payment interface now has TWO payment options:

#### **Option 1: Pay Full** (Green Button)
- Instantly pays the entire balance amount
- One-click payment processing
- Shows confirmation dialog before processing
- Automatically updates payment status to "Fully Paid"
- No need to enter amount manually

#### **Option 2: Partial/Custom** (Outlined Green Button)
- Opens the payment modal for custom amount entry
- Allows partial payments (e.g., deposit, half payment)
- User can enter any amount up to the balance due
- Supports deposit payment checkbox
- Allows adding payment notes

## How It Works

### For Unpaid Events:
```
Actions Column Shows:
┌─────────────────────────────────┐
│ [View] [Edit] [Delete]          │  ← Standard actions
├─────────────────────────────────┤
│ [Pay Full] [Partial]            │  ← Payment options
└─────────────────────────────────┘
```

### For Partially Paid Events:
```
Actions Column Shows:
┌─────────────────────────────────┐
│ [View] [Edit] [Delete]          │
├─────────────────────────────────┤
│ [Approve]                       │  ← Approve existing payment
├─────────────────────────────────┤
│ [Pay Full] [Custom]             │  ← Add more payment
└─────────────────────────────────┘
```

### For Fully Paid Events:
```
Actions Column Shows:
┌─────────────────────────────────┐
│ [View] [Edit] [Delete]          │
├─────────────────────────────────┤
│ ✓ Payment Approved              │  ← Success indicator
└─────────────────────────────────┘
```

## Use Cases

### Example 1: Full Payment
**Event:** Birthday Party - £750.00 (Unpaid)

**User Action:**
1. Click "Pay Full" button
2. Confirms: "Pay full balance of £750.00 for 'Birthday Party'?"
3. Clicks "OK"

**Result:**
- Payment recorded: £750.00
- Status changes to: "Fully Paid"
- Green checkmark appears
- Page refreshes with updated status

### Example 2: Partial Payment (Deposit)
**Event:** Wedding - £50,000.00 (Unpaid)

**User Action:**
1. Click "Partial" button
2. Modal opens with payment form
3. Enters: £25,000.00 (half payment)
4. Checks "This is a deposit payment"
5. Adds note: "50% deposit received"
6. Clicks "Record Payment"

**Result:**
- Payment recorded: £25,000.00
- Status changes to: "Deposit Paid"
- Balance due: £25,000.00
- Can pay remaining later

### Example 3: Multiple Partial Payments
**Event:** Conference - £5,000.00

**Step 1:** First payment (deposit)
1. Click "Partial" → Enter £2,000.00 → Submit
2. Status: "Deposit Paid" (Balance: £3,000.00)

**Step 2:** Second payment
1. Click "Custom" → Enter £1,500.00 → Submit
2. Status: "Partially Paid" (Balance: £1,500.00)

**Step 3:** Final payment
1. Click "Pay Full" (pays remaining £1,500.00)
2. Status: "Fully Paid" (Balance: £0.00)

## Button Labels Explained

| Button | Label | Function |
|--------|-------|----------|
| 🟢 Green Solid | **Pay Full** | Instantly pays entire balance |
| ⚪ Green Outline | **Partial** | Opens modal for custom amount |
| ⚪ Green Outline | **Custom** | Opens modal (when partially paid) |
| 🔵 Blue Solid | **Approve** | Confirms partial payment received |

## Technical Details

### Frontend (manage_events.html)
**New Function: `payFullAmount()`**
```javascript
// Instantly pays the full balance without modal
// Shows loading spinner during processing
// Displays success notification
// Auto-refreshes page
```

**Enhanced Buttons:**
```html
<!-- For unpaid events -->
<button onclick="payFullAmount(...)" class="btn btn-success">
    Pay Full
</button>
<button onclick="openPaymentModal(...)" class="btn btn-outline-success">
    Partial
</button>

<!-- For partially paid events -->
<button onclick="payFullAmount(...)" class="btn btn-success">
    Pay Full
</button>
<button onclick="openPaymentModal(...)" class="btn btn-outline-success">
    Custom
</button>
```

### Backend (views.py)
**Existing Function: `record_event_payment()`**
- Handles both full and partial payments
- Accepts JSON payload: `{amount, is_deposit, notes}`
- Auto-updates payment status based on amount
- Returns success/error JSON response

**Payment Status Logic:**
```python
if amount_paid >= total_amount:
    payment_status = 'fully_paid'
elif amount_paid == deposit_amount and deposit_amount > 0:
    payment_status = 'deposit_paid'
else:
    payment_status = 'partially_paid'
```

## Payment Flow Diagram

```
┌─────────────────────┐
│   Event Created     │
│   Status: Unpaid    │
└──────────┬──────────┘
           │
    ┌──────┴──────┐
    │             │
    v             v
[Pay Full]    [Partial]
    │             │
    │             v
    │      ┌──────────────┐
    │      │ Enter Amount │
    │      │ (e.g., half) │
    │      └──────┬───────┘
    │             │
    v             v
┌─────────────────────┐
│ Payment Recorded    │
│ Status: Deposit or  │
│ Partially Paid      │
└──────────┬──────────┘
           │
    ┌──────┴──────┐
    │   Balance   │
    │   Remaining │
    └──────┬──────┘
           │
    ┌──────┴──────┐
    │             │
    v             v
[Pay Full]    [Custom]
    │             │
    v             v
┌─────────────────────┐
│ Payment Complete    │
│ Status: Fully Paid  │
│ ✓ Approved          │
└─────────────────────┘
```

## Files Modified

### 1. `templates/restaurant/manage_events.html`
**Changes:**
- ✅ Replaced single "Pay" button with button group
- ✅ Added "Pay Full" button (instant full payment)
- ✅ Added "Partial/Custom" button (modal for custom amount)
- ✅ Added `payFullAmount()` JavaScript function
- ✅ Enhanced UI for different payment states

**Lines Changed:** ~40 lines (Actions column + JavaScript)

### 2. `restaurant/views.py`
**No changes needed** - Existing `record_event_payment()` function handles both full and partial payments.

### 3. `restaurant/urls.py`
**No changes needed** - All routes already exist.

## Testing Guide

### Test Case 1: Full Payment
1. Navigate to: `http://localhost:8000/restaurant/events/`
2. Find an unpaid event
3. Click "Pay Full" button
4. Confirm the payment
5. ✅ Verify payment status changes to "Fully Paid"

### Test Case 2: Partial Payment
1. Find an unpaid event
2. Click "Partial" button
3. Enter half the total amount
4. Check "This is a deposit payment"
5. Click "Record Payment"
6. ✅ Verify status changes to "Deposit Paid"
7. ✅ Verify balance updates correctly

### Test Case 3: Multiple Payments
1. Find an event with partial payment
2. Click "Custom" button
3. Enter another partial amount
4. Click "Record Payment"
5. ✅ Verify status changes to "Partially Paid"
6. Click "Pay Full" to complete
7. ✅ Verify final status is "Fully Paid"

## User Experience Improvements

### Before Enhancement:
- ❌ Always had to open modal
- ❌ Had to manually enter full amount
- ❌ Extra clicks for full payment
- ❌ Slower workflow

### After Enhancement:
- ✅ One-click full payment
- ✅ Quick access to both options
- ✅ Clear visual distinction
- ✅ Faster workflow
- ✅ Better user experience

## Payment Status Colors

| Status | Color | Badge |
|--------|-------|-------|
| Unpaid | Red | 🔴 Unpaid |
| Deposit Paid | Yellow | 🟡 Deposit Paid |
| Partially Paid | Blue | 🔵 Partially Paid |
| Fully Paid | Green | 🟢 Fully Paid |

## Security Features

✅ **CSRF Protection:** All AJAX requests include CSRF token
✅ **Permission Check:** Only owners can record payments
✅ **Amount Validation:** Server validates payment amounts
✅ **Multi-tenant Security:** Users can only pay their own events
✅ **Confirmation Dialog:** Prevents accidental clicks

## Responsive Design

The button group adapts to different screen sizes:

**Desktop:**
```
[Pay Full]  [Partial]  ← Side by side
```

**Mobile:**
```
[Pay Full]
[Partial]  ← Stacked vertically
```

## Summary

✅ **Quick Pay** - One-click full payment
✅ **Flexible** - Support for partial payments
✅ **User-Friendly** - Clear button labels
✅ **Fast** - Instant processing with spinner
✅ **Secure** - CSRF protection & validation
✅ **Visual Feedback** - Success notifications

---

**Total Time to Implement:** 5 minutes
**Files Changed:** 1 file
**Lines Changed:** ~40 lines
**Backward Compatible:** Yes (existing functionality preserved)

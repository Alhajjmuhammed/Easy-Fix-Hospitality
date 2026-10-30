"""Recipe pages: ingredients per dish, food cost and margin (under Inventory)."""
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render

from .models import InventoryItem, RecipeIngredient
from . import recipes as svc
from .views import _get_currency_symbol, _require_inventory_access
from .views_purchasing import _guard, _owner


@login_required
@_guard
def recipe_list(request):
    owner = _owner(request)
    products = list(svc.products_for_owner(owner))
    ingredients = defaultdict(list)
    for ing in RecipeIngredient.objects.filter(product__in=products).select_related('item'):
        ingredients[ing.product_id].append(ing)
    stock = dict(InventoryItem.objects.filter(owner=owner).annotate(
        s=Coalesce(Sum('records__quantity_change'), Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))))
        .values_list('id', 's'))

    rows, with_recipe = [], 0
    for p in products:
        ings = ingredients.get(p.id, [])
        cost, complete = svc.recipe_cost(ings)
        if ings:
            with_recipe += 1
        rows.append({
            'product': p,
            'count': len(ings),
            'cost': cost if ings else None,
            'complete': complete,
            'margin': svc.margin_percent(p.price, cost) if ings and complete else None,
            'out_of_stock': [i.item.name for i in ings if stock.get(i.item_id, 0) <= 0],
        })
    filt = request.GET.get('show', '')
    if filt == 'missing':
        rows = [r for r in rows if not r['count']]
    elif filt == 'with':
        rows = [r for r in rows if r['count']]
    return render(request, 'inventory/recipes.html', {
        'rows': rows,
        'total': len(products),
        'with_recipe': with_recipe,
        'show': filt,
        'can_manage': _require_inventory_access(request.user, 'manage'),
        'currency_symbol': _get_currency_symbol(owner, request.user),
    })


@login_required
@_guard
def recipe_edit(request, product_id):
    owner = _owner(request)
    product = get_object_or_404(svc.products_for_owner(owner), pk=product_id)
    can_manage = _require_inventory_access(request.user, 'manage')
    if request.method == 'POST':
        if not can_manage:
            messages.error(request, "You don't have permission to change recipes.")
            return redirect('inventory:recipe_edit', product_id=product.pk)
        try:
            n = svc.save_recipe(owner, product, request.POST.getlist('item_id'), request.POST.getlist('quantity'))
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
            lines = list(zip(request.POST.getlist('item_id'), request.POST.getlist('quantity')))
            return _render_edit(request, owner, product, lines, can_manage)
        messages.success(request, f'Recipe for {product.name} saved ({n} ingredient{"s" if n != 1 else ""}).'
                         if n else f'Recipe for {product.name} cleared.')
        return redirect('inventory:recipes')
    lines = [(str(i.item_id), f'{i.quantity.normalize():f}')
             for i in RecipeIngredient.objects.filter(product=product)]
    return _render_edit(request, owner, product, lines, can_manage)


def _render_edit(request, owner, product, lines, can_manage):
    used = [l[0] for l in lines if str(l[0]).isdigit()]
    items = (InventoryItem.objects.filter(owner=owner, is_active=True) | InventoryItem.objects.filter(owner=owner, pk__in=used)) \
        .distinct().order_by('category', 'name')
    current = list(RecipeIngredient.objects.filter(product=product).select_related('item'))
    cost, complete = svc.recipe_cost(current)
    return render(request, 'inventory/recipe_edit.html', {
        'product': product,
        'items': items,
        'lines': lines or [('', '')],
        'cost': cost if current else None,
        'complete': complete,
        'margin': svc.margin_percent(product.price, cost) if current and complete else None,
        'can_manage': can_manage,
        'currency_symbol': _get_currency_symbol(owner, request.user),
    })

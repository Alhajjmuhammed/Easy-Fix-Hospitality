"""
System admin views for managing per-restaurant permissions.
Allows the system administrator to view and edit any restaurant's
RolePermissionSets and CustomRoles without logging in as that restaurant.
"""
import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.db import transaction

from accounts.models import CustomRole, Feature, RolePermissionSet, User
from accounts.permissions_defaults import DEFAULT_ROLE_FEATURES

logger = logging.getLogger(__name__)

BUILT_IN_ROLES = [
    ('manager', 'Manager'),
    ('customer_care', 'Customer Care'),
    ('kitchen', 'Kitchen'),
    ('bar', 'Bar'),
    ('buffet', 'Buffet'),
    ('service', 'Service'),
    ('cashier', 'Cashier'),
    ('delivery_rider', 'Delivery Rider'),
]


def _require_admin(request):
    return request.user.is_authenticated and request.user.is_administrator()


@login_required
def restaurant_permissions(request, restaurant_id):
    """System admin page: view/edit permissions for a specific restaurant owner."""
    if not _require_admin(request):
        from django.contrib import messages as _m
        _m.error(request, 'Access denied.')
        return redirect('system_admin:dashboard')

    owner = get_object_or_404(
        User,
        pk=restaurant_id,
        role__name__in=['owner', 'main_owner', 'branch_owner'],
    )

    features = Feature.objects.all().order_by('category', 'name')
    features_by_category = {}
    for f in features:
        features_by_category.setdefault(f.get_category_display(), []).append(f)

    # Ensure all 8 role permission sets exist; auto-seed defaults on first create
    feature_cache = {f.slug: f for f in features}
    role_sets_json_data = {}
    for role_name, _ in BUILT_IN_ROLES:
        rps, created = RolePermissionSet.objects.get_or_create(owner=owner, role_name=role_name)
        if created:
            defaults = DEFAULT_ROLE_FEATURES.get(role_name, [])
            rps.features.set([feature_cache[s] for s in defaults if s in feature_cache])
        role_sets_json_data[role_name] = list(rps.features.values_list('slug', flat=True))

    role_sets_json = json.dumps(role_sets_json_data)

    custom_roles = CustomRole.objects.filter(owner=owner).prefetch_related('features')

    # Build custom roles JSON for JS
    custom_roles_data = [
        {
            'id': cr.pk,
            'name': cr.name,
            'description': cr.description,
            'feature_slugs': list(cr.features.values_list('slug', flat=True)),
            'assigned_count': cr.assigned_users.count(),
        }
        for cr in custom_roles
    ]
    custom_roles_json = json.dumps(custom_roles_data)

    staff = (
        User.objects.filter(owner=owner)
        .select_related('role', 'custom_role')
        .exclude(role__name__in=['owner', 'main_owner', 'branch_owner'])
        .order_by('username')
    )

    context = {
        'owner': owner,
        'features': features,
        'features_by_category': features_by_category,
        'role_sets_json': role_sets_json,
        'custom_roles': custom_roles,
        'custom_roles_json': custom_roles_json,
        'staff': staff,
        'built_in_roles': BUILT_IN_ROLES,
        'restaurant_id': restaurant_id,
    }
    return render(request, 'system_admin/restaurant_permissions.html', context)


@login_required
def admin_save_role_permissions(request, restaurant_id):
    """AJAX: system admin saves a role's feature set for a restaurant."""
    if not _require_admin(request):
        return JsonResponse({'error': 'Access denied'}, status=403)

    owner = get_object_or_404(
        User,
        pk=restaurant_id,
        role__name__in=['owner', 'main_owner', 'branch_owner'],
    )

    try:
        data = json.loads(request.body)
        role_name = data.get('role_name', '')
        slugs = data.get('feature_slugs', [])

        valid_roles = [r for r, _ in BUILT_IN_ROLES]
        if role_name not in valid_roles:
            return JsonResponse({'error': 'Invalid role'}, status=400)

        with transaction.atomic():
            rps, _ = RolePermissionSet.objects.get_or_create(owner=owner, role_name=role_name)
            features = Feature.objects.filter(slug__in=slugs)
            rps.features.set(features)
            rps.updated_by = request.user
            rps.save(update_fields=['updated_at', 'updated_by'])

        return JsonResponse({'success': True, 'count': features.count()})
    except Exception:
        logger.exception('admin_save_role_permissions error')
        return JsonResponse({'error': 'Server error'}, status=500)


@login_required
def admin_create_custom_role(request, restaurant_id):
    """AJAX: system admin creates or updates a custom role for a restaurant."""
    if not _require_admin(request):
        return JsonResponse({'error': 'Access denied'}, status=403)

    owner = get_object_or_404(
        User,
        pk=restaurant_id,
        role__name__in=['owner', 'main_owner', 'branch_owner'],
    )

    try:
        data = json.loads(request.body)
        name = (data.get('name') or '').strip()
        description = (data.get('description') or '').strip()
        slugs = data.get('feature_slugs', [])
        role_id = data.get('role_id')

        if not name:
            return JsonResponse({'error': 'Name is required'}, status=400)

        with transaction.atomic():
            if role_id:
                cr = get_object_or_404(CustomRole, pk=role_id, owner=owner)
                cr.name = name
                cr.description = description
                cr.save(update_fields=['name', 'description', 'updated_at'])
            else:
                cr = CustomRole.objects.create(owner=owner, name=name, description=description)

            features = Feature.objects.filter(slug__in=slugs)
            cr.features.set(features)

        return JsonResponse({
            'success': True,
            'role': {
                'id': cr.pk,
                'name': cr.name,
                'description': cr.description,
                'feature_slugs': list(cr.features.values_list('slug', flat=True)),
            },
        })
    except Exception:
        logger.exception('admin_create_custom_role error')
        return JsonResponse({'error': 'Server error'}, status=500)


@login_required
def admin_delete_custom_role(request, restaurant_id):
    """AJAX: system admin deletes a custom role for a restaurant."""
    if not _require_admin(request):
        return JsonResponse({'error': 'Access denied'}, status=403)

    owner = get_object_or_404(
        User,
        pk=restaurant_id,
        role__name__in=['owner', 'main_owner', 'branch_owner'],
    )

    try:
        data = json.loads(request.body)
        role_id = data.get('role_id')
        cr = get_object_or_404(CustomRole, pk=role_id, owner=owner)

        assigned_count = cr.assigned_users.count()
        if assigned_count:
            return JsonResponse(
                {'error': f'Cannot delete: {assigned_count} staff member(s) still assigned to this role. Unassign them first.'},
                status=400,
            )

        cr.delete()
        return JsonResponse({'success': True})
    except Exception:
        logger.exception('admin_delete_custom_role error')
        return JsonResponse({'error': 'Server error'}, status=500)


@login_required
def admin_assign_custom_role(request, restaurant_id):
    """AJAX: system admin assigns (or removes) a custom role from a staff member."""
    if not _require_admin(request):
        return JsonResponse({'error': 'Access denied'}, status=403)

    owner = get_object_or_404(
        User,
        pk=restaurant_id,
        role__name__in=['owner', 'main_owner', 'branch_owner'],
    )

    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        custom_role_id = data.get('custom_role_id')  # None to clear

        staff_user = get_object_or_404(User, pk=user_id, owner=owner)

        if custom_role_id:
            cr = get_object_or_404(CustomRole, pk=custom_role_id, owner=owner)
            staff_user.custom_role = cr
        else:
            staff_user.custom_role = None

        staff_user.save(update_fields=['custom_role'])
        return JsonResponse({'success': True})
    except Exception:
        logger.exception('admin_assign_custom_role error')
        return JsonResponse({'error': 'Server error'}, status=500)


@login_required
def admin_reset_to_defaults(request, restaurant_id):
    """AJAX: system admin resets all role permissions for a restaurant to defaults."""
    if not _require_admin(request):
        return JsonResponse({'error': 'Access denied'}, status=403)

    owner = get_object_or_404(
        User,
        pk=restaurant_id,
        role__name__in=['owner', 'main_owner', 'branch_owner'],
    )

    try:
        feature_cache = {f.slug: f for f in Feature.objects.all()}
        with transaction.atomic():
            for role_name, defaults in DEFAULT_ROLE_FEATURES.items():
                rps, _ = RolePermissionSet.objects.get_or_create(owner=owner, role_name=role_name)
                feature_objs = [feature_cache[s] for s in defaults if s in feature_cache]
                rps.features.set(feature_objs)
                rps.updated_by = request.user
                rps.save(update_fields=['updated_at', 'updated_by'])

        return JsonResponse({'success': True})
    except Exception:
        logger.exception('admin_reset_to_defaults error')
        return JsonResponse({'error': 'Server error'}, status=500)

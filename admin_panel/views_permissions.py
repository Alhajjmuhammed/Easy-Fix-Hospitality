import json
import logging

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST

from accounts.models import CustomRole, Feature, RolePermissionSet, User
from accounts.permissions_defaults import DEFAULT_ROLE_FEATURES

logger = logging.getLogger(__name__)

_BUILT_IN_ROLES = [
    ('manager', 'Manager'),
    ('customer_care', 'Customer Care'),
    ('kitchen', 'Kitchen'),
    ('bar', 'Bar'),
    ('buffet', 'Buffet'),
    ('service', 'Service'),
    ('cashier', 'Cashier'),
    ('delivery_rider', 'Delivery Rider'),
]

_CATEGORY_LABELS = {
    'orders': 'Orders',
    'payments': 'Payments',
    'station': 'Station Dashboards',
    'menu': 'Menu Management',
    'staff': 'Staff',
    'reports': 'Reports',
    'operations': 'Operations',
}


def _require_owner(user):
    return user.role and user.role.name in ('owner', 'main_owner', 'branch_owner')


@login_required
def roles_permissions_view(request):
    if not _require_owner(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Only restaurant owners can manage permissions.')

    all_features = Feature.objects.all().order_by('category', 'name')

    features_by_category = {}
    for f in all_features:
        label = _CATEGORY_LABELS.get(f.category, f.category.title())
        features_by_category.setdefault(label, []).append(f)

    feature_cache = {f.slug: f for f in all_features}
    role_sets = {}
    with transaction.atomic():
        for role_name, _ in _BUILT_IN_ROLES:
            rps, created = RolePermissionSet.objects.get_or_create(
                owner=request.user,
                role_name=role_name,
            )
            if created:
                defaults = DEFAULT_ROLE_FEATURES.get(role_name, [])
                rps.features.set([feature_cache[s] for s in defaults if s in feature_cache])
            role_sets[role_name] = set(rps.features.values_list('slug', flat=True))

    custom_roles = CustomRole.objects.filter(owner=request.user).prefetch_related('features').order_by('name')

    staff = (
        User.objects.filter(owner=request.user)
        .exclude(role__name__in=['owner', 'main_owner', 'branch_owner'])
        .select_related('role', 'custom_role')
        .order_by('username')
    )

    role_sets_json = json.dumps({k: list(v) for k, v in role_sets.items()})

    custom_roles_with_slugs = [
        {
            'id': cr.pk,
            'name': cr.name,
            'description': cr.description,
            'feature_slugs': list(cr.features.values_list('slug', flat=True)),
            'assigned_count': cr.assigned_users.count(),
        }
        for cr in custom_roles
    ]
    custom_roles_json = json.dumps(custom_roles_with_slugs)

    return render(request, 'admin_panel/roles_permissions.html', {
        'all_features': all_features,
        'features_by_category': features_by_category,
        'role_sets': role_sets,
        'role_sets_json': role_sets_json,
        'custom_roles': custom_roles,
        'custom_roles_json': custom_roles_json,
        'staff': staff,
        'built_in_roles': _BUILT_IN_ROLES,
    })


@login_required
@require_POST
def save_role_permissions(request):
    if not _require_owner(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    try:
        data = json.loads(request.body)
        role_name = data.get('role_name', '').strip()
        feature_slugs = data.get('feature_slugs', [])

        valid_roles = [r[0] for r in _BUILT_IN_ROLES]
        if role_name not in valid_roles:
            return JsonResponse({'success': False, 'error': 'Invalid role name.'}, status=400)

        features = Feature.objects.filter(slug__in=feature_slugs)

        with transaction.atomic():
            rps, _ = RolePermissionSet.objects.get_or_create(
                owner=request.user,
                role_name=role_name,
            )
            rps.features.set(features)
            rps.updated_by = request.user
            rps.save(update_fields=['updated_by', 'updated_at'])

        return JsonResponse({'success': True, 'count': features.count()})

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning('save_role_permissions bad request: %s', e)
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)


@login_required
@require_POST
def create_custom_role(request):
    if not _require_owner(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        feature_slugs = data.get('feature_slugs', [])
        role_id = data.get('role_id')

        if not name:
            return JsonResponse({'success': False, 'error': 'Role name is required.'}, status=400)

        features = Feature.objects.filter(slug__in=feature_slugs)

        with transaction.atomic():
            if role_id:
                role = get_object_or_404(CustomRole, pk=role_id, owner=request.user)
                role.name = name
                role.description = description
                role.save(update_fields=['name', 'description', 'updated_at'])
                role.features.set(features)
            else:
                if CustomRole.objects.filter(owner=request.user, name=name).exists():
                    return JsonResponse({'success': False, 'error': f'A custom role named "{name}" already exists.'}, status=400)
                role = CustomRole.objects.create(
                    owner=request.user,
                    name=name,
                    description=description,
                )
                role.features.set(features)

        return JsonResponse({
            'success': True,
            'role': {
                'id': role.pk,
                'name': role.name,
                'description': role.description,
                'feature_slugs': list(role.features.values_list('slug', flat=True)),
            },
        })

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning('create_custom_role bad request: %s', e)
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)


@login_required
@require_POST
def delete_custom_role(request):
    if not _require_owner(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    try:
        data = json.loads(request.body)
        role_id = data.get('role_id')
        role = get_object_or_404(CustomRole, pk=role_id, owner=request.user)

        assigned_count = role.assigned_users.count()
        if assigned_count:
            return JsonResponse({
                'success': False,
                'error': f'Cannot delete: {assigned_count} staff member(s) are still assigned to this role. Reassign them first.',
            }, status=400)

        role.delete()
        return JsonResponse({'success': True})

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning('delete_custom_role bad request: %s', e)
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)


@login_required
@require_POST
def assign_custom_role(request):
    if not _require_owner(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        custom_role_id = data.get('custom_role_id')

        staff_member = get_object_or_404(
            User,
            pk=user_id,
            owner=request.user,
        )

        if custom_role_id:
            custom_role = get_object_or_404(CustomRole, pk=custom_role_id, owner=request.user)
            staff_member.custom_role = custom_role
        else:
            staff_member.custom_role = None

        staff_member.save(update_fields=['custom_role'])
        return JsonResponse({'success': True})

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning('assign_custom_role bad request: %s', e)
        return JsonResponse({'success': False, 'error': 'Invalid request.'}, status=400)

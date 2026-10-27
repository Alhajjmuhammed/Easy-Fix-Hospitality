from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.auth.hashers import make_password
from django.db import transaction

from accounts.models import User, Role, AdminSectionPermission

SECTIONS = [
    ('dashboard',   'Dashboard',       'fas fa-tachometer-alt'),
    ('restaurants', 'Restaurants',     'fas fa-store'),
    ('users',       'User Management', 'fas fa-users'),
    ('statistics',  'Statistics',      'fas fa-chart-bar'),
    ('orders',      'Orders',          'fas fa-clipboard-list'),
    ('categories',  'Categories',      'fas fa-tags'),
    ('products',    'Products',        'fas fa-box'),
    ('tables',      'Tables',          'fas fa-chair'),
    ('riders',      'Delivery Riders', 'fas fa-motorcycle'),
]
SECTION_KEYS = [s[0] for s in SECTIONS]


def _admin_only(request):
    """Returns True if the request is from the main administrator."""
    return request.user.is_authenticated and request.user.is_administrator()


@login_required
def admin_staff_list(request):
    if not _admin_only(request):
        messages.error(request, 'Access denied.')
        return redirect('system_admin:dashboard')

    staff_list = User.objects.filter(
        role__name='admin_staff'
    ).select_related('role').prefetch_related('admin_section_permissions').order_by('date_joined')

    # Annotate each staff member with a quick permission summary
    for staff in staff_list:
        perms = {p.section: p for p in staff.admin_section_permissions.all()}
        staff.perm_summary = []
        for key, label, icon in SECTIONS:
            p = perms.get(key)
            actions = []
            if p:
                if p.can_view:   actions.append('View')
                if p.can_create: actions.append('Create')
                if p.can_edit:   actions.append('Edit')
                if p.can_delete: actions.append('Delete')
            staff.perm_summary.append((key, label, icon, actions))

    context = {
        'staff_list': staff_list,
        'sections': SECTIONS,
    }
    return render(request, 'system_admin/admin_staff.html', context)


@login_required
@transaction.atomic
def create_admin_staff(request):
    if not _admin_only(request):
        return JsonResponse({'error': 'Access denied.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required.'}, status=405)

    username    = request.POST.get('username', '').strip()
    first_name  = request.POST.get('first_name', '').strip()
    last_name   = request.POST.get('last_name', '').strip()
    email       = request.POST.get('email', '').strip()
    password    = request.POST.get('password', '')

    if not username or not password:
        messages.error(request, 'Username and password are required.')
        return redirect('system_admin:admin_staff_list')

    if User.objects.filter(username=username).exists():
        messages.error(request, f'Username "{username}" is already taken.')
        return redirect('system_admin:admin_staff_list')

    role, _ = Role.objects.get_or_create(
        name='admin_staff',
        defaults={'description': 'System Admin Staff'}
    )

    User.objects.create(
        username=username,
        first_name=first_name,
        last_name=last_name,
        email=email,
        password=make_password(password),
        role=role,
        is_active=True,
    )
    messages.success(request, f'Admin staff member "{username}" created successfully.')
    return redirect('system_admin:admin_staff_list')


@login_required
@transaction.atomic
def edit_admin_staff(request, staff_id):
    if not _admin_only(request):
        return JsonResponse({'error': 'Access denied.'}, status=403)

    staff = get_object_or_404(User, id=staff_id, role__name='admin_staff')

    if request.method == 'POST':
        staff.first_name = request.POST.get('first_name', '').strip()
        staff.last_name  = request.POST.get('last_name', '').strip()
        staff.email      = request.POST.get('email', '').strip()
        new_password     = request.POST.get('password', '').strip()
        if new_password:
            staff.password = make_password(new_password)
        active = request.POST.get('is_active') == 'on'
        staff.is_active = active
        staff.save()
        messages.success(request, f'Staff member "{staff.username}" updated.')
        return redirect('system_admin:admin_staff_list')

    return JsonResponse({'error': 'POST required.'}, status=405)


@login_required
@transaction.atomic
def delete_admin_staff(request, staff_id):
    if not _admin_only(request):
        return JsonResponse({'error': 'Access denied.'}, status=403)

    staff = get_object_or_404(User, id=staff_id, role__name='admin_staff')
    username = staff.username
    staff.delete()
    messages.success(request, f'Staff member "{username}" deleted.')
    return redirect('system_admin:admin_staff_list')


@login_required
@transaction.atomic
def save_staff_permissions(request, staff_id):
    if not _admin_only(request):
        return JsonResponse({'error': 'Access denied.'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required.'}, status=405)

    staff = get_object_or_404(User, id=staff_id, role__name='admin_staff')

    for section_key in SECTION_KEYS:
        perm, _ = AdminSectionPermission.objects.get_or_create(
            staff=staff, section=section_key
        )
        perm.can_view   = request.POST.get(f'{section_key}_view')   == '1'
        perm.can_create = request.POST.get(f'{section_key}_create') == '1'
        perm.can_edit   = request.POST.get(f'{section_key}_edit')   == '1'
        perm.can_delete = request.POST.get(f'{section_key}_delete') == '1'
        perm.save()

    return JsonResponse({'ok': True})

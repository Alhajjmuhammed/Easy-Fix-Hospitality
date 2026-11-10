"""Small database helpers shared by the web and API views."""
from django.http import Http404


def locked_get(queryset, **lookup):
    """Lock and return the ONE row of `queryset` matching `lookup`, or raise Http404.

    Access filters here are often OR'd joins (tables, branch owners, managed restaurants) that
    can return the same row several times, and PostgreSQL refuses SELECT DISTINCT ... FOR UPDATE.
    So: find the id through the filtered queryset first (duplicates don't matter), then lock
    that single row by primary key."""
    pk = queryset.filter(**lookup).values_list('pk', flat=True).first()
    if pk is None:
        raise Http404('Not found')
    return queryset.model.objects.select_for_update(of=('self',)).get(pk=pk)


def managed_owner_ids(main_owner):
    """Subquery: the operator (branch_owner) ids of every restaurant `main_owner` controls.

    Use `ordered_by__owner__in=managed_owner_ids(owner)` instead of
    `ordered_by__owner__managed_restaurant__main_owner=owner`. That reverse join repeats each
    row once per restaurant the operator manages, so a main owner who also runs a branch
    himself saw every order/payment twice (doubled sums, MultipleObjectsReturned on .get()).
    A subquery matches the same rows without joining, so it can never repeat them."""
    from restaurant.models_restaurant import Restaurant
    return Restaurant.objects.filter(main_owner=main_owner, branch_owner__isnull=False).values('branch_owner')

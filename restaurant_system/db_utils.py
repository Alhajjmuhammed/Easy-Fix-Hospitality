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

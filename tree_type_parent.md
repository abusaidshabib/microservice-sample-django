Here's the complete implementation — model, services, serializer, and views.

---

### models.py

```python
from django.db import models


class Company(models.Model):
    name       = models.CharField(max_length=255, db_index=True)
    is_active  = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "company"

    def get_tree(self):
        """Return this node and all descendants as a nested dict (2 queries)."""
        rows = (
            CompanyClosure.objects
            .filter(ancestor=self, depth__gt=0)
            .select_related("descendant")
        )
        nodes = {
            self.id: {
                "id": self.id,
                "name": self.name,
                "is_active": self.is_active,
                "children": [],
            }
        }
        for row in rows:
            d = row.descendant
            nodes[d.id] = {
                "id": d.id,
                "name": d.name,
                "is_active": d.is_active,
                "children": [],
            }
        direct = (
            CompanyClosure.objects
            .filter(descendant_id__in=nodes.keys(), depth=1)
            .values("ancestor_id", "descendant_id")
        )
        for row in direct:
            parent = nodes.get(row["ancestor_id"])
            child  = nodes.get(row["descendant_id"])
            if parent and child:
                parent["children"].append(child)

        return nodes[self.id]

    def __str__(self):
        return self.name


class CompanyClosure(models.Model):
    ancestor   = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="ancestor_set"
    )
    descendant = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="descendant_set"
    )
    depth = models.PositiveIntegerField()

    class Meta:
        db_table = "company_closure"
        unique_together = ("ancestor", "descendant")
        indexes = [
            models.Index(fields=["ancestor", "depth"]),
            models.Index(fields=["descendant"]),
        ]
```

---

### services.py

```python
from django.db import transaction
from .models import Company, CompanyClosure


@transaction.atomic
def create_root(name):
    """Create a top-level company."""
    company = Company.objects.create(name=name)
    CompanyClosure.objects.create(ancestor=company, descendant=company, depth=0)
    return company


@transaction.atomic
def create_child(parent_id, name):
    """Create a child under an existing company."""
    try:
        parent = Company.objects.get(id=parent_id)
    except Company.DoesNotExist:
        return None

    child = Company.objects.create(name=name)

    # Self-reference
    CompanyClosure.objects.create(ancestor=child, descendant=child, depth=0)

    # Copy all ancestor paths from parent, increment depth
    parent_rows = CompanyClosure.objects.filter(descendant=parent)
    CompanyClosure.objects.bulk_create([
        CompanyClosure(
            ancestor=row.ancestor,
            descendant=child,
            depth=row.depth + 1,
        )
        for row in parent_rows
    ])
    return child


@transaction.atomic
def create_nested(data, parent_id=None):
    """
    Recursively create companies from a nested dict.

    data = {
        "name": "Global Corp",
        "children": [
            {
                "name": "EMEA",
                "children": [
                    {"name": "Germany", "children": []},
                    {"name": "France",  "children": []},
                ]
            }
        ]
    }
    """
    if parent_id is None:
        company = create_root(data["name"])
    else:
        company = create_child(parent_id, data["name"])

    for child_data in data.get("children", []):
        create_nested(child_data, parent_id=company.id)

    return company


def get_all_roots():
    """
    Return all root companies (no parent) each with full nested tree.
    Fetches roots in 1 query, then get_tree() per root = 2 queries each.
    """
    root_ids = (
        CompanyClosure.objects
        .filter(depth=0)
        .exclude(
            descendant_id__in=CompanyClosure.objects
            .filter(depth=1)
            .values("descendant_id")
        )
        .values_list("ancestor_id", flat=True)
    )
    roots = Company.objects.filter(id__in=root_ids)
    return [company.get_tree() for company in roots]


def get_children(company_id):
    """Direct children only."""
    return list(
        CompanyClosure.objects
        .filter(ancestor_id=company_id, depth=1)
        .select_related("descendant")
        .values("descendant__id", "descendant__name", "descendant__is_active")
    )


def get_ancestors(company_id):
    """All ancestors from root down to direct parent."""
    return list(
        CompanyClosure.objects
        .filter(descendant_id=company_id, depth__gt=0)
        .select_related("ancestor")
        .order_by("-depth")
        .values("ancestor__id", "ancestor__name")
    )


@transaction.atomic
def delete_company(company_id):
    """Delete a company and all its descendants."""
    descendant_ids = list(
        CompanyClosure.objects
        .filter(ancestor_id=company_id, depth__gt=0)
        .values_list("descendant_id", flat=True)
    )
    descendant_ids.append(company_id)
    Company.objects.filter(id__in=descendant_ids).delete()
```

---

### serializers.py

```python
from rest_framework import serializers
from .models import Company


class CompanyTreeSerializer(serializers.Serializer):
    """Serializes the dict returned by company.get_tree() — recursive."""
    id       = serializers.IntegerField()
    name     = serializers.CharField()
    is_active = serializers.BooleanField()
    children = serializers.SerializerMethodField()

    def get_children(self, obj):
        return CompanyTreeSerializer(obj["children"], many=True).data


class CompanyCreateSerializer(serializers.Serializer):
    name      = serializers.CharField(max_length=255)
    parent_id = serializers.IntegerField(required=False, allow_null=True)


class CompanyNestedCreateSerializer(serializers.Serializer):
    """For bulk nested creation from a single payload."""
    name     = serializers.CharField(max_length=255)
    children = serializers.ListField(child=serializers.DictField(), default=list)
```

---

### views.py

```python
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Company
from .serializers import CompanyTreeSerializer, CompanyCreateSerializer, CompanyNestedCreateSerializer
from .services import (
    create_root, create_child, create_nested,
    get_all_roots, get_children, get_ancestors, delete_company
)


class CompanyListView(APIView):
    def get(self, request):
        """Return all root companies, each with full nested tree."""
        trees = get_all_roots()
        return Response(CompanyTreeSerializer(trees, many=True).data)

    def post(self, request):
        """Create a single company (root or child)."""
        serializer = CompanyCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        parent_id = serializer.validated_data.get("parent_id")
        name      = serializer.validated_data["name"]

        if parent_id:
            company = create_child(parent_id, name)
            if not company:
                return Response(
                    {"error": f"Parent {parent_id} not found"},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            company = create_root(name)

        return Response(
            {"id": company.id, "name": company.name},
            status=status.HTTP_201_CREATED
        )


class CompanyNestedCreateView(APIView):
    def post(self, request):
        """
        Create an entire nested hierarchy in one request.

        POST /api/companies/nested/
        {
            "name": "Global Corp",
            "children": [
                {
                    "name": "EMEA",
                    "children": [
                        {"name": "Germany", "children": []},
                        {"name": "France",  "children": []}
                    ]
                }
            ]
        }
        """
        serializer = CompanyNestedCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        root = create_nested(request.data)
        return Response(root.get_tree(), status=status.HTTP_201_CREATED)


class CompanyDetailView(APIView):
    def get(self, request, company_id):
        """Return a single company with its full nested subtree."""
        try:
            company = Company.objects.get(id=company_id)
        except Company.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(CompanyTreeSerializer(company.get_tree()).data)

    def delete(self, request, company_id):
        """Delete a company and all its descendants."""
        try:
            Company.objects.get(id=company_id)
        except Company.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        delete_company(company_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CompanyChildrenView(APIView):
    def get(self, request, company_id):
        """Return only direct children (flat, fast)."""
        children = get_children(company_id)
        return Response(children)


class CompanyAncestorsView(APIView):
    def get(self, request, company_id):
        """Return breadcrumb path from root to this company."""
        ancestors = get_ancestors(company_id)
        return Response(ancestors)
```

---

### urls.py

```python
from django.urls import path
from . import views

urlpatterns = [
    path("companies/",                       views.CompanyListView.as_view()),
    path("companies/nested/",                views.CompanyNestedCreateView.as_view()),
    path("companies/<int:company_id>/",      views.CompanyDetailView.as_view()),
    path("companies/<int:company_id>/children/",  views.CompanyChildrenView.as_view()),
    path("companies/<int:company_id>/ancestors/", views.CompanyAncestorsView.as_view()),
]
```

---

### API summary

| Method | URL | What it returns |
|---|---|---|
| `GET` | `/companies/` | All roots with full nested trees |
| `POST` | `/companies/` | Create one company (root or child) |
| `POST` | `/companies/nested/` | Create full hierarchy from one payload |
| `GET` | `/companies/1/` | Company 1 + full subtree |
| `DELETE` | `/companies/1/` | Delete company 1 + all descendants |
| `GET` | `/companies/1/children/` | Direct children only (fast, flat) |
| `GET` | `/companies/1/ancestors/` | Breadcrumb path from root |
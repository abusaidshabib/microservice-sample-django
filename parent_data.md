## Without a Package: Closure Table

The best no-package option for fast reads. Store every ancestor-descendant pair in a separate table — all reads are a single query with no recursion.

---

### Models

```python
# models.py
from django.db import models


class Company(models.Model):
    name      = models.CharField(max_length=255, db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "company"

    def __str__(self):
        return self.name


class CompanyClosure(models.Model):
    ancestor   = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="ancestor_set"
    )
    descendant = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="descendant_set"
    )
    depth = models.PositiveIntegerField()  # 0 = self, 1 = child, 2 = grandchild

    class Meta:
        db_table = "company_closure"
        unique_together = ("ancestor", "descendant")
        indexes = [
            models.Index(fields=["ancestor", "depth"]),
            models.Index(fields=["descendant"]),
        ]
```

---

### Tree Operations (pure Django ORM)

```python
# services.py
from .models import Company, CompanyClosure


def add_root(name):
    """Create a top-level company with no parent."""
    company = Company.objects.create(name=name)
    # Every node must have a self-referencing row at depth 0
    CompanyClosure.objects.create(ancestor=company, descendant=company, depth=0)
    return company


def add_child(parent, name):
    """Create a child company under parent."""
    child = Company.objects.create(name=name)

    # 1. Self-reference for the new child
    CompanyClosure.objects.create(ancestor=child, descendant=child, depth=0)

    # 2. Copy all ancestor rows from parent, increase depth by 1
    parent_ancestors = CompanyClosure.objects.filter(descendant=parent)
    CompanyClosure.objects.bulk_create([
        CompanyClosure(
            ancestor=row.ancestor,
            descendant=child,
            depth=row.depth + 1
        )
        for row in parent_ancestors
    ])
    return child


def get_descendants(company, depth=None):
    """All nodes below company. Optionally filter by exact depth."""
    qs = CompanyClosure.objects.filter(
        ancestor=company, depth__gt=0
    ).select_related("descendant")
    if depth is not None:
        qs = qs.filter(depth=depth)
    return [row.descendant for row in qs]


def get_ancestors(company):
    """All nodes above company, ordered from root down."""
    return [
        row.ancestor
        for row in CompanyClosure.objects.filter(
            descendant=company, depth__gt=0
        ).select_related("ancestor").order_by("-depth")
    ]


def get_children(company):
    """Direct children only (depth=1)."""
    return get_descendants(company, depth=1)


def delete_company(company):
    """Delete a company and all its descendants."""
    descendant_ids = [c.id for c in get_descendants(company)]
    descendant_ids.append(company.id)
    Company.objects.filter(id__in=descendant_ids).delete()
    # Closure rows are deleted automatically via CASCADE
```

---

### ERD

```
┌───────────────────────────┐
│         company           │
├───────────────────────────┤
│ PK  id          INT       │
│     name        VARCHAR   │
│     is_active   BOOLEAN   │
│     created_at  DATETIME  │
└────────────┬──────────────┘
             │ 1
             │              (ancestor_id → company.id)
             │  many         (descendant_id → company.id)
             ▼
┌───────────────────────────────────┐
│         company_closure           │
├───────────────────────────────────┤
│ PK  id             INT            │
│ FK  ancestor_id    INT ──────────►│ company.id
│ FK  descendant_id  INT ──────────►│ company.id
│     depth          INT            │
│                                   │
│ UNIQUE (ancestor_id, descendant_id)│
│ INDEX  (ancestor_id, depth)       │
│ INDEX  (descendant_id)            │
└───────────────────────────────────┘
```

---

### What the closure table looks like for a real hierarchy

```
Global Corp          (id=1)
└── EMEA Division    (id=2)
    └── Germany      (id=3)
        └── Berlin   (id=4)
```

| ancestor | descendant | depth |
|---|---|---|
| 1 | 1 | 0 | ← self
| 2 | 2 | 0 | ← self
| 3 | 3 | 0 | ← self
| 4 | 4 | 0 | ← self
| 1 | 2 | 1 | ← Global → EMEA
| 1 | 3 | 2 | ← Global → Germany
| 1 | 4 | 3 | ← Global → Berlin
| 2 | 3 | 1 | ← EMEA → Germany
| 2 | 4 | 2 | ← EMEA → Berlin
| 3 | 4 | 1 | ← Germany → Berlin

**Read queries are always a single `WHERE ancestor_id = ?` — no recursion, no joins.**
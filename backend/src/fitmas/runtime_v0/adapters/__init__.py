"""Bridges between the legacy FitMAS product and the isolated Runtime V0 core.

Adapters MAY depend on the existing product (core ORM today, domain writers
later); the V0 core never imports this package. They translate the real world
into a V0 WorldSnapshot (read side) and, later, V0 commands into official
writers (write side).

Boundary enforced by tests/runtime_v0/test_import_boundaries.py: this package is
excluded from the core isolation/budget checks, and the core must never import
`runtime_v0.adapters`.
"""

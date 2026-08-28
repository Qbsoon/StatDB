"""Embedded SQL migrations for the catalog schema.

Each migration is a plain ``.sql`` file named ``NNN_description.sql`` where
``NNN`` is a zero-padded, strictly increasing integer version. Migrations run
inside a transaction and are tracked in the ``schema_migrations`` table.
"""

"""A minimal `RepositoryDriver` used only to prove the `lnpl.drivers`
entry-points discovery path works end-to-end (issue #75) — registration
wiring, not backend correctness. Backend correctness is `lnpl.testing`'s job,
exercised against `SqliteRepositoryDriver` in `test_driver_contract.py`.

`make_demo_driver` is the callable an entry-point's `value` names (the shape
`--backend demo:<arg>` needs): `EntryPoint(name="demo",
value="tests.driver_spi_fixture:make_demo_driver", group="lnpl.drivers")`.
`test_driver_spi.py` constructs entry-points like that one directly rather
than installing a second package — this repo is the only consumer of its own
group, so there is nothing to install (`lnpl-dev-env`'s stdlib-only
constraint; a real external driver's own CI is what installs a real package).
"""

from lnpl.drivers import DriverError, RepositoryDriver


class DemoRepositoryDriver(RepositoryDriver):
    """In-memory, keyed the same way `interp.FakeRepository` is — just
    without importing `interp` (out of scope here, see `lnpl.testing`'s
    module docstring for why the TCK stays driver-only, same reasoning)."""

    def __init__(self, arg=None):
        self.arg = arg
        self.rows = {}

    def seed(self, rows):
        for entity_id, table in (rows or {}).items():
            store = self.rows.setdefault(entity_id, {})
            for key, row in table.items():
                store.setdefault(key, dict(row))

    def execute(self, entity_id, operation, key):
        table = self.rows.setdefault(entity_id, {})
        if operation in ("read", "query"):
            return table.get(key)
        if operation == "create":
            if key in table:
                raise DriverError(
                    "repository create conflicts: %s already exists" % entity_id)
            table[key] = {"id": key}
            return {"affected": 1}
        if operation in ("update", "delete"):
            affected = 1 if key in table else 0
            if operation == "delete":
                table.pop(key, None)
            return {"affected": affected}
        raise DriverError("unsupported repository operation %r" % operation)

    def query(self, entity_id):
        table = self.rows.get(entity_id, {})
        return [row for _key, row in sorted(table.items())]

    def persist(self, entity_id, key, row):
        self.rows.setdefault(entity_id, {})[key] = dict(row)

    def record_emission(self, emission):
        pass

    def close(self):
        pass


def make_demo_driver(arg=None):
    return DemoRepositoryDriver(arg)

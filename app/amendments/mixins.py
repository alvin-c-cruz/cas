"""The contract a document implements to become amendable.

Slice 1 requires only DOCUMENT_TYPE and build_snapshot(). Slice 2 adds
consumed_qty(line) and has_any_child_reference(line) for the shared validator.
"""
from app.amendments.snapshot import canonical, money


class Amendable:
    #: Matches the module's audit `module` name, e.g. 'purchase_orders'.
    DOCUMENT_TYPE = None

    #: Header column names captured in the snapshot. The revision viewer renders
    #: these, so the set is a CONTRACT -- a missing key is read as a default and
    #: silently becomes an affirmative false claim.
    SNAPSHOT_HEADER_FIELDS = ()

    #: Line column names captured per row.
    SNAPSHOT_LINE_FIELDS = ()

    #: Header money columns that also get a *_display form.
    SNAPSHOT_MONEY_FIELDS = ()

    #: May a line legitimately carry NO quantity? Defaults to False -- a line
    #: without one is meaningless on an order document, and every adopter before
    #: Purchase Request had a NOT-NULL-in-practice quantity. PR is the exception:
    #: its column is nullable and its create parser keeps a line on a product OR
    #: a description, so "Cement, quantity to follow" is an ordinary requisition.
    #: The shared validator reads this to tell an ABSENT quantity (allowed here)
    #: from an UNREADABLE one (never allowed).
    LINE_QUANTITY_REQUIRED = True

    def snapshot_line_extras(self, line):
        """Resolved, human-facing values for a line (FK names, display money).

        Override per document. Must return a dict; keys are merged into the row.
        """
        return {}

    def snapshot_header_extras(self):
        """Resolved, human-facing values for the header. Override per document."""
        return {}

    def build_snapshot(self):
        """Complete document state -- header + all lines -- as of right now."""
        header = {f: canonical(getattr(self, f, None)) for f in self.SNAPSHOT_HEADER_FIELDS}
        for f in self.SNAPSHOT_MONEY_FIELDS:
            header[f'{f}_display'] = money(getattr(self, f, None))
        header.update(self.snapshot_header_extras())

        lines = []
        for item in sorted(self.line_items, key=lambda i: (i.line_number or 0, i.id or 0)):
            row = {f: canonical(getattr(item, f, None)) for f in self.SNAPSHOT_LINE_FIELDS}
            # Identity -- a raw int, not canonicalised, so lookups stay exact.
            row['line_id'] = item.id
            row.update(self.snapshot_line_extras(item))
            lines.append(row)

        return {'header': header, 'lines': lines}

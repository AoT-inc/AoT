"""Shared form shims for the AI data-tool drawer mixins.

Split out of aot_data_tool_service.py (was a nested class on
AoTDataToolService) so definition/function/record drawer mixins can share
it without importing each other.
"""


class _FakeForm:
    """Minimal WTForms form/field shim: exposes .<field>.data and validate()."""
    class _Field:
        def __init__(self, data): self.data = data
    def __init__(self, **fields):
        for k, v in fields.items():
            setattr(self, k, _FakeForm._Field(v))
    def validate(self):
        return True

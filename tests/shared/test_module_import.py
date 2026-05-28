"""Test core.shared module import validation."""

def test_import_shared():
    """Verify core.shared module loads successfully."""
    import core.shared
    assert hasattr(core.shared, '__version__')
    assert core.shared.__version__ == "0.1.0"

def test_shared_module_docstring():
    """Verify module has proper documentation."""
    import core.shared
    assert core.shared.__doc__ is not None
    assert 'Shared utilities' in core.shared.__doc__

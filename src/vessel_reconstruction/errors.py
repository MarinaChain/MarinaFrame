"""Small exception types that do not import the native CAD runtime."""


class GeometryError(ValueError):
    """Observed geometry cannot be constructed within the supported contract."""

"""spiraltracker.com/<world>: quest order and goal types."""
from .listing import ListingSource


class SpiralTracker(ListingSource):
    name = "spiraltracker"
    url_template = "https://spiraltracker.com/{}"

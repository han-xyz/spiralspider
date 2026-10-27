"""wizard101folio.com/<world>-quest-tree: quest order and goals."""
from .listing import ListingSource


class Folio(ListingSource):
    name = "folio"
    url_template = "https://wizard101folio.com/{}-quest-tree"

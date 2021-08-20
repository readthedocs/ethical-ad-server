from .models import AdImpression
from .models import GeoImpression
from .models import KeywordImpression
from .models import PlacementImpression
from .models import RegionImpression
from .models import RegionTopicImpression
from .models import UpliftImpression


class IndexRouter:
    """
    A database router that allows for indexing into a different postgres DB than core operations.
    """

    index_models = {
        AdImpression,
        PlacementImpression,
        GeoImpression,
        RegionImpression,
        RegionTopicImpression,
    }

    def db_for_read(self, model, **hints):
        """Only allow reads from the replica server."""
        if model in self.index_models:
            return "index"
        return None

    def db_for_write(self, model, **hints):
        if model in self.index_models:
            return "index"
        return None

    def allow_relation(self, obj1, obj2, **hints):
        db_list = ("default", "index")
        if obj1._state.db in db_list and obj2._state.db in db_list:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return True

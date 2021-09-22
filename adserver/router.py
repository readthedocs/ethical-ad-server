"""Router for replica replica."""
from .models import AdImpression
from .models import GeoImpression
from .models import KeywordImpression
from .models import PlacementImpression
from .models import RegionImpression
from .models import RegionTopicImpression
from .models import UpliftImpression


class ReplicaRouter:  # pylint: disable=unused-argument

    """A database router that allows for reading from a replica, mostly used for reporting for now."""

    # All reporting models
    index_models = {
        AdImpression,
        PlacementImpression,
        GeoImpression,
        KeywordImpression,
        RegionImpression,
        RegionTopicImpression,
        UpliftImpression,
    }

    def db_for_read(self, model, **hints):
        """Read all indexes from the replica server (this is only used for reporting)."""
        if model in self.index_models:
            return "replica"
        return None

    def db_for_write(self, model, **hints):
        """Only write to the default database."""
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        """Don't allow creating relations across databases."""
        db_list = ("default", "replica")
        if (
            obj1._state.db in db_list and obj2._state.db in db_list
        ):  # pylint: disable=protected-access
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """Don't allow migrating the replica, since we shouldn't write to it."""
        if db == "replica":
            return False
        return True

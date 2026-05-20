"""Backward-compatibility re-export shim.

The canonical implementations have moved to ``utils/serializers.py`` so that
service-layer modules can import them without depending on the API layer.
All existing ``from index_advisor.api.serializers import …`` statements
continue to work unchanged.
"""
from index_advisor.utils.serializers import to_jsonable, row_to_dict, rows_to_list

__all__ = ["to_jsonable", "row_to_dict", "rows_to_list"]

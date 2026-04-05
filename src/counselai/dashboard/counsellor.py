"""Backward-compatibility shim -- re-exports from the split modules.

All logic now lives in counsellor_queue.py and counsellor_review.py.
Import from those modules directly in new code.
"""

from counselai.dashboard.counsellor_queue import (  # noqa: F401
    QueueFilters,
    _count_by_key,
    _enum_val,
    get_available_grades,
    get_available_schools,
    get_counsellor_queue,
)
from counselai.dashboard.counsellor_review import (  # noqa: F401
    get_session_evidence,
    get_session_review,
)

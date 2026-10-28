"""All PIC tables share one metadata (app.pic.db.Base) in the ``pic`` schema."""
from app.pic.models.platform import *  # noqa: F401,F403
from app.pic.models.master import *  # noqa: F401,F403
from app.pic.models.plan_request import *  # noqa: F401,F403
from app.pic.models.source_contract import *  # noqa: F401,F403
from app.pic.models.order_receive import *  # noqa: F401,F403
from app.pic.models.pay_value import *  # noqa: F401,F403
from app.pic.models.governance import *  # noqa: F401,F403

# Tables without tenant_id or with their own isolation handling.
NON_RLS_TABLES = {"tenant", "process_definition"}
# Tables the application role may only append to.
APPEND_ONLY_TABLES = {"audit_event"}

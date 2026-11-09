"""All PIC tables share one metadata (app.pic.db.Base) in the ``pic`` schema."""
from app.pic.models.platform import *  # noqa: F401,F403
from app.pic.models.master import *  # noqa: F401,F403
from app.pic.models.plan_request import *  # noqa: F401,F403
from app.pic.models.source_contract import *  # noqa: F401,F403
from app.pic.models.order_receive import *  # noqa: F401,F403
from app.pic.models.pay_value import *  # noqa: F401,F403
from app.pic.models.governance import *  # noqa: F401,F403
from app.pic.models.operations import *  # noqa: F401,F403
from app.pic.models.platform_enterprise import *  # noqa: F401,F403
from app.pic.models.p2p_completion import *  # noqa: F401,F403
from app.pic.models.wave1_a import *  # noqa: F401,F403
from app.pic.models.wave1_c import *  # noqa: F401,F403
from app.pic.models.ai_sync import *  # noqa: F401,F403
from app.pic.models.insight import *  # noqa: F401,F403
from app.pic.models.industry import *  # noqa: F401,F403
from app.pic.models.admin_enterprise import *  # noqa: F401,F403
from app.pic.models.finance_close import *  # noqa: F401,F403
from app.pic.models.inventory import *  # noqa: F401,F403
from app.pic.models.tax_nonresident import *  # noqa: F401,F403

# Tables without tenant_id or with their own isolation handling.
NON_RLS_TABLES = {"tenant", "process_definition"}
# Tables the application role may only append to.
APPEND_ONLY_TABLES = {"audit_event", "audit_event_archive", "audit_archive_batch"}

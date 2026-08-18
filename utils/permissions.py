import logging

from ..repositories import user_repo, machine_permission_repo

logger = logging.getLogger(__name__)


def _can_access_machine(user_id: int, machine_id: int) -> bool:
    if not user_id or not machine_id:
        return False
    if _is_operator_user(user_id):
        return True
    try:
        allowed = set(machine_permission_repo.list_machine_ids_by_user(user_id))
        return machine_id in allowed
    except Exception as e:
        logger.warning("_can_access_machine: machine permission check failed for user %s machine %s: %s", user_id, machine_id, e)
        return False

def _is_operator_user(user_id: int) -> bool:
    try:
        u = user_repo.get_by_id(user_id)
        # logger.debug("DEBUG: checking if user %s is operator: permission=%s", user_id, getattr(u, 'permission', None))
        perm = getattr(u, 'permission', None) if u else None
        return bool(perm and getattr(perm, 'value', str(perm)).lower() == 'operator')
    except Exception as e:
        logger.warning("_is_operator_user: permission check failed for user %s: %s", user_id, e)
        return False

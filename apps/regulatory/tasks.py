import logging
from celery import shared_task
from django.utils import timezone
from apps.regulatory.models import PlayerPlayLimits, AutoExclusionRecord
from apps.accounts.models import AccountStatus

logger = logging.getLogger(__name__)

@shared_task
def procesar_cooldowns_de_limites():
    """Busca usuarios cuyo periodo de 24 horas ya pasó y les aplica el nuevo límite."""
    ahora = timezone.now()
    
    # Filtramos los que tienen un cooldown vencido y un límite pendiente
    limites_listos = PlayerPlayLimits.objects.filter(
        cooldown_until__lte=ahora,
        pending_daily_limit__isnull=False
    )
    
    cantidad = limites_listos.count()
    for limite in limites_listos:
        limite.daily_deposit_limit = limite.pending_daily_limit
        limite.pending_daily_limit = None
        limite.cooldown_until = None
        limite.save()
        
    logger.info(f"Cron: Se procesaron y liberaron {cantidad} incrementos de límite de depósito.")
    return cantidad


@shared_task
def levantar_autoexclusiones_vencidas():
    """Busca cuentas autoexcluidas cuyo castigo temporal haya terminado para devolverlas a la normalidad."""
    ahora = timezone.now()
    
    # Buscamos registros vencidos, ignorando los indefinidos (excluded_until__isnull=False)
    registros_vencidos = AutoExclusionRecord.objects.filter(
        excluded_until__isnull=False,
        excluded_until__lte=ahora,
        user__profile__status=AccountStatus.SELF_EXCLUDED
    ).select_related('user__profile')

    cantidad = registros_vencidos.count()
    for registro in registros_vencidos:
        profile = registro.user.profile
        # Se devuelve al estado pendiente para que vuelva a interactuar
        profile.status = AccountStatus.PENDING_VERIFICATION
        profile.save()

    logger.info(f"Cron: Se levantaron {cantidad} autoexclusiones vencidas.")
    return cantidad
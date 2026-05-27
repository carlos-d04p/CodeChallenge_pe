from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.betting.models import Bet
from apps.wallet.models import LedgerEntry
from apps.events.models import OddsAuditRecord
from apps.regulatory.models import ImmutableLog

@receiver(post_save, sender=Bet)
def auditar_ticket_apuesta(sender, instance, created, **kwargs):
    payload = {
        "bet_id": instance.id,
        "user_id": instance.user.id,
        "stake": str(instance.stake),
        "odds": str(instance.odds),
        "status": instance.status,
        "bet_type": instance.bet_type
    }
    ImmutableLog.registrar_evento("APUESTA_MODIFICADA", payload)

@receiver(post_save, sender=LedgerEntry)
def auditar_movimiento_billetera(sender, instance, created, **kwargs):
    payload = {
        "ledger_id": instance.id,
        "user_id": instance.user.id if instance.user else None,
        "account": instance.account,
        "amount": str(instance.amount),
        "direction": instance.direction,
        "transaction_id": str(instance.transaction_id)
    }
    ImmutableLog.registrar_evento("MOVIMIENTO_BILLETERA", payload)

@receiver(post_save, sender=OddsAuditRecord)
def auditar_cambio_cuotas(sender, instance, created, **kwargs):
    payload = {
        "audit_id": instance.id,
        "selection_id": instance.selection.id,
        "old_odds": str(instance.old_odds),
        "new_odds": str(instance.new_odds)
    }
    ImmutableLog.registrar_evento("CAMBIO_CUOTAS", payload)
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

class EventOddsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.event_id = self.scope['url_route']['kwargs']['event_id']
        self.group_name = f"event_{self.event_id}"
        
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        
        # Carga inicial: Enviar estado actual de las cuotas al conectarse
        await self.enviar_snapshot_inicial()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        """Mantiene viva la conexión WebSocket (Keep-Alive)."""
        try:
            data = json.loads(text_data)
            if data.get("type") == "ping":
                await self.send(text_data=json.dumps({"type": "pong"}))
        except json.JSONDecodeError:
            pass

    async def odds_update(self, event):
        await self.send(text_data=json.dumps(event['data']))

    async def enviar_snapshot_inicial(self):
        snapshot = await self.obtener_cuotas_bd(self.event_id)
        if snapshot:
            await self.send(text_data=json.dumps({
                "type": "initial_snapshot",
                "event_id": self.event_id,
                "selections": snapshot
            }))
        else:
            await self.close(code=4004)

    @database_sync_to_async
    def obtener_cuotas_bd(self, event_id):
        """Consulta asíncrona a la base de datos de Django."""
        from apps.events.models import Event, MarketStatus
        
        try:
            evento = Event.objects.prefetch_related('markets__selections').get(id=event_id)
        except Event.DoesNotExist:
            return None

        resultado = []
        for market in evento.markets.filter(status=MarketStatus.OPEN):
            for sel in market.selections.all():
                resultado.append({
                    "market_id": market.id,
                    "market_code": market.code,
                    "selection_id": sel.id,
                    "name": sel.name,
                    "odds": str(sel.odds)
                })
        return resultado
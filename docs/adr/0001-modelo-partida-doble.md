# ADR 0001: Implementación del Modelo de Billetera por Partida Doble

## Contexto
El sistema FairBet es una plataforma educativa de simulación de apuestas que requiere un control absoluto sobre la integridad financiera de las fichas virtuales. Al procesar transacciones concurrentes (como recargas, retiros y congelamiento de fondos para apuestas), usar un diseño clásico de base de datos con un campo estático de 'saldo' incrementa drásticamente el riesgo de corrupción de datos ante caídas del servidor o condiciones de carrera. Necesitamos un mecanismo que garantice la trazabilidad completa de cada ficha del sistema.

## Opciones Consideradas

### Opción 1: Almacenamiento Estático de Saldo (Columna Balance)
Consiste en crear una tabla 'Wallet' con una columna numérica fija (ej: saldo = 150.00). Cada operación incrementaría o decrementaría directamente este valor mediante consultas SQL ('UPDATE').
* **Pros:** Consultas de lectura extremadamente rápidas y estructura simple de entender.
* **Contras:** No deja rastro histórico de por qué cambió el saldo. Si dos procesos acceden al mismo tiempo sin el bloqueo adecuado, se puede generar duplicación o pérdida de saldo. No cumple con las especificaciones de la rúbrica del reto.

### Opción 2: Libro Contable de Partida Doble (LedgerEntry)
Consiste en registrar cada transacción como un conjunto de filas balanceadas inside un libro diario. El saldo nunca se almacena; se deriva calculando dinámicamente la suma de todas las entradas (Créditos) menos las salidas (Débitos) en tiempo real ($SUM(credits) - SUM(debits)$).
* **Pros:** Integridad financiera absoluta e inmutable por diseño. Cada movimiento tiene una contraparte (si el usuario recarga, la casa se debita). Permite una auditoría perfecta y cumple estrictamente con el requerimiento del Núcleo Obligatorio.
* **Contras:** Requiere un diseño de código más avanzado y consultas de agregación más pesadas sobre la base de datos a medida que el libro contable crezca.

## Decisión
Se elige la **Opción 2 (Libro Contable de Partida Doble)** debido a que la tolerancia a errores financieros en plataformas regulatorias (conforme a la Ley 31557) debe ser cero. El impacto en el rendimiento de lectura se mitigará mediante el uso de índices compuestos en la base de datos PostgreSQL sobre los campos de cuenta y usuario.

## Consecuencias
* **Lo que se vuelve más fácil:** El sistema cuenta con una trazabilidad contable total de auditoría automática. Es imposible alterar el saldo de un usuario sin dejar una huella matemática en el libro diario.
* **Lo que se vuelve más difícil:** Las operaciones de negocio requieren mayor cuidado al programarse. Obliga a utilizar transacciones atómicas de Django ('transaction.atomic') y bloqueos pesimistas ('select_for_update') para asegurar que los saldos intermedios no varíen durante el cálculo dinámico.

## Fecha y Autor
* **Fecha:** 26 de Mayo de 2026
* **Autor:** Carlos Cancino
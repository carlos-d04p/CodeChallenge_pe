# ADR 0002: Manejo Estricto de Tipo de Dato Decimal y Precisión Financiera

## Contexto
La plataforma requiere procesar transacciones de saldos, cuotas (odds) y liquidación de apuestas bajo un esquema educativo de alta integridad financiera conforme a los lineamientos de la Ley 31557. El uso de tipos de datos de punto flotante binario (`float` en Python o `real`/`double precision` en bases de datos) genera imprecisiones acumulativas debido al redondeo en base 2 (por ejemplo, `0.1 + 0.2` resulta en `0.30000000000000004`). Para una simulación financiera válida, cualquier error de redondeo invalida los cálculos de la casa y del usuario.

## Opciones Consideradas

### Opción 1: Uso de Tipos Nativos Float (`float`)
Consiste en utilizar el tipo primitivo de coma flotante de Python y PostgreSQL para almacenar montos y cuotas.
* **Pros:** Mayor velocidad de procesamiento aritmético a nivel de CPU y menor consumo de almacenamiento en disco.
* **Contras:** Pérdida de precisión matemática exacta. Incompatible con las reglas de auditoría y con las restricciones explícitas del reto.

### Opción 2: Punto Fijo Decimal (`Decimal` / `numeric`)
Consiste en forzar el uso de la clase `Decimal` de Python y la columna `numeric` en PostgreSQL, configurando una escala fija de 18 dígitos totales y 4 decimales (`max_digits=18`, `decimal_places=4`).
* **Pros:** Precisión matemática exacta en base 10. Garantiza que las operaciones aritméticas complejas (como `stake * odds`) devuelvan resultados exactos sin decimales fantasmas. Cumple con los requerimientos técnicos de la rúbrica.
* **Contras:** Ligera penalización en el rendimiento de operaciones de cálculo masivo y mayor espacio de almacenamiento asignado en la base de datos.

## Decisión
Se elige la **Opción 2 (Punto Fijo Decimal)**. La integridad del dinero virtual y de las cuotas es prioritaria frente al rendimiento marginal de cómputo. Todo modelo que almacene dinero, stakes, payouts o cuotas implementará campos `DecimalField` con la configuración exacta de `max_digits=18` y `decimal_places=4`.

## Consecuencias
* **Lo que se vuelve más fácil:** Los cálculos financieros e invariantes globales son 100% predecibles y auditables. Las pruebas unitarias pueden evaluar comparaciones exactas sin necesidad de tolerancias de aproximación.
* **Lo que se vuelve más difícil:** Se debe garantizar la conversión explícita a `Decimal` en el código de negocio. Intentar realizar una operación aritmética mezclando un `float` de Python con un `Decimal` de Django lanzará un error de tipo (`TypeError`) en tiempo de ejecución, obligando a un desarrollo riguroso.

## Fecha y Autor
* **Fecha:** 26 de Mayo de 2026
* **Autor:** Carlos Cancino
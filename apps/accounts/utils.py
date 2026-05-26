from datetime import date

def calcular_edad(fecha_nacimiento: date) -> int:
    """Calcula la edad exacta de una persona basándose en la fecha actual."""
    hoy = date.today()
    return hoy.year - fecha_nacimiento.year - ((hoy.month, hoy.day) < (fecha_nacimiento.month, fecha_nacimiento.day))

def validar_dni_peruano(dni: str, digito_verificador: str) -> bool:
    """
    Algoritmo oficial del dígito verificador de RENIEC (Módulo 11).
    Valida si el carácter verificador (número o letra) corresponde a los 8 dígitos del DNI.
    """
    if len(dni) != 8 or not dni.isdigit():
        return False

    # Factores multiplicadores asignados de derecha a izquierda por estándar
    factores = [3, 2, 7, 6, 5, 4, 3, 2]
    
    # Tablas de conversión oficiales de RENIEC según el residuo obtenido
    llaves_numericas = [6, 7, 8, 9, 0, 1, 1, 2, 3, 4, 5]
    llaves_caracter = ['K', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']

    # Sumatoria de multiplicación de dígitos por sus respectivos factores
    suma_total = sum(int(dni[i]) * factores[i] for i in range(8))
    
    # Operación de módulo 11
    indice_clave = 11 - (suma_total % 11)
    if indice_clave == 11:
        indice_clave = 0

    numero_esperado = str(llaves_numericas[indice_clave])
    letra_esperada = llaves_caracter[indice_clave]

    caracter_provisto = str(digito_verificador).strip().upper()

    # El dígito puede presentarse de forma numérica o en letra según el tipo de DNI
    return caracter_provisto == numero_esperado or caracter_provisto == letra_esperada
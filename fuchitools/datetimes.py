from __future__ import annotations
import datetime
from typing import Union, Optional
import pandas as pd  # type: ignore

def timestamp():
    return datetime.now().isoformat()

def del_microseconds(x: datetime.datetime) -> datetime.datetime:
    """Elimina los microsegundos de un objeto datetime.

    Args:
        x: Objeto datetime del cual se eliminarán los microsegundos.

    Returns:
        Objeto datetime con microsegundos establecidos a cero.
    """
    return x.replace(microsecond=0)


def end_of_day(x: Union[datetime.date, datetime.datetime], microseconds: bool = True) -> datetime.datetime:
    """Obtiene el último momento del día para una fecha dada.

    Args:
        x: Objeto date o datetime que representa el día.
        microseconds: Si es False, elimina los microsegundos del resultado.

    Returns:
        Objeto datetime representando las 23:59:59.999999 del día indicado
        (o 23:59:59 si microseconds=False).
    """
    if isinstance(x, datetime.datetime):
        x = x.date()
    dt = datetime.datetime.combine(x, datetime.datetime.max.time())
    if not microseconds:
        dt = del_microseconds(dt)
    return dt


def start_of_day(x: Union[datetime.date, datetime.datetime], microseconds: bool = True) -> datetime.datetime:
    """Obtiene el primer momento del día para una fecha dada.

    Args:
        x: Objeto date o datetime que representa el día.
        microseconds: Si es False, elimina los microsegundos del resultado.

    Returns:
        Objeto datetime representando las 00:00:00.000000 del día indicado
        (o 00:00:00 si microseconds=False).
    """
    if isinstance(x, datetime.datetime):
        x = x.date()
    dt = datetime.datetime.combine(x, datetime.datetime.min.time())
    if not microseconds:
        dt = del_microseconds(dt)
    return dt


def time_from_str(x: str) -> datetime.time:
    """Convierte una cadena de tiempo en un objeto time.

    Soporta formatos HH:MM y HH:MM:SS[.ffffff]. Los microsegundos se extraen
    de la parte decimal de los segundos si está presente.

    Args:
        x: Cadena con formato de tiempo (ej. "14:30:45.123456").

    Returns:
        Objeto time con hora, minuto, segundo y microsegundo.

    Raises:
        ValueError: Si el formato de la cadena es inválido.
    """
    t = x.strip().split(":")
    h: int
    m: int
    s: int = 0
    u: int = 0

    if len(t) == 3:
        h_str, m_str, s_str = t
        h, m = int(h_str), int(m_str)
        if "." in s_str:
            s_float = float(s_str)
            s = int(s_float)
            u = int(round((s_float - s) * 1_000_000))
        else:
            s = int(s_str)
    elif len(t) == 2:
        h_str, m_str = t
        h, m = int(h_str), int(m_str)
    else:
        raise ValueError(f"Formato de tiempo inválido: '{x}'")

    return datetime.time(h, m, s, u)


def date_to_datetime(
    x: Union[datetime.date, datetime.datetime],
    endofday: bool = False,
    microseconds: bool = True
) -> datetime.datetime:
    """Convierte un objeto date a datetime (inicio o fin del día).

    Args:
        x: Objeto date o datetime a convertir.
        endofday: Si es True, devuelve el final del día; de lo contrario, el inicio.
        microseconds: Si es False, elimina los microsegundos del resultado.

    Returns:
        Objeto datetime correspondiente al inicio o final del día.
    """
    if endofday:
        return end_of_day(x, microseconds=microseconds)
    return start_of_day(x, microseconds=microseconds)


def datetime_from_str(
    x: str,
    usaformat: bool = False,
    endofday: bool = False
) -> datetime.datetime:
    """Convierte una cadena a objeto datetime con múltiples formatos soportados.

    Soporta formatos:
      - ISO 8601 (ej. "2024-01-15T14:30:00")
      - DD/MM/YYYY [HH:MM:SS] (formato europeo por defecto)
      - MM/DD/YYYY [HH:MM:SS] (con usaformat=True)
      - YYYY-MM-DD [HH:MM:SS]

    Args:
        x: Cadena que representa fecha y opcionalmente hora.
        usaformat: Si es True, interpreta la fecha como MM/DD/YYYY; de lo contrario DD/MM/YYYY.
        endofday: Si es True y no se especifica hora, devuelve el final del día.

    Returns:
        Objeto datetime resultante.

    Raises:
        ValueError: Si el formato de la cadena es inválido o los componentes de fecha son incorrectos.
    """
    x = x.strip()
    try:
        return datetime.datetime.fromisoformat(x)
    except ValueError:
        pass
    
    dts = x.split()
    hora: Optional[str] = None

    if len(dts) > 2:
        raise ValueError(f"Cadena de fecha/hora con formato inválido: '{x}'")
    elif len(dts) == 2:
        hora = dts[1].strip()

    fecha = dts[0].strip()
    fs = fecha.split("/")

    if len(fs) == 1:
        fs = fecha.split("-")
    
    if len(fs) == 1:
        # Intentar formato ISO
        dt = datetime.datetime.fromisoformat(fecha)
        if hora is None:
            return date_to_datetime(dt.date(), endofday=endofday)
        else:
            return datetime.datetime.combine(dt.date(), time_from_str(hora))
    
    if len(fs) != 3:
        raise ValueError(f"Cadena de fecha/hora con formato inválido: '{x}'")

    if usaformat:
        m_str, d_str, y_str = fs[:3]
    else:
        d_str, m_str, y_str = fs[:3]

    d, m, y = int(d_str), int(m_str), int(y_str)

    if y < 100:
        y += 2000

    dt_date = datetime.date(y, m, d)
    if hora is None:
        return date_to_datetime(dt_date, endofday=endofday)
    else:
        return datetime.datetime.combine(dt_date, time_from_str(hora))


def date_from_int(x: int) -> datetime.date:
    """Convierte un entero (formato YYYYMMDD) a objeto date.

    Args:
        x: Entero representando una fecha (ej. 20240115 para 15/01/2024).

    Returns:
        Objeto date correspondiente.

    Raises:
        ValueError: Si el entero no representa una fecha válida.
    """
    return datetime.datetime.fromisoformat(str(x)).date()


def datetime_from_int(x: int, endofday: bool = False) -> datetime.datetime:
    """Convierte un entero (formato YYYYMMDD) a objeto datetime.

    Args:
        x: Entero representando una fecha (ej. 20240115).
        endofday: Si es True, devuelve el final del día; de lo contrario, el inicio.

    Returns:
        Objeto datetime correspondiente al inicio o final del día.
    """
    return date_to_datetime(date_from_int(x), endofday=endofday)


def to_datetime(
    x: Union[datetime.datetime, datetime.date, str, int, pd.Timestamp],
    usaformat: bool = False,
    endofday: bool = False
) -> datetime.datetime:
    """Convierte múltiples tipos de entrada a objeto datetime.

    Args:
        x: Valor a convertir (datetime, date, str, int o Timestamp de pandas).
        usaformat: Si x es str, interpreta la fecha como MM/DD/YYYY (requerido solo para cadenas).
        endofday: Si es True y no se especifica hora, devuelve el final del día.

    Returns:
        Objeto datetime resultante.

    Raises:
        ValueError: Si no es posible convertir el valor a datetime.
    """
    if isinstance(x, datetime.datetime):
        if isinstance(x, pd.Timestamp): # pd.Timestamp es instancia de datetime
            return x.to_pydatetime()
        return x
    elif isinstance(x, datetime.date):
        return date_to_datetime(x, endofday=endofday)
    elif isinstance(x, str):
        return datetime_from_str(x, usaformat=usaformat, endofday=endofday)
    elif isinstance(x, int):
        return datetime_from_int(x, endofday=endofday)
    else:
        raise ValueError(f"No se puede convertir el valor de tipo {type(x).__name__} a datetime.")


def to_date(
    x: Union[datetime.datetime, datetime.date, str, int, pd.Timestamp],
    usaformat: bool = False,
) -> datetime.date:
    """Convierte múltiples tipos de entrada a objeto date.

    Args:
        x: Valor a convertir (datetime, date, str, int o Timestamp de pandas).
        usaformat: Si x es str, interpreta la fecha como MM/DD/YYYY (requerido solo para cadenas).
        endofday: Ignorado para date, pero necesario para coherencia en la conversión de datetime.

    Returns:
        Objeto date resultante.

    Raises:
        ValueError: Si no es posible convertir el valor a date.
    """
    if isinstance(x, datetime.date) and not isinstance(x, datetime.datetime):
        return x
    elif isinstance(x, datetime.datetime): # pd.Timestamp es instancia de datetime
        return x.date()
    elif isinstance(x, str):
        return to_datetime(x, usaformat=usaformat).date()
    elif isinstance(x, int):
        return date_from_int(x)
    else:
        raise ValueError(f"No se puede convertir el valor de tipo {type(x).__name__} a date.")
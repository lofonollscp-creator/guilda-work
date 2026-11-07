"""Error común de la capa de IA (asistente, lectura de facturas, acciones de correo…): legible para mostrar en pantalla."""


class ErrorIA(Exception):
    """Error legible para mostrar en el chat cuando el asistente falla. `codigo_http` solo se rellena si el error viene de una respuesta HTTP real del proveedor (None en errores de red, tiempo
    de espera o formato); lo usan los reintentos para decidir si vale la pena probar otra clave u otro proveedor."""

    def __init__(self, mensaje: str, codigo_http: int | None = None):
        super().__init__(mensaje)
        self.codigo_http = codigo_http

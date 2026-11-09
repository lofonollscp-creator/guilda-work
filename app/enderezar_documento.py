"""Enderezar la foto de un documento: busca el papel en la imagen, lo recorta en perspectiva y le quita las sombras.

Es una **propuesta**: si no hay un contorno claro de documento (cuatro esquinas, ni demasiado pequeño ni toda la imagen) no devuelve nada y la foto se deja como está. El cliente decide en el portal si usa la
enderezada o la suya, porque un detector puede equivocarse (por ejemplo, tomar una tabla de la factura por el papel entero). Se hace en el servidor con OpenCV, que ya es dependencia del lector de QR."""
from __future__ import annotations

import logging

logger = logging.getLogger("guilda")

LADO_DETECCION = 900                    # la detección se hace en una copia pequeña: es más rápida y menos sensible al ruido
AREA_MINIMA, AREA_MAXIMA = 0.30, 0.94   # el papel ocupa entre el 30 % y el 94 % de la foto: menos, será otra cosa; más, no hay nada que recortar
LADO_SALIDA = 2200
CALIDAD_JPEG = 86


def _ordenar(puntos):
    """Esquinas en el orden arriba-izquierda, arriba-derecha, abajo-derecha, abajo-izquierda."""
    import numpy as np
    p = np.array(puntos, dtype="float32").reshape(4, 2)
    suma, resta = p.sum(axis=1), np.diff(p, axis=1).ravel()
    return np.array([p[suma.argmin()], p[resta.argmin()], p[suma.argmax()], p[resta.argmax()]], dtype="float32")


def _es_rectangulo_razonable(cuad) -> bool:
    """Los lados opuestos de un folio visto en perspectiva no pueden diferir demasiado y ninguno puede ser minúsculo."""
    import numpy as np
    lados = [float(np.linalg.norm(cuad[i] - cuad[(i + 1) % 4])) for i in range(4)]
    if min(lados) < 40:
        return False
    return max(lados[0], lados[2]) / min(lados[0], lados[2]) < 2.2 and max(lados[1], lados[3]) / min(lados[1], lados[3]) < 2.2


def _buscar_cuadrilatero(gris):
    import cv2
    desenfocada = cv2.GaussianBlur(gris, (5, 5), 0)
    candidatos = []
    for bordes in (cv2.Canny(desenfocada, 40, 120), cv2.threshold(desenfocada, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]):
        cerrados = cv2.morphologyEx(bordes, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)), iterations=2)
        contornos, _ = cv2.findContours(cerrados, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contornos, key=cv2.contourArea, reverse=True)[:6]:
            perimetro = cv2.arcLength(c, True)
            aprox = cv2.approxPolyDP(c, 0.02 * perimetro, True)
            if len(aprox) == 4 and cv2.isContourConvex(aprox):
                candidatos.append(aprox.reshape(4, 2).astype("float32"))
                break
    return candidatos


def _sin_sombras(imagen):
    """Divide cada canal por el fondo desenfocado: la luz desigual desaparece y el papel queda blanco, sin perder el color del texto ni de los sellos."""
    import cv2
    import numpy as np
    lab = cv2.cvtColor(imagen, cv2.COLOR_BGR2LAB)
    luz = lab[:, :, 0].astype("float32")
    k = max(31, (min(luz.shape) // 8) | 1)
    fondo = cv2.medianBlur(cv2.resize(lab[:, :, 0], None, fx=0.25, fy=0.25), (k // 4) | 1)
    fondo = cv2.resize(fondo, (luz.shape[1], luz.shape[0])).astype("float32")
    lab[:, :, 0] = np.clip(luz / np.maximum(fondo, 1) * 235, 0, 255).astype("uint8")
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def enderezar(contenido: bytes) -> dict | None:
    """{imagen: bytes JPEG, area: fracción de la foto que ocupaba el papel} o None si no hay un documento claro que enderezar."""
    try:
        import cv2
        import numpy as np
        original = cv2.imdecode(np.frombuffer(contenido, np.uint8), cv2.IMREAD_COLOR)
        if original is None:
            return None
        alto, ancho = original.shape[:2]
        k = min(1.0, LADO_DETECCION / max(alto, ancho))
        pequena = cv2.resize(original, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else original
        area_total = pequena.shape[0] * pequena.shape[1]
        cuad = None
        for c in _buscar_cuadrilatero(cv2.cvtColor(pequena, cv2.COLOR_BGR2GRAY)):
            if AREA_MINIMA <= cv2.contourArea(c) / area_total <= AREA_MAXIMA and _es_rectangulo_razonable(_ordenar(c)):
                cuad = _ordenar(c)
                break
        if cuad is None:
            return None
        cuad = cuad / k
        w = int(max(np.linalg.norm(cuad[0] - cuad[1]), np.linalg.norm(cuad[3] - cuad[2])))
        h = int(max(np.linalg.norm(cuad[0] - cuad[3]), np.linalg.norm(cuad[1] - cuad[2])))
        f = min(1.0, LADO_SALIDA / max(w, h))
        w, h = max(1, int(w * f)), max(1, int(h * f))
        destino = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype="float32")
        plana = cv2.warpPerspective(original, cv2.getPerspectiveTransform(cuad, destino), (w, h), flags=cv2.INTER_CUBIC)
        ok, jpeg = cv2.imencode(".jpg", _sin_sombras(plana), [cv2.IMWRITE_JPEG_QUALITY, CALIDAD_JPEG])
        return {"imagen": jpeg.tobytes(), "area": round(float(cv2.contourArea(cuad * k)) / area_total, 2)} if ok else None
    except Exception:  # noqa: BLE001 -- es una ayuda: si algo falla, la foto se queda como está
        logger.warning("No se pudo enderezar la foto", exc_info=True)
        return None

"""La app principal no se puede enmarcar desde otra web ni deja que el navegador adivine tipos."""


def test_las_paginas_y_la_api_llevan_cabeceras_de_seguridad(cliente):
    for ruta in ("/login", "/api/v1/health", "/docs/"):
        r = cliente.get(ruta, follow_redirects=False)
        assert r.headers["X-Content-Type-Options"] == "nosniff", ruta
        assert r.headers["X-Frame-Options"] == "SAMEORIGIN", ruta
        assert "frame-ancestors 'self'" in r.headers["Content-Security-Policy"] and "object-src 'none'" in r.headers["Content-Security-Policy"], ruta
        assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin", ruta


def test_hsts_solo_cuando_la_peticion_llego_por_https(cliente):
    assert "Strict-Transport-Security" not in cliente.get("/api/v1/health").headers
    r = cliente.get("/api/v1/health", headers={"X-Forwarded-Proto": "https"})
    assert r.headers["Strict-Transport-Security"] == "max-age=31536000"

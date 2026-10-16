"""`limpiar_kratos_huerfanos` (tests/conftest.py): quita solo los Kratos de prueba de ejecuciones de pytest que ya no existen."""
from types import SimpleNamespace

from tests.conftest import limpiar_kratos_huerfanos


class _Docker:
    """Docker falso: guarda las órdenes y responde a los `ps`."""
    def __init__(self, proyectos, ids_por_proyecto):
        self.proyectos, self.ids, self.ordenes = proyectos, ids_por_proyecto, []

    def __call__(self, orden, **kw):
        self.ordenes.append(orden)
        if orden[:3] == ["docker", "ps", "-a"] and "--format" in orden:
            return SimpleNamespace(stdout="\n".join(self.proyectos) + "\n")
        if orden[:3] == ["docker", "ps", "-aq"]:
            proyecto = orden[-1].split("=", 2)[2]
            return SimpleNamespace(stdout=" ".join(self.ids.get(proyecto, [])))
        return SimpleNamespace(stdout="")


def test_quita_el_de_un_pid_muerto_y_respeta_el_vivo_y_lo_ajeno():
    d = _Docker(["", "guilda-test-111", "guilda-test-222", "guilda-work", "guilda-test-facturascripts", "guilda-test-333x"],
                {"guilda-test-111": ["c1", "c2"], "guilda-test-222": ["c3"]})
    limpiados = limpiar_kratos_huerfanos(ejecutar=d, pid_vivo=lambda pid: pid == 222)
    assert limpiados == ["guilda-test-111"]
    assert ["docker", "rm", "-f", "-v", "c1", "c2"] in d.ordenes
    assert ["docker", "network", "rm", "guilda-test-111_default"] in d.ordenes
    tocados = " ".join(" ".join(o) for o in d.ordenes if o[:2] in (["docker", "rm"], ["docker", "network"]))
    assert "c3" not in tocados and "222" not in tocados and "guilda-work" not in tocados and "facturascripts" not in tocados and "333x" not in tocados


def test_sin_restos_no_borra_nada():
    d = _Docker(["guilda-work"], {})
    assert limpiar_kratos_huerfanos(ejecutar=d, pid_vivo=lambda pid: False) == []
    assert all(o[:2] != ["docker", "rm"] for o in d.ordenes)

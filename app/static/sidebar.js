// Barra lateral: selector de tema (claro/oscuro/sistema) y arrastrar para
// reordenar los menús, al estilo New Outlook. El tema ya se aplica antes de
// pintar mediante el script inline en <head> de base.html — este archivo
// solo gestiona el clic para rotarlo y refleja el estado en el botón.
(function () {
  const CLAVE_TEMA = "guilda-work-tema";
  const ORDEN_TEMAS = ["system", "light", "dark"];
  const ETIQUETAS_TEMA = { system: "🖥 Sistema", light: "☀ Claro", dark: "☾ Oscuro" };

  const boton = document.getElementById("theme-toggle");
  if (boton) {
    const actualizarBoton = () => {
      const tema = localStorage.getItem(CLAVE_TEMA) || "system";
      boton.textContent = ETIQUETAS_TEMA[tema];
      boton.title = "Tema actual: " + ETIQUETAS_TEMA[tema].slice(2) + " (clic para cambiar)";
    };
    actualizarBoton();

    boton.addEventListener("click", () => {
      const actual = localStorage.getItem(CLAVE_TEMA) || "system";
      const siguiente = ORDEN_TEMAS[(ORDEN_TEMAS.indexOf(actual) + 1) % ORDEN_TEMAS.length];
      localStorage.setItem(CLAVE_TEMA, siguiente);
      if (siguiente === "system") {
        delete document.documentElement.dataset.theme;
      } else {
        document.documentElement.dataset.theme = siguiente;
      }
      actualizarBoton();
    });
  }

  const lista = document.getElementById("side-menu-list");
  if (!lista) return;

  let elementoArrastrado = null;

  function filasMenu() {
    return Array.from(lista.querySelectorAll(".side-menu-item"));
  }

  lista.querySelectorAll(".side-menu-item").forEach((fila) => {
    fila.addEventListener("dragstart", () => {
      elementoArrastrado = fila;
      fila.classList.add("is-arrastrando");
    });
    fila.addEventListener("dragend", () => {
      fila.classList.remove("is-arrastrando");
      elementoArrastrado = null;
      guardarOrden();
    });
    fila.addEventListener("dragover", (e) => {
      e.preventDefault();
      if (!elementoArrastrado || elementoArrastrado === fila) return;
      const rect = fila.getBoundingClientRect();
      const despuesDelMedio = e.clientY - rect.top > rect.height / 2;
      fila.parentNode.insertBefore(elementoArrastrado, despuesDelMedio ? fila.nextSibling : fila);
    });
  });

  function guardarOrden() {
    const ids = filasMenu().map((f) => f.dataset.menuId);
    fetch("/menus/reordenar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ orden: ids }),
    });
  }
})();

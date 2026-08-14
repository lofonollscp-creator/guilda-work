// Cabecera de la app: selector de tema (claro/oscuro/sistema), selector de
// densidad, y el menú desplegable de ajustes (⚙) de la barra superior. El
// tema ya se aplica antes de pintar mediante el script inline en <head> de
// base.html — este archivo solo gestiona el clic para rotarlo y refleja el
// estado en el botón. La lista de menús (favoritos/reordenar) vive en el
// Dashboard (inicio.html), no aquí.
(function () {
  // URL del sprite de iconos (app/static/iconos.svg), leída una vez de
  // <body data-url-iconos="..."> -- puesta ahí en vez de en cada botón
  // por separado para no repetir la misma URL de Jinja en varios sitios
  // (ver base.html).
  const URL_ICONOS = document.body.dataset.urlIconos;

  const CLAVE_TEMA = "guilda-work-tema";
  const ORDEN_TEMAS = ["system", "light", "dark"];
  const ETIQUETAS_TEMA = {
    system: { icono: "monitor", texto: "Sistema" },
    light: { icono: "sun", texto: "Claro" },
    dark: { icono: "moon", texto: "Oscuro" },
  };

  const boton = document.getElementById("theme-toggle");
  if (boton) {
    const iconoUse = boton.querySelector(".ajustes-panel-icono use");
    const textoSpan = boton.querySelector(".ajustes-panel-texto");
    const actualizarBoton = () => {
      const tema = localStorage.getItem(CLAVE_TEMA) || "system";
      const { icono, texto } = ETIQUETAS_TEMA[tema];
      if (iconoUse) iconoUse.setAttribute("href", URL_ICONOS + "#icono-" + icono);
      if (textoSpan) textoSpan.textContent = texto;
      boton.title = "Tema actual: " + texto + " (clic para cambiar)";
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

  const CLAVE_DENSIDAD = "guilda-work-densidad";
  const ORDEN_DENSIDADES = ["normal", "compacta"];
  const ETIQUETAS_DENSIDAD = { normal: "Normal", compacta: "Compacta" };

  const botonDensidad = document.getElementById("densidad-toggle");
  if (botonDensidad) {
    // Icono fijo (layout-list, ya en el HTML) -- solo cambia el texto,
    // igual que antes, sin necesidad de swap de icono.
    const textoSpanDensidad = botonDensidad.querySelector(".ajustes-panel-texto");
    const actualizarBotonDensidad = () => {
      const densidad = localStorage.getItem(CLAVE_DENSIDAD) || "normal";
      if (textoSpanDensidad) textoSpanDensidad.textContent = ETIQUETAS_DENSIDAD[densidad];
      botonDensidad.title = "Densidad actual: " + ETIQUETAS_DENSIDAD[densidad] + " (clic para cambiar)";
    };
    actualizarBotonDensidad();

    botonDensidad.addEventListener("click", () => {
      const actual = localStorage.getItem(CLAVE_DENSIDAD) || "normal";
      const siguiente = ORDEN_DENSIDADES[(ORDEN_DENSIDADES.indexOf(actual) + 1) % ORDEN_DENSIDADES.length];
      localStorage.setItem(CLAVE_DENSIDAD, siguiente);
      if (siguiente === "normal") {
        delete document.documentElement.dataset.densidad;
      } else {
        document.documentElement.dataset.densidad = siguiente;
      }
      actualizarBotonDensidad();
    });
  }

  const railToggle = document.getElementById("rail-toggle");
  if (railToggle) {
    railToggle.addEventListener("click", () => {
      const expandido = document.documentElement.dataset.railExpandido === "1";
      if (expandido) {
        delete document.documentElement.dataset.railExpandido;
        localStorage.removeItem("guilda-work-rail-expandido");
      } else {
        document.documentElement.dataset.railExpandido = "1";
        localStorage.setItem("guilda-work-rail-expandido", "1");
      }
    });
  }

  const ajustesToggle = document.getElementById("ajustes-toggle");
  const ajustesPanel = document.getElementById("ajustes-panel");
  if (ajustesToggle && ajustesPanel) {
    ajustesToggle.addEventListener("click", (e) => {
      e.stopPropagation();
      ajustesPanel.hidden = !ajustesPanel.hidden;
    });
    document.addEventListener("click", (e) => {
      if (!ajustesPanel.hidden && !ajustesPanel.contains(e.target) && e.target !== ajustesToggle) {
        ajustesPanel.hidden = true;
      }
    });
  }
})();

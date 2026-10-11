// Cabecera de la app: selector de tema (claro/oscuro/sistema), selector de
// densidad, y el menú desplegable de ajustes (⚙) de la barra superior. El
// tema ya se aplica antes de pintar mediante el script inline en <head> de
// base.html — este archivo solo gestiona el clic para rotarlo y refleja el
// estado en el botón. La lista de proyectos (favoritos/reordenar) vive en el
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

  // Móvil (<= 640 px): el menú lateral es un panel que se abre con el botón de la barra superior. Estado en <html data-menu-movil>.
  const movil = window.matchMedia("(max-width: 640px)");
  const botonMenuMovil = document.getElementById("menu-movil-abrir");
  const fondoMenuMovil = document.getElementById("rail-fondo");
  const panelMenuMovil = document.getElementById("rail-principal");
  const menuMovilAbierto = () => document.documentElement.dataset.menuMovil === "1";
  const fijarMenuMovil = (abierto) => {
    if (abierto) document.documentElement.dataset.menuMovil = "1";
    else delete document.documentElement.dataset.menuMovil;
    if (botonMenuMovil) botonMenuMovil.setAttribute("aria-expanded", abierto ? "true" : "false");
    if (fondoMenuMovil) fondoMenuMovil.hidden = !abierto;
    if (abierto && panelMenuMovil) {
      const primero = panelMenuMovil.querySelector("a, button");
      if (primero) primero.focus();
    } else if (!abierto && botonMenuMovil && movil.matches) {
      botonMenuMovil.focus();
    }
  };
  if (botonMenuMovil) botonMenuMovil.addEventListener("click", () => fijarMenuMovil(!menuMovilAbierto()));
  if (fondoMenuMovil) fondoMenuMovil.addEventListener("click", () => fijarMenuMovil(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && menuMovilAbierto()) fijarMenuMovil(false); });
  movil.addEventListener("change", () => { if (!movil.matches && menuMovilAbierto()) fijarMenuMovil(false); });
  if (panelMenuMovil) panelMenuMovil.addEventListener("click", (e) => { if (movil.matches && e.target.closest("a[href]")) fijarMenuMovil(false); });

  const railToggle = document.getElementById("rail-toggle");
  if (railToggle) {
    railToggle.addEventListener("click", () => {
      if (movil.matches) { fijarMenuMovil(false); return; }   // en móvil este botón cierra el panel
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

  const ajustesToggle = document.getElementById("perfil-toggle");
  const ajustesPanel = document.getElementById("perfil-panel");
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

  // Buscador del rail: abre el mismo modal que el botón de la barra
  // superior (static/busqueda.js escucha ese botón, no hay que duplicarlo).
  const railBuscar = document.getElementById("rail-buscar");
  if (railBuscar) {
    railBuscar.addEventListener("click", () => {
      const abrir = document.getElementById("busqueda-abrir");
      if (abrir) abrir.click();
    });
  }

  // Grupos plegables del rail (Correo, Fiscal) -- el chevron alterna
  // "is-abierto" sin navegar; el enlace padre sigue navegando normal
  // a su hijo principal (ver base.html, mismo comportamiento en
  // colapsado que un icono suelto de siempre).
  document.querySelectorAll(".icon-rail-grupo-plegable").forEach((grupo) => {
    const chevron = grupo.querySelector(".icon-rail-chevron");
    if (!chevron) return;
    chevron.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      grupo.classList.toggle("is-abierto");
    });
  });
})();

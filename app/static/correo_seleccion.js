// Selección múltiple de mensajes con checkboxes + barra de acciones en
// lote, al estilo Outlook. Sin SPA: cada acción hace un fetch a una ruta en
// lote de app/rutas_correo.py y recarga la página al terminar.
(function () {
  const lista = document.getElementById("correo-lista-mensajes");
  const barra = document.getElementById("correo-bulkbar");
  if (!lista || !barra) return;

  const contador = document.getElementById("correo-bulkbar-cuenta");
  const selectCarpeta = document.getElementById("correo-bulkbar-carpeta");

  function idsSeleccionados() {
    return Array.from(lista.querySelectorAll(".correo-fila-check:checked")).map((c) => c.dataset.mensajeId);
  }

  function actualizarBarra() {
    const ids = idsSeleccionados();
    if (ids.length === 0) {
      barra.hidden = true;
      return;
    }
    barra.hidden = false;
    contador.textContent = ids.length + (ids.length === 1 ? " seleccionado" : " seleccionados");
  }

  const todas = Array.from(lista.querySelectorAll(".correo-fila-check"));
  const seleccionarTodo = document.getElementById("correo-seleccionar-todo");
  let ultimaMarcada = null;

  function sincronizarSeleccionarTodo() {
    if (!seleccionarTodo) return;
    const marcadas = todas.filter((c) => c.checked).length;
    seleccionarTodo.checked = marcadas > 0 && marcadas === todas.length;
    seleccionarTodo.indeterminate = marcadas > 0 && marcadas < todas.length;
  }

  todas.forEach((casilla, indice) => {
    casilla.addEventListener("click", (e) => {
      e.stopPropagation();
      // Mayús + clic marca (o desmarca) todo el tramo desde la última casilla pulsada, como en cualquier gestor de correo.
      if (e.shiftKey && ultimaMarcada !== null) {
        const [desde, hasta] = [Math.min(ultimaMarcada, indice), Math.max(ultimaMarcada, indice)];
        for (let i = desde; i <= hasta; i++) todas[i].checked = casilla.checked;
      }
      ultimaMarcada = indice;
    });
    casilla.addEventListener("change", () => { actualizarBarra(); sincronizarSeleccionarTodo(); });
  });

  if (seleccionarTodo) {
    seleccionarTodo.addEventListener("change", () => {
      todas.forEach((c) => (c.checked = seleccionarTodo.checked));
      actualizarBarra();
    });
  }

  document.getElementById("correo-bulkbar-cancelar").addEventListener("click", () => {
    lista.querySelectorAll(".correo-fila-check:checked").forEach((c) => (c.checked = false));
    actualizarBarra();
    sincronizarSeleccionarTodo();
  });

  // Doble clic en un mensaje: entra en "modo pantalla completa" (oculta
  // el rail de cuentas y la lista, ver .correo-shell.es-pantalla-completa
  // en style.css) -- pedido explícitamente porque las columnas fijas de
  // 220px+340px dejan poco sitio para leer. Un solo clic sigue
  // navegando tal cual (recarga con ?mensaje_id=), así que no hace
  // falta prevenir el primer clic: en el SEGUNDO clic de un doble clic,
  // `e.detail` vale 2 (lo reporta el propio navegador, sin temporizador
  // a mano) -- ahí se cancela la navegación normal y se repite con
  // &completa=1 añadido.
  lista.querySelectorAll(".correo-fila-contenido").forEach((enlace) => {
    enlace.addEventListener("click", (e) => {
      if (e.detail < 2) return;
      e.preventDefault();
      const url = new URL(enlace.href, window.location.origin);
      url.searchParams.set("completa", "1");
      window.location.href = url.toString();
    });
  });

  const i18n = window.GUILDA_I18N || {};

  // «Posponer»: las opciones fijas se convierten en una fecha y hora locales («2026-11-04T09:00»).
  function momentoParaPosponer(clave) {
    const d = new Date();
    if (clave === "hoy") d.setHours(16, 0, 0, 0);
    else if (clave === "manana") { d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); }
    else if (clave === "lunes") { d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7)); d.setHours(9, 0, 0, 0); }
    else return null;
    const dos = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + dos(d.getMonth() + 1) + "-" + dos(d.getDate()) + "T" + dos(d.getHours()) + ":" + dos(d.getMinutes());
  }

  // Los desplegables (posponer, categoría, cliente) actúan al elegir una opción; los botones, al pulsarlos.
  const controles = Array.from(barra.querySelectorAll("[data-accion], [data-accion-cambio]"));
  controles.forEach((boton) => {
    const alElegir = boton.tagName === "SELECT";
    boton.addEventListener(alElegir ? "change" : "click", async () => {
      const ids = idsSeleccionados();
      if (ids.length === 0) return;
      const accion = boton.dataset.accion || boton.dataset.accionCambio;
      if (alElegir && boton.value === "") return;
      const cuerpo = { ids };
      let url = "";
      let mensajeOk;

      if (accion === "eliminar") {
        const pregunta = (i18n.correoEliminarConfirmar || "¿Eliminar __N__ mensaje(s) de la caché local? No se puede deshacer.").replace("__N__", ids.length);
        if (!(await (window.GuildaDS ? window.GuildaDS.confirmar(pregunta, { peligro: true }) : Promise.resolve(window.confirm(pregunta))))) return;
        url = "/correo/mensajes/eliminar";
        mensajeOk = i18n.correoEliminarOk;
      } else if (accion === "marcar-leido") {
        cuerpo.leido = boton.dataset.valor === "true";
        url = "/correo/mensajes/marcar-leido";
        mensajeOk = i18n.correoMarcarLeidoOk;
      } else if (accion === "destacar") {
        cuerpo.destacado = boton.dataset.valor === "true";
        url = "/correo/mensajes/destacar";
        mensajeOk = i18n.correoDestacarOk;
      } else if (accion === "mover") {
        if (!selectCarpeta || !selectCarpeta.value) return;
        cuerpo.carpeta = selectCarpeta.value;
        url = "/correo/mensajes/mover";
        mensajeOk = i18n.correoMoverOk;
      } else if (accion === "archivar") {
        url = "/correo/mensajes/archivar";
        mensajeOk = i18n.correoArchivarOk;
      } else if (accion === "spam") {
        url = "/correo/mensajes/spam";
        mensajeOk = i18n.correoSpamOk;
      } else if (accion === "crear-tarea") {
        url = "/correo/mensajes/crear-tarea";
        mensajeOk = i18n.correoTareasOk;
      } else if (accion === "posponer") {
        cuerpo.hasta = momentoParaPosponer(boton.value);
        url = "/correo/mensajes/posponer";
        mensajeOk = i18n.correoPosponerOk;
      } else if (accion === "categoria") {
        cuerpo.categoria_id = boton.value === "0" ? "" : boton.value;
        url = "/correo/mensajes/categoria";
        mensajeOk = i18n.correoCategoriaOk;
      } else if (accion === "cliente-fiscal") {
        cuerpo.cliente_fiscal_id = boton.value === "0" ? "" : boton.value;
        url = "/correo/mensajes/cliente-fiscal";
        mensajeOk = i18n.correoClienteOk;
      } else {
        return;
      }

      try {
        const respuesta = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(cuerpo),
        });
        if (!respuesta.ok) throw new Error("HTTP " + respuesta.status);
        // "mover" es la única acción que toca el servidor IMAP de verdad
        // (las otras tres son solo caché local, ver app/correo.py) -- es
        // la única que puede fallar a medias y devolver `errores` sin que
        // la petición entera falle. Antes esto se perdía: solo se miraba
        // respuesta.ok, nunca el cuerpo, así que un fallo parcial se veía
        // igual que un éxito total.
        const datos = await respuesta.json().catch(() => ({}));
        if (datos.errores && datos.errores.length > 0) {
          const plantilla = i18n.correoParcial || "completados -- fallos:";
          const mensaje = (datos.procesados || 0) + "/" + ids.length + " " + plantilla + " " + datos.errores.join(" · ");
          if (window.mostrarToast) window.mostrarToast(mensaje, "error");
        } else if (window.mostrarToast && mensajeOk) {
          window.mostrarToast(mensajeOk, "exito");
        }
        window.location.reload();
      } catch (err) {
        if (window.mostrarToast) {
          window.mostrarToast(i18n.correoAccionError || "No se pudo completar la acción.", "error");
        }
      }
    });
  });
})();

// Categoría / cliente fiscal del mensaje abierto: antes cada cambio en
// el <select> mandaba `this.form.requestSubmit()` (recarga completa de
// la página para actualizar un solo campo). Ahora se envía por fetch --
// el color del borde del propio <select> se actualiza al momento desde
// el data-color de la opción elegida, sin esperar a que vuelva el
// servidor (ver categorias en correo_bandeja.html). El backend no ha
// cambiado: la ruta sigue devolviendo un redirect normal, que fetch()
// sigue en silencio -- solo interesa que la petición haya funcionado,
// el cuerpo de la respuesta se descarta.
(function () {
  document.querySelectorAll("form[data-fetch-submit] select").forEach(function (select) {
    var form = select.closest("form");
    if (!form) return;
    select.addEventListener("change", async function () {
      var opcion = select.selectedOptions[0];
      if (opcion && opcion.dataset.color !== undefined) {
        select.style.borderColor = opcion.dataset.color || "";
      }
      try {
        const respuesta = await fetch(form.action, { method: "POST", body: new FormData(form) });
        if (!respuesta.ok) throw new Error("HTTP " + respuesta.status);
        if (window.mostrarToast) {
          window.mostrarToast(form.dataset.mensajeOk || "Guardado.", "exito");
        }
      } catch (err) {
        if (window.mostrarToast) {
          const i18n = window.GUILDA_I18N || {};
          window.mostrarToast(i18n.correoAccionError || "No se pudo completar la acción.", "error");
        }
      }
    });
  });
})();

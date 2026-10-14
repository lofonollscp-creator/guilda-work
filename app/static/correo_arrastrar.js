// Arrastrar mensajes de la lista a una carpeta del panel izquierdo: los mueve en el servidor (mismo endpoint que «Mover a…»).
(function () {
  const lista = document.getElementById("correo-lista-mensajes");
  if (!lista) return;
  const carpetas = document.querySelectorAll(".correo-carpeta-item[data-carpeta]");
  if (!carpetas.length) return;
  const i18n = window.GUILDA_I18N || {};

  function idsParaArrastrar(fila) {
    const marcadas = Array.from(lista.querySelectorAll(".correo-fila-check:checked")).map(function (c) { return c.dataset.mensajeId; });
    const propio = fila.querySelector(".correo-fila-check");
    const id = propio ? propio.dataset.mensajeId : null;
    return marcadas.length && id && marcadas.indexOf(id) !== -1 ? marcadas : (id ? [id] : []);
  }

  lista.querySelectorAll(".correo-fila-wrap").forEach(function (fila) {
    fila.setAttribute("draggable", "true");
    fila.addEventListener("dragstart", function (e) {
      const ids = idsParaArrastrar(fila);
      if (!ids.length) { e.preventDefault(); return; }
      e.dataTransfer.setData("application/x-guilda-correo", JSON.stringify(ids));
      e.dataTransfer.effectAllowed = "move";
      fila.classList.add("is-arrastrando");
    });
    fila.addEventListener("dragend", function () { fila.classList.remove("is-arrastrando"); });
  });

  carpetas.forEach(function (destino) {
    destino.addEventListener("dragover", function (e) {
      if (Array.from(e.dataTransfer.types).indexOf("application/x-guilda-correo") === -1) return;
      e.preventDefault();
      destino.classList.add("es-destino");
    });
    destino.addEventListener("dragleave", function () { destino.classList.remove("es-destino"); });
    destino.addEventListener("drop", async function (e) {
      e.preventDefault();
      destino.classList.remove("es-destino");
      let ids;
      try { ids = JSON.parse(e.dataTransfer.getData("application/x-guilda-correo")); } catch (err) { return; }
      if (!ids || !ids.length || destino.classList.contains("active")) return;
      try {
        const r = await fetch("/correo/mensajes/mover", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: ids, carpeta: destino.dataset.carpeta }) });
        const datos = await r.json().catch(function () { return {}; });
        if (!r.ok || (datos.errores && datos.errores.length)) throw new Error((datos.errores || []).join(" · ") || "HTTP " + r.status);
        if (window.mostrarToast && i18n.correoMoverOk) window.mostrarToast(i18n.correoMoverOk, "exito");
        window.location.reload();
      } catch (err) {
        if (window.mostrarToast) window.mostrarToast(String(err.message || err), "error");
      }
    });
  });
})();

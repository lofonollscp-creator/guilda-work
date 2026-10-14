// Redactar: autoguardado del borrador y adjuntos arrastrando o pegando archivos, con lista para quitarlos.
(function () {
  const form = document.querySelector("form[action$='/correo/enviar']");
  if (!form) return;
  const i18n = window.GUILDA_I18N || {};
  const editor = document.getElementById("correo-editor-cuerpo");
  const oculto = document.getElementById("correo-editor-campo-oculto");
  const campoBorrador = document.getElementById("correo-borrador-id");
  const boton = document.getElementById("correo-guardar-borrador");
  const estado = document.getElementById("correo-autoguardado-estado");

  // --- Autoguardado: cada 20 s, solo si hay algo escrito y ha cambiado desde la última vez ---
  const urlBorrador = boton && boton.dataset.url;
  function instantanea() {
    const v = function (n) { const e = form.elements[n]; return e ? e.value : ""; };
    return [v("cuenta_id"), v("destinatarios"), v("cc"), v("bcc"), v("asunto"), editor ? editor.innerHTML : ""].join("\u0001");
  }
  let ultima = instantanea();
  let guardando = false;
  async function autoguardar() {
    if (!urlBorrador || guardando) return;
    const ahora = instantanea();
    const hayTexto = form.elements.asunto.value.trim() || (editor && editor.textContent.trim()) || form.elements.destinatarios.value.trim();
    if (ahora === ultima || !hayTexto) return;
    guardando = true;
    try {
      if (editor && oculto) oculto.value = editor.innerHTML;
      const datos = new FormData(form);
      datos.delete("adjuntos");          // los archivos no se guardan en el borrador: no se vuelven a subir cada vez
      const r = await fetch(urlBorrador, { method: "POST", body: datos });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const j = await r.json();
      if (campoBorrador) campoBorrador.value = j.borrador_id;
      ultima = ahora;
      if (estado) estado.textContent = (i18n.correoBorradorAuto || "Borrador guardado") + " " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch (e) {
      if (estado) estado.textContent = i18n.correoBorradorFallo || "No se pudo guardar el borrador";
    } finally {
      guardando = false;
    }
  }
  setInterval(autoguardar, 20000);
  form.addEventListener("submit", function () { ultima = instantanea(); });

  // --- Adjuntos: arrastrar, pegar y quitar ---
  const entrada = form.querySelector("input[type='file'][name='adjuntos']");
  const lista = document.getElementById("correo-adjuntos-lista");
  if (!entrada || !lista) return;
  const MAX = 25 * 1024 * 1024;
  let dt = new DataTransfer();

  function tamano(n) { return n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB"; }
  function pintar() {
    lista.textContent = "";
    let total = 0;
    Array.from(dt.files).forEach(function (f, i) {
      total += f.size;
      const li = document.createElement("li");
      li.textContent = f.name + " (" + tamano(f.size) + ") ";
      const quitar = document.createElement("button");
      quitar.type = "button"; quitar.className = "btn btn-ghost"; quitar.textContent = "×";
      quitar.setAttribute("aria-label", (i18n.correoQuitarAdjunto || "Quitar") + " " + f.name);
      quitar.addEventListener("click", function () {
        const nuevo = new DataTransfer();
        Array.from(dt.files).forEach(function (g, j) { if (j !== i) nuevo.items.add(g); });
        dt = nuevo; entrada.files = dt.files; pintar();
      });
      li.appendChild(quitar);
      lista.appendChild(li);
    });
    lista.hidden = dt.files.length === 0;
    const nombre = form.querySelector(".file-input-nombre");
    if (nombre) nombre.textContent = dt.files.length ? dt.files.length + " · " + tamano(total) : (i18n.correoSinArchivos || nombre.textContent);
    if (total > MAX && window.mostrarToast) window.mostrarToast(i18n.correoAdjuntosGrandes || "Los adjuntos superan los 25 MB.", "error");
  }
  function anadir(archivos) {
    Array.from(archivos).forEach(function (f) { dt.items.add(f); });
    entrada.files = dt.files;
    pintar();
  }
  entrada.addEventListener("change", function () {
    const nuevos = Array.from(entrada.files);
    const previos = Array.from(dt.files);
    dt = new DataTransfer();
    previos.concat(nuevos.filter(function (f) { return !previos.some(function (p) { return p === f; }); })).forEach(function (f) { dt.items.add(f); });
    entrada.files = dt.files;
    pintar();
  });
  const zona = form.closest(".correo-compose") || form;
  ["dragenter", "dragover"].forEach(function (ev) {
    zona.addEventListener(ev, function (e) {
      if (e.dataTransfer && Array.from(e.dataTransfer.types).indexOf("Files") !== -1) { e.preventDefault(); zona.classList.add("es-destino-archivos"); }
    });
  });
  zona.addEventListener("dragleave", function (e) { if (e.target === zona) zona.classList.remove("es-destino-archivos"); });
  zona.addEventListener("drop", function (e) {
    zona.classList.remove("es-destino-archivos");
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) { e.preventDefault(); anadir(e.dataTransfer.files); }
  });
  if (editor) editor.addEventListener("paste", function (e) {
    const archivos = e.clipboardData && e.clipboardData.files;
    if (archivos && archivos.length && !e.clipboardData.getData("text/html")) { e.preventDefault(); anadir(archivos); }
  });
})();

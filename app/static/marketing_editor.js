// Editor visual de plantillas de correo (Marketing). Mejora el formulario normal: si este script no carga, el formulario sigue funcionando igual.
// Cada bloque es un <fieldset class="mk-bloque"> con sus campos tipo/texto/url; aquí se les añade arrastrar y soltar, subir/bajar, quitar, añadir desde la paleta
// y una vista previa en vivo que pide el HTML al servidor (una sola fuente de verdad: el mismo código que arma el correo real).
(function () {
  "use strict";
  var lista = document.getElementById("mk-bloques");
  if (!lista) return;
  var formulario = lista.closest("form");
  var plantilla = document.getElementById("mk-bloque-plantilla");
  var marco = document.getElementById("mk-vista-en-vivo");
  var estado = document.getElementById("mk-estado");
  var urlVista = lista.dataset.urlVista;
  var textos = JSON.parse(lista.dataset.textos || "{}");
  var arrastrado = null;
  var temporizador = null;
  var peticion = 0;

  function anunciar(mensaje) { if (estado) estado.textContent = mensaje; }

  function bloques() { return Array.prototype.slice.call(lista.querySelectorAll(".mk-bloque")); }

  function datos() {
    return bloques().map(function (b) {
      return { tipo: b.querySelector('[name="tipo"]').value, texto: b.querySelector('[name="texto"]').value, url: b.querySelector('[name="url"]').value };
    }).filter(function (b) { return b.tipo === "divisor" || b.texto.trim() || (b.tipo === "imagen" && b.url.trim()); });
  }

  function refrescarTipo(b) { b.dataset.tipo = b.querySelector('[name="tipo"]').value; }

  function vistaPrevia() {
    if (!marco || !urlVista) return;
    var esta = ++peticion;
    fetch(urlVista, { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ bloques: datos() }) })
      .then(function (r) { return r.json(); })
      .then(function (r) {
        if (esta !== peticion) return;                                   // llegó tarde: ya hay una petición más nueva
        if (r.html) { marco.srcdoc = r.html; marco.classList.remove("mk-con-error"); }
        if (r.error) { anunciar(r.error); marco.classList.add("mk-con-error"); } else { anunciar(""); }
      })
      .catch(function () { /* sin vista previa, pero se puede seguir editando y guardando */ });
  }

  function programarVista() { clearTimeout(temporizador); temporizador = setTimeout(vistaPrevia, 400); }

  function mover(b, delta) {
    var todos = bloques(), i = todos.indexOf(b), j = i + delta;
    if (j < 0 || j >= todos.length) return;
    lista.insertBefore(b, delta < 0 ? todos[j] : todos[j].nextSibling);
    anunciar(textos.movido + " " + (j + 1));
    b.querySelector('[data-mk="mover"]').focus();
    programarVista();
  }

  function adornar(b) {
    if (b.dataset.listo) return;
    b.dataset.listo = "1";
    refrescarTipo(b);
    var barra = document.createElement("div");
    barra.className = "mk-barra";
    function boton(clave, etiqueta, texto) {
      var x = document.createElement("button");
      x.type = "button"; x.className = "btn btn-ghost btn-sm"; x.dataset.mk = clave; x.title = etiqueta; x.setAttribute("aria-label", etiqueta); x.textContent = texto;
      return x;
    }
    var asa = boton("mover", textos.arrastrar, "⠿");
    asa.classList.add("mk-asa");
    var subir = boton("subir", textos.subir, "↑"), bajar = boton("bajar", textos.bajar, "↓"), quitar = boton("quitar", textos.quitar, "×");
    [asa, subir, bajar, quitar].forEach(function (x) { barra.appendChild(x); });
    b.insertBefore(barra, b.firstChild);
    b.draggable = false;
    asa.addEventListener("mousedown", function () { b.draggable = true; });
    asa.addEventListener("mouseup", function () { b.draggable = false; });
    b.addEventListener("dragstart", function (e) { arrastrado = b; b.classList.add("mk-arrastrando"); e.dataTransfer.effectAllowed = "move"; try { e.dataTransfer.setData("text/plain", "bloque"); } catch (_) { /* Safari antiguo */ } });
    b.addEventListener("dragend", function () { b.draggable = false; b.classList.remove("mk-arrastrando"); arrastrado = null; bloques().forEach(function (x) { x.classList.remove("mk-sobre"); }); programarVista(); });
    b.addEventListener("dragover", function (e) { if (!arrastrado || arrastrado === b) return; e.preventDefault(); e.dataTransfer.dropEffect = "move"; b.classList.add("mk-sobre"); });
    b.addEventListener("dragleave", function () { b.classList.remove("mk-sobre"); });
    b.addEventListener("drop", function (e) {
      if (!arrastrado || arrastrado === b) return;
      e.preventDefault(); b.classList.remove("mk-sobre");
      var todos = bloques();
      lista.insertBefore(arrastrado, todos.indexOf(arrastrado) < todos.indexOf(b) ? b.nextSibling : b);
      anunciar(textos.movido + " " + (bloques().indexOf(arrastrado) + 1));
    });
    subir.addEventListener("click", function () { mover(b, -1); });
    bajar.addEventListener("click", function () { mover(b, 1); });
    quitar.addEventListener("click", function () { b.remove(); anunciar(textos.quitado); programarVista(); });
    b.querySelector('[name="tipo"]').addEventListener("change", function () { refrescarTipo(b); programarVista(); });
  }

  function anadir(tipo) {
    var nodo = plantilla.content.firstElementChild.cloneNode(true);
    nodo.querySelector('[name="tipo"]').value = tipo;
    if (tipo === "boton") nodo.querySelector('[name="url"]').value = "https://";
    lista.appendChild(nodo);
    adornar(nodo);
    var campo = nodo.querySelector('[name="texto"]');
    if (campo) campo.focus();
    anunciar(textos.anadido);
    programarVista();
  }

  bloques().forEach(adornar);
  document.querySelectorAll("[data-mk-anadir]").forEach(function (x) { x.hidden = false; x.addEventListener("click", function () { anadir(x.dataset.mkAnadir); }); });   // la paleta solo aparece si el script funciona
  // soltar un bloque de la paleta (o cualquier cosa) en el espacio libre de la lista lo añade al final
  lista.addEventListener("dragover", function (e) { if (!arrastrado) e.preventDefault(); });
  lista.addEventListener("input", programarVista);
  formulario.addEventListener("submit", function () {
    // los bloques vacíos no se envían: el servidor ya los descarta, pero así el formulario es más corto
    bloques().forEach(function (b) { var t = b.querySelector('[name="tipo"]').value; if (t !== "divisor" && !b.querySelector('[name="texto"]').value.trim() && !(t === "imagen" && b.querySelector('[name="url"]').value.trim())) b.remove(); });
  });
  vistaPrevia();
})();

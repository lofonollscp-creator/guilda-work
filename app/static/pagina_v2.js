/* Web v2: el título de cada pantalla vive en la barra superior. Las pantallas que aún llevan su cabecera propia (header.page-header)
   la ceden a la barra: el título y el subtítulo suben, la acción principal (un enlace .btn-primary) sustituye al «+ Nuevo» y el resto
   de acciones se quedan en la página. El h1 sigue en el DOM (solo para lectores de pantalla).
   Si el h1 lleva etiquetas dentro (estado del proyecto, tipo de cliente…), el nombre y las etiquetas suben a la barra y la cabecera
   conserva su icono/avatar, subtítulo y acciones. */
(function () {
  "use strict";
  var titulo = document.querySelector(".top-bar-titulo");
  var cabecera = document.querySelector("main.content > header.page-header:not(.sr-only):not(.dash-header)");
  if (!titulo || !cabecera) return;
  var h1 = cabecera.querySelector("h1");
  if (!h1 || !h1.textContent.trim()) return;

  function moverAccionPrincipal() {
    var principal = cabecera.querySelector("a.btn-primary[href]");
    var nuevo = document.querySelector(".top-bar-acciones > details.top-bar-nuevo");
    if (principal && nuevo && !principal.closest("form")) {
      principal.classList.add("top-bar-accion", "top-bar-nuevo-btn");
      nuevo.replaceWith(principal);
    }
  }

  if (titulo.textContent.trim()) {        // la barra ya trae su título (Tareas, Correo…): el h1 repetido solo queda para lectores de pantalla
    if (titulo.textContent.trim().indexOf(h1.textContent.trim()) === 0) cabecera.classList.add("h1-en-barra");
    return;
  }

  var etiquetas = h1.children.length ? Array.prototype.slice.call(h1.children) : [];
  if (etiquetas.length) {
    var nombre = "";
    for (var i = 0; i < h1.childNodes.length; i++) { if (h1.childNodes[i].nodeType === 3 && h1.childNodes[i].textContent.trim()) { nombre = h1.childNodes[i].textContent.trim(); break; } }
    titulo.textContent = nombre || h1.textContent.trim();
    etiquetas.forEach(function (e) { var c = e.cloneNode(true); c.setAttribute("aria-hidden", "true"); titulo.appendChild(c); });
    cabecera.classList.add("h1-en-barra");
    moverAccionPrincipal();
    return;
  }

  titulo.textContent = h1.textContent.trim();
  var sub = cabecera.querySelector(".subtitle");
  if (sub && sub.textContent.trim()) {
    var s = document.createElement("span");
    s.className = "top-bar-subtitulo";
    s.textContent = sub.textContent.trim();
    titulo.appendChild(s);
  }
  cabecera.classList.add("titulo-en-barra");
  moverAccionPrincipal();
  if (!cabecera.querySelector(".ds-fila, form, .btn, a")) cabecera.classList.add("sin-acciones");
})();

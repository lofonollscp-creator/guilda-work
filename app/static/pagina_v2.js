/* Web v2: el título de cada pantalla vive en la barra superior. Las pantallas que aún llevan su cabecera propia (header.page-header)
   la ceden a la barra: el título y el subtítulo suben, la acción principal (un enlace .btn-primary) sustituye al «+ Nuevo» y el resto
   de acciones se quedan en la página. El h1 sigue en el DOM (solo para lectores de pantalla). */
(function () {
  "use strict";
  var titulo = document.querySelector(".top-bar-titulo");
  var cabecera = document.querySelector("main.content > header.page-header:not(.sr-only):not(.dash-header)");
  if (!titulo || !cabecera) return;
  var h1 = cabecera.querySelector("h1");
  if (!h1 || !h1.textContent.trim()) return;
  if (cabecera.classList.contains("proyecto-cabecera") && !titulo.textContent.trim()) {   // proyecto: nombre + estado en la barra; icono y subtítulo se quedan
    var nombre = (h1.firstChild && h1.firstChild.textContent || h1.textContent).trim();
    titulo.textContent = nombre;
    var estado = h1.querySelector(".proyecto-estado");
    if (estado) { var e = estado.cloneNode(true); e.setAttribute("aria-hidden", "true"); titulo.appendChild(e); }
    cabecera.classList.add("h1-en-barra");
    return;
  }
  if (titulo.textContent.trim()) {        // la barra ya trae su título (Tareas, Correo…): el h1 repetido solo queda para lectores de pantalla
    if (titulo.textContent.trim().indexOf(h1.textContent.trim()) === 0) cabecera.classList.add("h1-en-barra");
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
  var principal = cabecera.querySelector("a.btn-primary[href]");
  var nuevo = document.querySelector(".top-bar-acciones > details.top-bar-nuevo");
  if (principal && nuevo && !principal.closest("form")) {
    principal.classList.add("top-bar-accion", "top-bar-nuevo-btn");
    nuevo.replaceWith(principal);
  }
  if (!cabecera.querySelector(".ds-fila, form, .btn, a")) cabecera.classList.add("sin-acciones");
})();

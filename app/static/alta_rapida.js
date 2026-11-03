/* Autocompletado del alta rápida de tareas: al escribir «@» ofrece personas, con «#» proyectos o secciones y con «!» la prioridad. Teclado: ↑ ↓ para moverse, Intro o Tab para elegir, Esc para cerrar.
   Se activa en los campos con data-alta-rapida; data-sugerencias es la URL que da las opciones (se pide la primera vez que se enfoca el campo). Si trae data-interpretar y data-previa (id de un
   elemento), enseña en vivo lo que el alta ha entendido del texto. */
(function () {
  "use strict";
  var PRIORIDADES = [{ nombre: "alta", insertar: "!alta" }, { nombre: "normal", insertar: "!normal" }, { nombre: "baja", insertar: "!baja" }];

  function sinAcentos(t) { return (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }

  function activar(campo) {
    var opciones = null, pidiendo = false;
    var lista = document.createElement("ul");
    lista.className = "alta-sugerencias";
    lista.id = "alta-sugerencias-" + Math.random().toString(36).slice(2, 8);
    lista.setAttribute("role", "listbox");
    lista.setAttribute("aria-label", campo.dataset.tSugerencias || "Suggestions");
    lista.hidden = true;
    document.body.appendChild(lista);
    campo.setAttribute("role", "combobox");
    campo.setAttribute("aria-autocomplete", "list");
    campo.setAttribute("aria-expanded", "false");
    campo.setAttribute("aria-controls", lista.id);

    var visibles = [], activa = -1, token = null;

    function cargar() {
      if (opciones || pidiendo || !campo.dataset.sugerencias) return;
      pidiendo = true;
      fetch(campo.dataset.sugerencias, { credentials: "same-origin", headers: { "Accept": "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { opciones = d || { personas: [], etiquetas: [] }; pidiendo = false; actualizar(); })
        .catch(function () { pidiendo = false; });
    }

    function cerrar() {
      lista.hidden = true; visibles = []; activa = -1; token = null;
      campo.setAttribute("aria-expanded", "false");
      campo.removeAttribute("aria-activedescendant");
    }

    function posicionar() {
      var r = campo.getBoundingClientRect();
      lista.style.left = Math.round(r.left) + "px";
      lista.style.top = Math.round(r.bottom + 4) + "px";
      lista.style.minWidth = Math.min(Math.round(r.width), 320) + "px";
    }

    function pintar() {
      lista.textContent = "";
      visibles.forEach(function (o, i) {
        var li = document.createElement("li");
        li.id = lista.id + "-" + i;
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", i === activa ? "true" : "false");
        li.className = "alta-sugerencia" + (i === activa ? " es-activa" : "");
        var marca = document.createElement("span");
        marca.className = "alta-sugerencia-marca";
        marca.textContent = o.insertar.charAt(0);
        var texto = document.createElement("span");
        texto.textContent = o.nombre;
        li.appendChild(marca); li.appendChild(texto);
        li.addEventListener("mousedown", function (e) { e.preventDefault(); elegir(i); });
        lista.appendChild(li);
      });
      if (activa >= 0) campo.setAttribute("aria-activedescendant", lista.id + "-" + activa);
      else campo.removeAttribute("aria-activedescendant");
    }

    function actualizar() {
      var antes = campo.value.slice(0, campo.selectionStart == null ? campo.value.length : campo.selectionStart);
      var m = /(^|\s)([@#!])("?)([^\s"@#!]*)$/.exec(antes) || /(^|\s)(#)"([^"]*)$/.exec(antes);
      if (!m) { cerrar(); return; }
      var marca = m[2], consulta = sinAcentos(m.length === 5 ? m[4] : m[3]);
      var origen = marca === "@" ? (opciones && opciones.personas) : marca === "#" ? (opciones && opciones.etiquetas) : PRIORIDADES;
      if (!origen) { cerrar(); return; }
      var palabras = consulta.split(/\s+/).filter(Boolean);
      var coinciden = origen.filter(function (o) {
        var n = sinAcentos(o.nombre);
        return palabras.every(function (p) { return n.indexOf(p) !== -1; });
      });
      coinciden.sort(function (a, b) { return (sinAcentos(a.nombre).indexOf(consulta) === 0 ? 0 : 1) - (sinAcentos(b.nombre).indexOf(consulta) === 0 ? 0 : 1); });
      visibles = coinciden.slice(0, 6);
      if (!visibles.length || (visibles.length === 1 && visibles[0].insertar.toLowerCase() === (marca + (m.length === 5 ? m[4] : m[3])).toLowerCase())) { cerrar(); return; }
      token = { inicio: antes.lastIndexOf(marca), fin: antes.length };        // el tramo a sustituir va desde la marca hasta el cursor
      if (activa < 0 || activa >= visibles.length) activa = 0;
      pintar(); posicionar();
      lista.hidden = false;
      campo.setAttribute("aria-expanded", "true");
    }

    function elegir(i) {
      var o = visibles[i];
      if (!o || !token) { cerrar(); return; }
      var despues = campo.value.slice(token.fin);
      var nuevo = campo.value.slice(0, token.inicio) + o.insertar + " " + despues.replace(/^\s+/, "");
      var cursor = token.inicio + o.insertar.length + 1;
      campo.value = nuevo;
      campo.setSelectionRange(cursor, cursor);
      cerrar();
      campo.dispatchEvent(new Event("input", { bubbles: true }));
      campo.focus();
    }

    campo.addEventListener("focus", cargar);
    campo.addEventListener("input", function () { cargar(); activa = 0; actualizar(); });
    campo.addEventListener("click", actualizar);
    campo.addEventListener("keyup", function (e) { if (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "Home" || e.key === "End") actualizar(); });
    campo.addEventListener("blur", function () { setTimeout(cerrar, 120); });
    campo.addEventListener("keydown", function (e) {
      if (lista.hidden || !visibles.length) return;
      if (e.key === "ArrowDown") { e.preventDefault(); activa = (activa + 1) % visibles.length; pintar(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); activa = (activa - 1 + visibles.length) % visibles.length; pintar(); }
      else if (e.key === "Enter" || e.key === "Tab") { if (activa >= 0) { e.preventDefault(); elegir(activa); } }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cerrar(); }
    });
    window.addEventListener("resize", function () { if (!lista.hidden) posicionar(); });
    window.addEventListener("scroll", function () { if (!lista.hidden) posicionar(); }, true);

    // Vista previa en vivo de lo que ha entendido el alta (solo si la página no la hace por su cuenta).
    var previa = campo.dataset.previa && document.getElementById(campo.dataset.previa);
    if (previa && campo.dataset.interpretar) {
      var temporizador = null, ultima = "";
      var pintarPrevia = function (d) {
        var trozos = [];
        if (d.vencimiento) trozos.push((d.fecha_texto || d.vencimiento.slice(0, 10)) + (d.hora ? " " + d.hora : ""));
        if (d.persona) trozos.push("@" + d.persona);
        if (d.seccion) trozos.push("#" + d.seccion);
        if (d.prioridad) trozos.push("!" + d.prioridad);
        if (d.estimacion) trozos.push("~" + d.estimacion);
        previa.textContent = trozos.join(" · ");
        if (d.sin_resolver && d.sin_resolver.length) previa.textContent += (trozos.length ? " · " : "") + d.sin_resolver.join(" ") + " ?";
        previa.hidden = !previa.textContent;
      };
      campo.addEventListener("input", function () {
        clearTimeout(temporizador);
        var texto = campo.value;
        if (!/[@#!~]|\d|hoy|mañana|manana|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|today|tomorrow|avui|dem[aà]/i.test(texto)) { previa.hidden = true; return; }
        temporizador = setTimeout(function () {
          if (texto === ultima) return;
          ultima = texto;
          fetch(campo.dataset.interpretar + "?texto=" + encodeURIComponent(texto), { credentials: "same-origin", headers: { "Accept": "application/json" } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { if (d && campo.value === texto) pintarPrevia(d); })
            .catch(function () { previa.hidden = true; });
        }, 250);
      });
    }
  }

  document.querySelectorAll("input[data-alta-rapida]").forEach(activar);
})();

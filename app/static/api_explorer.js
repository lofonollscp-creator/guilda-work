// Explorador interactivo de /api/v1/* (/docs/explorador-api) — genera
// toda la interfaz en el cliente a partir de GET /api/v1/openapi.json
// (público, sin token). Sin dependencias externas, a propósito (mismo
// criterio "autoalojado" que el resto de la app — ver docs.js).

(function () {
  var elGrupos = document.getElementById("api-explorer-grupos");
  var elDetalle = document.getElementById("api-explorer-detalle");
  var elFiltro = document.getElementById("api-explorer-filtro");
  if (!elGrupos || !elDetalle) return;

  var ORIGEN = window.location.origin;
  var endpoints = []; // { ruta, metodo, operacion, tag }
  var botonesLista = [];

  function metodoBadge(metodo) {
    return '<span class="docs-method docs-method-' + metodo.toLowerCase() + '">' + metodo.toUpperCase() + "</span>";
  }

  function escapeHtml(s) {
    var div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function cargar() {
    fetch("/api/v1/openapi.json")
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(pintarLista)
      .catch(function (err) {
        elGrupos.innerHTML =
          '<p class="api-explorer-cargando">No se ha podido cargar /api/v1/openapi.json (' +
          escapeHtml(err.message) +
          "). ¿Está la app arrancada?</p>";
      });
  }

  function pintarLista(spec) {
    endpoints = [];
    var porTag = {};
    Object.keys(spec.paths).sort().forEach(function (ruta) {
      var operaciones = spec.paths[ruta];
      Object.keys(operaciones).forEach(function (metodo) {
        var operacion = operaciones[metodo];
        var tag = (operacion.tags && operacion.tags[0]) || "otros";
        if (!porTag[tag]) porTag[tag] = [];
        var entrada = { ruta: ruta, metodo: metodo, operacion: operacion, tag: tag };
        porTag[tag].push(entrada);
        endpoints.push(entrada);
      });
    });

    elGrupos.innerHTML = "";
    botonesLista = [];
    Object.keys(porTag).sort().forEach(function (tag) {
      var grupo = document.createElement("div");
      grupo.className = "api-explorer-grupo";
      var h3 = document.createElement("h3");
      h3.textContent = tag;
      grupo.appendChild(h3);

      porTag[tag].forEach(function (entrada) {
        var boton = document.createElement("button");
        boton.type = "button";
        boton.className = "api-explorer-endpoint";
        boton.innerHTML =
          metodoBadge(entrada.metodo) + '<span class="api-explorer-endpoint-ruta">' + escapeHtml(entrada.ruta) + "</span>";
        boton.dataset.filtro = (entrada.ruta + " " + entrada.metodo + " " + (entrada.operacion.summary || "")).toLowerCase();
        boton.addEventListener("click", function () {
          seleccionar(entrada, boton);
        });
        grupo.appendChild(boton);
        botonesLista.push(boton);
      });
      elGrupos.appendChild(grupo);
    });

    if (elFiltro) {
      elFiltro.addEventListener("input", function () {
        var q = elFiltro.value.trim().toLowerCase();
        botonesLista.forEach(function (b) {
          b.parentElement.style.display = "";
        });
        botonesLista.forEach(function (b) {
          b.style.display = q === "" || b.dataset.filtro.indexOf(q) !== -1 ? "" : "none";
        });
        // Oculta grupos que se han quedado sin ningún endpoint visible.
        document.querySelectorAll(".api-explorer-grupo").forEach(function (grupoEl) {
          var visibles = Array.from(grupoEl.querySelectorAll(".api-explorer-endpoint")).some(function (b) {
            return b.style.display !== "none";
          });
          grupoEl.style.display = visibles ? "" : "none";
        });
      });
    }

    // Selecciona el primer endpoint por defecto para que la página no
    // empiece vacía.
    if (endpoints.length) seleccionar(endpoints[0], botonesLista[0]);
  }

  function tipoParaEjemplo(propiedad) {
    if (propiedad.enum) return propiedad.enum[0];
    if (propiedad.type === "integer") return 1;
    if (propiedad.type === "number") return 1.0;
    if (propiedad.type === "boolean") return true;
    if (propiedad.type === "array") return [];
    return "...";
  }

  function generarCurl(entrada) {
    var url = ORIGEN + entrada.ruta.replace(/\{(\w+)\}/g, function (_, nombre) { return "1"; });
    var partes = ["curl -X " + entrada.metodo.toUpperCase() + " \"" + url + "\""];
    var necesitaAuth = entrada.operacion.security && entrada.operacion.security.length > 0;
    if (necesitaAuth) partes.push('  -H "Authorization: Bearer <tu-token>"');
    var cuerpo = entrada.operacion.requestBody;
    if (cuerpo) {
      var esquema = cuerpo.content["application/json"].schema;
      var ejemplo = {};
      Object.keys(esquema.properties || {}).forEach(function (campo) {
        ejemplo[campo] = tipoParaEjemplo(esquema.properties[campo]);
      });
      partes.push('  -H "Content-Type: application/json"');
      partes.push("  -d '" + JSON.stringify(ejemplo) + "'");
    }
    return partes.join(" \\\n");
  }

  function tablaParametros(parametros) {
    if (!parametros || !parametros.length) return "";
    var filas = parametros
      .map(function (p) {
        return (
          "<tr><td><code>" + escapeHtml(p.name) + "</code></td><td>" + p["in"] + "</td><td>" + p.schema.type + "</td></tr>"
        );
      })
      .join("");
    return (
      '<h2>Parámetros de camino</h2><div class="docs-table-wrap"><table class="docs-table">' +
      "<thead><tr><th>Nombre</th><th>En</th><th>Tipo</th></tr></thead><tbody>" +
      filas +
      "</tbody></table></div>"
    );
  }

  function tablaCuerpo(requestBody) {
    if (!requestBody) return "";
    var esquema = requestBody.content["application/json"].schema;
    var requeridos = esquema.required || [];
    var filas = Object.keys(esquema.properties || {})
      .map(function (campo) {
        var propiedad = esquema.properties[campo];
        var tipo = propiedad.type + (propiedad.items ? "[" + propiedad.items.type + "]" : "");
        return (
          "<tr><td><code>" +
          escapeHtml(campo) +
          "</code></td><td>" +
          tipo +
          "</td><td>" +
          (requeridos.indexOf(campo) !== -1 ? "sí" : "no") +
          "</td></tr>"
        );
      })
      .join("");
    return (
      '<h2>Cuerpo de la petición (JSON)</h2><div class="docs-table-wrap"><table class="docs-table">' +
      "<thead><tr><th>Campo</th><th>Tipo</th><th>Obligatorio</th></tr></thead><tbody>" +
      filas +
      "</tbody></table></div>"
    );
  }

  function tablaRespuestas(respuestas) {
    var filas = Object.keys(respuestas)
      .map(function (codigo) {
        return "<tr><td><code>" + codigo + "</code></td><td>" + escapeHtml(respuestas[codigo].description) + "</td></tr>";
      })
      .join("");
    return (
      '<h2>Respuestas</h2><div class="docs-table-wrap"><table class="docs-table">' +
      "<thead><tr><th>HTTP</th><th>Significado</th></tr></thead><tbody>" +
      filas +
      "</tbody></table></div>"
    );
  }

  function seleccionar(entrada, boton) {
    botonesLista.forEach(function (b) { b.classList.remove("is-activo"); });
    if (boton) boton.classList.add("is-activo");

    var op = entrada.operacion;
    var curl = generarCurl(entrada);
    elDetalle.innerHTML =
      '<div class="api-explorer-cabecera">' +
      metodoBadge(entrada.metodo) +
      '<span class="api-explorer-ruta">' + escapeHtml(entrada.ruta) + "</span>" +
      "</div>" +
      '<p class="api-explorer-resumen">' + escapeHtml(op.summary || "") + "</p>" +
      '<span class="api-explorer-auth">' +
      (op.security && op.security.length ? "🔒 Requiere Authorization: Bearer" : "🔓 Público") +
      "</span>" +
      tablaParametros(op.parameters) +
      tablaCuerpo(op.requestBody) +
      tablaRespuestas(op.responses) +
      "<h2>Ejemplo</h2>" +
      '<div class="docs-code"><div class="docs-code-cabecera"><span>curl</span>' +
      '<button type="button" class="docs-code-copiar" data-code="' + escapeHtml(curl) + '">Copiar</button></div>' +
      "<pre><code>" + escapeHtml(curl) + "</code></pre></div>";

    // El botón "Copiar" recién insertado no pasó por el listener que
    // docs.js registra en DOMContentLoaded (llegó tarde) — se engancha
    // aquí mismo, mismo comportamiento.
    var botonCopiar = elDetalle.querySelector(".docs-code-copiar");
    if (botonCopiar) {
      botonCopiar.addEventListener("click", function () {
        var texto = botonCopiar.dataset.code;
        var marcar = function () {
          botonCopiar.textContent = "Copiado";
          botonCopiar.classList.add("is-copiado");
          setTimeout(function () {
            botonCopiar.textContent = "Copiar";
            botonCopiar.classList.remove("is-copiado");
          }, 1500);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(texto).then(marcar);
        }
      });
    }
  }

  cargar();
})();

// Explorador interactivo de /api/v1/* (/docs/explorador-api) — genera toda la
// interfaz en el cliente a partir de GET /api/v1/openapi.json (público, sin
// token). Sin dependencias externas, a propósito (mismo criterio
// "autoalojado" que el resto de la app).
//
// Resuelve los $ref del documento (parámetros, respuestas, esquemas), admite
// cuerpos JSON y multipart, enlaza cada operación con #operationId y permite
// probarla con un token (solo se guarda en sessionStorage).

(function () {
  var elGrupos = document.getElementById("api-explorer-grupos");
  var elDetalle = document.getElementById("api-explorer-detalle");
  var elFiltro = document.getElementById("api-explorer-filtro");
  var elArea = document.getElementById("api-explorer-area");
  if (!elGrupos || !elDetalle) return;

  var ORIGEN = window.location.origin;
  var METODOS = ["get", "post", "put", "patch", "delete"];
  var spec = null;
  var endpoints = [];
  var botones = [];

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function badge(metodo) {
    return '<span class="docs-method docs-method-' + metodo + '">' + metodo.toUpperCase() + "</span>";
  }

  function guardado(clave, valor) {
    try {
      if (valor === undefined) return window.sessionStorage.getItem(clave);
      if (valor === null) window.sessionStorage.removeItem(clave);
      else window.sessionStorage.setItem(clave, valor);
    } catch (e) { /* almacenamiento no disponible: se sigue sin recordar */ }
    return null;
  }

  // --- $ref ---------------------------------------------------------------
  function resolver(obj) {
    var vistos = [];
    while (obj && obj.$ref) {
      if (vistos.indexOf(obj.$ref) !== -1) return {};
      vistos.push(obj.$ref);
      var partes = obj.$ref.replace(/^#\//, "").split("/");
      var destino = spec;
      for (var i = 0; i < partes.length && destino; i++) destino = destino[partes[i]];
      obj = destino || {};
    }
    return obj || {};
  }

  function nombreRef(obj) {
    return obj && obj.$ref ? obj.$ref.split("/").pop() : "";
  }

  // --- Esquemas -----------------------------------------------------------
  function tipoDe(esq) {
    var r = resolver(esq);
    var t = r.type || (r.properties ? "object" : "");
    if (nombreRef(esq)) t = nombreRef(esq);
    else if (t === "array" && r.items) t = "array<" + (nombreRef(r.items) || tipoDe(r.items) || "any") + ">";
    if (r.format) t += " (" + r.format + ")";
    if (r.nullable) t += " | null";
    return t || "any";
  }

  function filasEsquema(esq, prefijo, nivel, vistos) {
    var r = resolver(esq);
    var filas = [];
    var props = r.properties || {};
    var req = r.required || [];
    if (nivel > 2) return filas;
    Object.keys(props).forEach(function (campo) {
      var p = props[campo];
      var pr = resolver(p);
      var extra = [];
      if (pr.enum) extra.push("Valores: " + pr.enum.map(function (v) { return "<code>" + esc(v) + "</code>"; }).join(", "));
      if (pr.maxLength) extra.push("máx. " + pr.maxLength + " caracteres");
      filas.push(
        "<tr><td><code>" + esc(prefijo + campo) + "</code></td><td>" + esc(tipoDe(p)) + "</td><td>" +
        (req.indexOf(campo) !== -1 ? "sí" : "no") + "</td><td>" + esc(pr.description || "") +
        (extra.length ? '<div class="api-explorer-nota">' + extra.join(" · ") + "</div>" : "") + "</td></tr>"
      );
      var anidado = pr.type === "array" && pr.items ? pr.items : p;
      var clave = nombreRef(anidado) || nombreRef(p);
      if (resolver(anidado).properties && vistos.indexOf(clave) === -1) {
        filas = filas.concat(filasEsquema(anidado, prefijo + campo + (pr.type === "array" ? "[]." : "."), nivel + 1, vistos.concat([clave])));
      }
    });
    return filas;
  }

  function tabla(cabeceras, filas) {
    return '<div class="docs-table-wrap"><table class="docs-table"><thead><tr>' +
      cabeceras.map(function (c) { return "<th>" + c + "</th>"; }).join("") +
      "</tr></thead><tbody>" + filas.join("") + "</tbody></table></div>";
  }

  function ejemploDe(esq, nivel) {
    nivel = nivel || 0;
    var r = resolver(esq);
    if (r.example !== undefined) return r.example;
    if (r.enum) return r.enum[0];
    if (r.type === "array") return nivel > 2 ? [] : [ejemploDe(r.items || {}, nivel + 1)];
    if (r.type === "object" || r.properties) {
      var o = {};
      if (nivel > 2) return o;
      var req = r.required || [];
      Object.keys(r.properties || {}).forEach(function (k) {
        if (nivel === 0 || req.indexOf(k) !== -1) o[k] = ejemploDe(r.properties[k], nivel + 1);
      });
      return o;
    }
    if (r.type === "integer") return 1;
    if (r.type === "number") return 1.5;
    if (r.type === "boolean") return true;
    if (r.format === "date") return "2026-01-31";
    if (r.format === "date-time") return "2026-01-31T10:00:00Z";
    return "texto";
  }

  // --- Carga y lista --------------------------------------------------------
  function cargar() {
    fetch("/api/v1/openapi.json")
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (doc) {
        spec = doc;
        prepararLista();
        pintarLista();
        abrirDesdeHash(true);
      })
      .catch(function (err) {
        elGrupos.innerHTML = '<p class="api-explorer-cargando">No se ha podido cargar /api/v1/openapi.json (' + esc(err.message) + ").</p>";
      });
  }

  function prepararLista() {
    endpoints = [];
    var areas = {};
    Object.keys(spec.paths || {}).sort().forEach(function (ruta) {
      METODOS.forEach(function (metodo) {
        var op = spec.paths[ruta][metodo];
        if (!op) return;
        var area = op["x-area"] || "";
        if (area) areas[area] = true;
        endpoints.push({ ruta: ruta, metodo: metodo, op: op, tag: (op.tags && op.tags[0]) || "otros", area: area, id: op.operationId || (metodo + ruta) });
      });
    });
    if (elArea) {
      Object.keys(areas).sort().forEach(function (a) {
        var o = document.createElement("option");
        o.value = a;
        o.textContent = a;
        elArea.appendChild(o);
      });
      elArea.addEventListener("change", filtrar);
    }
    if (elFiltro) elFiltro.addEventListener("input", filtrar);
  }

  function pintarLista() {
    var porTag = {};
    endpoints.forEach(function (e) { (porTag[e.tag] = porTag[e.tag] || []).push(e); });
    elGrupos.innerHTML = "";
    botones = [];
    var fragmento = document.createDocumentFragment();
    Object.keys(porTag).sort().forEach(function (tag) {
      var grupo = document.createElement("div");
      grupo.className = "api-explorer-grupo";
      var h3 = document.createElement("h3");
      h3.textContent = tag;
      grupo.appendChild(h3);
      porTag[tag].forEach(function (e) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "api-explorer-endpoint";
        b.title = e.metodo.toUpperCase() + " " + e.ruta + (e.op.summary ? " — " + e.op.summary : "");
        b.innerHTML = badge(e.metodo) + '<span class="api-explorer-endpoint-ruta">' + esc(e.ruta.replace(/^\/api\/v1/, "")) + "</span>";
        b.dataset.filtro = (e.ruta + " " + e.metodo + " " + (e.op.summary || "") + " " + e.id + " " + e.area).toLowerCase();
        b.dataset.area = e.area;
        b.addEventListener("click", function () { seleccionar(e, true); });
        e.boton = b;
        grupo.appendChild(b);
        botones.push(b);
      });
      fragmento.appendChild(grupo);
    });
    elGrupos.appendChild(fragmento);
  }

  function filtrar() {
    var q = elFiltro ? elFiltro.value.trim().toLowerCase() : "";
    var area = elArea ? elArea.value : "";
    botones.forEach(function (b) {
      var ok = (q === "" || b.dataset.filtro.indexOf(q) !== -1) && (area === "" || b.dataset.area === area);
      b.style.display = ok ? "" : "none";
    });
    Array.prototype.forEach.call(elGrupos.querySelectorAll(".api-explorer-grupo"), function (g) {
      var visible = Array.prototype.some.call(g.querySelectorAll(".api-explorer-endpoint"), function (b) { return b.style.display !== "none"; });
      g.style.display = visible ? "" : "none";
    });
  }

  function abrirDesdeHash(primeraVez) {
    var id = "";
    try { id = decodeURIComponent((window.location.hash || "").replace(/^#/, "")); } catch (err) { /* hash mal formado */ }
    var e = endpoints.filter(function (x) { return x.id === id; })[0];
    if (e) seleccionar(e, false);
    else if (primeraVez) mostrarInicio();
  }
  window.addEventListener("hashchange", function () { if (spec) abrirDesdeHash(false); });

  function mostrarInicio() {
    var info = spec.info || {};
    var texto = esc(info.description || "")
      .replace(/^## (.*)$/gm, "<h2>$1</h2>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/^- (.*)$/gm, "<li>$1</li>")
      .replace(/\n/g, "<br>");
    elDetalle.innerHTML =
      '<p class="docs-kicker">EXPLORADOR DE API · v' + esc(info.version) + "</p><h1>" + esc(info.title) + "</h1>" +
      '<p class="docs-lead">' + endpoints.length + " operaciones. Elige una en la lista o descarga el contrato y los clientes:</p>" +
      '<p class="api-explorer-descargas"><a class="api-explorer-btn" href="/api/v1/openapi.json">openapi.json</a>' +
      '<a class="api-explorer-btn" href="/docs/sdk/guilda_work.py">Cliente Python</a>' +
      '<a class="api-explorer-btn" href="/docs/sdk/guilda-work.ts">Cliente TypeScript</a>' +
      '<a class="api-explorer-btn" href="/docs/sdk/guilda-work.postman_collection.json">Postman</a></p>' +
      '<div class="api-explorer-intro">' + texto + "</div>";
  }

  // --- Detalle --------------------------------------------------------------
  function parametrosDe(e) {
    var lista = ((spec.paths[e.ruta].parameters || []).concat(e.op.parameters || [])).map(resolver);
    var vistos = {};
    return lista.filter(function (p) {
      var k = p["in"] + ":" + p.name;
      if (vistos[k]) return false;
      vistos[k] = true;
      return true;
    });
  }

  function cuerpoDe(e) {
    var rb = e.op.requestBody && resolver(e.op.requestBody);
    if (!rb || !rb.content) return null;
    var tipo = rb.content["application/json"] ? "application/json" : Object.keys(rb.content)[0];
    var c = rb.content[tipo] || {};
    return { tipo: tipo, esquema: c.schema || {}, ejemplo: c.example };
  }

  function curlDe(e, params, cuerpo) {
    var url = ORIGEN + e.ruta.replace(/\{(\w+)\}/g, function (_, n) {
      var p = params.filter(function (x) { return x.name === n; })[0];
      return p ? String(ejemploDe(p.schema || {})) : "1";
    });
    var consulta = params.filter(function (p) { return p["in"] === "query" && p.required; })
      .map(function (p) { return p.name + "=" + ejemploDe(p.schema || {}); });
    if (consulta.length) url += "?" + consulta.join("&");
    var partes = ["curl -X " + e.metodo.toUpperCase() + ' "' + url + '"'];
    if (e.op.security && e.op.security.length) partes.push('  -H "Authorization: Bearer <tu-token>"');
    if (cuerpo) {
      if (cuerpo.tipo === "multipart/form-data") {
        var r = resolver(cuerpo.esquema);
        Object.keys(r.properties || {}).forEach(function (k) {
          var binario = resolver(r.properties[k]).format === "binary";
          partes.push("  -F '" + k + "=" + (binario ? "@archivo.pdf" : ejemploDe(r.properties[k])) + "'");
        });
      } else {
        var ej = cuerpo.ejemplo !== undefined ? cuerpo.ejemplo : ejemploDe(cuerpo.esquema);
        partes.push('  -H "Content-Type: application/json"');
        partes.push("  -d '" + JSON.stringify(ej).replace(/'/g, "'\\''") + "'");
      }
    }
    return partes.join(" \\\n");
  }

  function bloqueCodigo(titulo, texto) {
    return '<div class="docs-code"><div class="docs-code-cabecera"><span>' + esc(titulo) + "</span>" +
      '<button type="button" class="docs-code-copiar" data-code="' + esc(texto) + '">Copiar</button></div>' +
      "<pre><code>" + esc(texto) + "</code></pre></div>";
  }

  function seleccionar(e, actualizarHash) {
    botones.forEach(function (b) { b.classList.remove("is-activo"); });
    if (e.boton) e.boton.classList.add("is-activo");
    if (actualizarHash && window.history && window.history.replaceState) window.history.replaceState(null, "", "#" + encodeURIComponent(e.id));

    var op = e.op;
    var params = parametrosDe(e);
    var cuerpo = cuerpoDe(e);
    var html = '<div class="api-explorer-cabecera">' + badge(e.metodo) + '<span class="api-explorer-ruta">' + esc(e.ruta) + "</span></div>" +
      '<p class="api-explorer-resumen">' + esc(op.summary || "") + "</p>" +
      '<p class="api-explorer-etiquetas">' +
      (op.security && op.security.length ? '<span class="api-explorer-chip">Requiere <code>Authorization: Bearer</code></span>' : '<span class="api-explorer-chip">Público</span>') +
      (e.area ? '<span class="api-explorer-chip">Área: <code>' + esc(e.area) + "</code></span>" : "") +
      (op["x-escribe"] ? '<span class="api-explorer-chip">Escribe: no vale un token de solo lectura</span>' : '<span class="api-explorer-chip">Solo lectura</span>') +
      "</p>";
    if (op.description) html += "<p>" + esc(op.description).replace(/`([^`]+)`/g, "<code>$1</code>") + "</p>";

    var normales = params.filter(function (p) { return p["in"] !== "header"; });
    if (normales.length) {
      html += "<h2>Parámetros</h2>" + tabla(["Nombre", "En", "Tipo", "Obligatorio", "Descripción"], normales.map(function (p) {
        return "<tr><td><code>" + esc(p.name) + "</code></td><td>" + esc(p["in"]) + "</td><td>" + esc(tipoDe(p.schema || {})) + "</td><td>" +
          (p.required ? "sí" : "no") + "</td><td>" + esc(p.description || "") + "</td></tr>";
      }));
    }
    var cabeceras = params.filter(function (p) { return p["in"] === "header"; });
    if (cabeceras.length) {
      html += "<h2>Cabeceras opcionales</h2>" + tabla(["Nombre", "Descripción"], cabeceras.map(function (p) {
        return "<tr><td><code>" + esc(p.name) + "</code></td><td>" + esc(p.description || "") + "</td></tr>";
      }));
    }
    if (cuerpo) {
      var filas = filasEsquema(cuerpo.esquema, "", 0, [nombreRef(cuerpo.esquema)]);
      html += "<h2>Cuerpo de la petición <small>" + esc(cuerpo.tipo) + "</small></h2>";
      html += filas.length ? tabla(["Campo", "Tipo", "Obligatorio", "Descripción"], filas) : "<p>Sin campos documentados.</p>";
    }

    html += "<h2>Respuestas</h2>";
    Object.keys(op.responses || {}).forEach(function (codigo) {
      var r = resolver(op.responses[codigo]);
      var c = r.content && (r.content["application/json"] || r.content[Object.keys(r.content)[0]]);
      html += '<div class="api-explorer-respuesta"><div class="api-explorer-respuesta-cab"><code class="api-explorer-codigo api-explorer-codigo-' +
        esc(String(codigo).charAt(0)) + '">' + esc(codigo) + "</code><span>" + esc(r.description || "") + "</span></div>";
      if (c) {
        var ej = c.example !== undefined ? c.example : (c.schema ? ejemploDe(c.schema) : undefined);
        if (ej !== undefined) html += '<pre class="api-explorer-ejemplo"><code>' + esc(JSON.stringify(ej, null, 2)) + "</code></pre>";
      }
      html += "</div>";
    });

    html += "<h2>Ejemplo</h2>" + bloqueCodigo("curl", curlDe(e, params, cuerpo)) + probador(e, params, cuerpo);
    elDetalle.innerHTML = html;
    if (window.innerWidth < 900 && elDetalle.scrollIntoView) elDetalle.scrollIntoView();
    enganchar(e, cuerpo);
  }

  // --- Probar ---------------------------------------------------------------
  function probador(e, params, cuerpo) {
    var h = '<h2>Probar</h2><div class="api-explorer-probar">';
    if (e.metodo !== "get") h += '<p class="api-explorer-aviso">Esto ejecuta la operación de verdad sobre tus datos.</p>';
    h += '<label>Token <input type="password" id="ae-token" autocomplete="off" placeholder="Solo se guarda en esta pestaña" value="' + esc(guardado("gw_explorador_token") || "") + '"></label>';
    params.filter(function (p) { return p["in"] === "path" || p["in"] === "query"; }).forEach(function (p) {
      h += "<label>" + esc(p.name) + " <small>(" + esc(p["in"]) + (p.required ? ", obligatorio" : "") + ')</small><input type="text" data-param="' + esc(p["in"] + ":" + p.name) + '"></label>';
    });
    var json = cuerpo && cuerpo.tipo === "application/json";
    if (json) {
      var ej = cuerpo.ejemplo !== undefined ? cuerpo.ejemplo : ejemploDe(cuerpo.esquema);
      h += '<label>Cuerpo JSON<textarea id="ae-cuerpo" rows="7" spellcheck="false">' + esc(JSON.stringify(ej, null, 2)) + "</textarea></label>";
    } else if (cuerpo) {
      h += '<p class="api-explorer-aviso">Este cuerpo es ' + esc(cuerpo.tipo) + ": pruébalo con el curl de arriba.</p>";
    }
    return h + '<button type="button" class="api-explorer-btn" id="ae-enviar"' + (!cuerpo || json ? "" : " disabled") + ">Enviar</button>" +
      '<div id="ae-resultado" class="api-explorer-resultado" hidden></div></div>';
  }

  function enganchar(e, cuerpo) {
    Array.prototype.forEach.call(elDetalle.querySelectorAll(".docs-code-copiar"), function (b) {
      b.addEventListener("click", function () {
        if (!navigator.clipboard || !navigator.clipboard.writeText) return;
        navigator.clipboard.writeText(b.dataset.code).then(function () {
          b.textContent = "Copiado";
          setTimeout(function () { b.textContent = "Copiar"; }, 1500);
        });
      });
    });
    var enviar = document.getElementById("ae-enviar");
    if (!enviar) return;
    enviar.addEventListener("click", function () {
      var token = document.getElementById("ae-token").value.trim();
      guardado("gw_explorador_token", token || null);
      var ruta = e.ruta;
      var consulta = [];
      Array.prototype.forEach.call(elDetalle.querySelectorAll("[data-param]"), function (inp) {
        var partes = inp.dataset.param.split(":");
        var valor = inp.value.trim();
        if (partes[0] === "path") ruta = ruta.replace("{" + partes[1] + "}", encodeURIComponent(valor || "1"));
        else if (valor !== "") consulta.push(encodeURIComponent(partes[1]) + "=" + encodeURIComponent(valor));
      });
      var opciones = { method: e.metodo.toUpperCase(), headers: { Accept: "application/json" } };
      if (token) opciones.headers.Authorization = "Bearer " + token;
      var area = document.getElementById("ae-cuerpo");
      if (area && e.metodo !== "get") {
        try { JSON.parse(area.value); } catch (err) { return resultado("El cuerpo no es JSON válido: " + err.message, null); }
        opciones.headers["Content-Type"] = "application/json";
        opciones.body = area.value;
      }
      enviar.disabled = true;
      var t0 = performance.now();
      fetch(ruta + (consulta.length ? "?" + consulta.join("&") : ""), opciones)
        .then(function (r) {
          return r.text().then(function (texto) {
            var visto = texto;
            try { visto = JSON.stringify(JSON.parse(texto), null, 2); } catch (err) { /* no era JSON */ }
            if (visto.length > 20000) visto = visto.slice(0, 20000) + "\n… recortado";
            resultado(r.status + " " + r.statusText + " · " + Math.round(performance.now() - t0) + " ms · " + (r.headers.get("X-Request-Id") || ""), visto, r.ok);
          });
        })
        .catch(function (err) { resultado("Error de red: " + err.message, null); })
        .then(function () { enviar.disabled = false; });
    });
  }

  function resultado(cabecera, cuerpo, ok) {
    var el = document.getElementById("ae-resultado");
    el.hidden = false;
    el.className = "api-explorer-resultado" + (ok === false ? " is-error" : ok ? " is-ok" : "");
    el.innerHTML = "<strong>" + esc(cabecera) + "</strong>" + (cuerpo ? "<pre><code>" + esc(cuerpo) + "</code></pre>" : "");
  }

  cargar();
})();

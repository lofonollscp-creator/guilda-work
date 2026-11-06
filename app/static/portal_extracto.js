// «Revisar mi extracto»: lee el CSV del banco en el navegador y enseña los pagos que no tienen factura ni tiquet. Nada del extracto se envía: solo el formulario de «anotar como tiquet» de cada pago que la persona elija.
(function () {
  var raiz = document.getElementById('extracto');
  if (!raiz) return;
  var entrada = document.getElementById('extracto-archivo'), estado = document.getElementById('extracto-estado'), lista = document.getElementById('extracto-lista');
  var VENTANA_ANTES = 5, VENTANA_DESPUES = 45;      // el cargo en el banco suele caer entre unos días antes y semanas después de la fecha de la factura

  function t(clave, valores) {
    var x = raiz.getAttribute('data-txt-' + clave) || '';
    Object.keys(valores || {}).forEach(function (k) { x = x.replace('%(' + k + ')s', valores[k]); });
    return x;
  }
  function norm(s) { return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim(); }

  // Una línea de CSV respetando comillas.
  function partir(linea, sep) {
    var campos = [], actual = '', dentro = false;
    for (var i = 0; i < linea.length; i++) {
      var c = linea[i];
      if (c === '"') { if (dentro && linea[i + 1] === '"') { actual += '"'; i++; } else dentro = !dentro; }
      else if (c === sep && !dentro) { campos.push(actual); actual = ''; }
      else actual += c;
    }
    campos.push(actual);
    return campos.map(function (x) { return x.trim(); });
  }
  function separador(lineas) {
    var mejor = ';', maximo = 0;
    [';', '\t', ',', '|'].forEach(function (s) { var n = lineas.slice(0, 15).reduce(function (a, l) { return a + (l.split(s).length - 1); }, 0); if (n > maximo) { maximo = n; mejor = s; } });
    return mejor;
  }
  // «1.234,56», «-1234.56», «(45,00)», «45,00 EUR» → céntimos con signo (o null)
  function importe(texto) {
    var s = String(texto || '').replace(/[^\d,.\-+()]/g, '');
    if (!s) return null;
    var negativo = /^\(.*\)$/.test(s) || s.indexOf('-') >= 0;
    s = s.replace(/[()+\-]/g, '');
    var coma = s.lastIndexOf(','), punto = s.lastIndexOf('.');
    if (coma >= 0 && punto >= 0) s = coma > punto ? s.replace(/\./g, '').replace(',', '.') : s.replace(/,/g, '');
    else if (coma >= 0) s = (s.length - coma - 1 === 3 && s.indexOf(',') === coma && /^\d{1,3},\d{3}$/.test(s)) ? s.replace(',', '') : s.replace(',', '.');
    else if (punto >= 0 && s.length - punto - 1 === 3 && /^\d{1,3}\.\d{3}$/.test(s)) s = s.replace('.', '');
    var n = parseFloat(s);
    if (isNaN(n)) return null;
    n = Math.round(n * 100);
    return negativo ? -n : n;
  }
  function fecha(texto) {
    var s = String(texto || '').trim(), m;
    if ((m = s.match(/^(\d{4})-(\d{2})-(\d{2})/))) return m[1] + '-' + m[2] + '-' + m[3];
    if ((m = s.match(/^(\d{1,2})[\/.\-](\d{1,2})[\/.\-](\d{2,4})/))) {
      var a = m[3].length === 2 ? '20' + m[3] : m[3], mm = ('0' + m[2]).slice(-2), d = ('0' + m[1]).slice(-2);
      if (+mm >= 1 && +mm <= 12 && +d >= 1 && +d <= 31) return a + '-' + mm + '-' + d;
    }
    return null;
  }
  function dias(a, b) { return Math.round((Date.parse(a + 'T00:00:00Z') - Date.parse(b + 'T00:00:00Z')) / 86400000); }

  // Qué columna es cada cosa: por el título si lo hay y, si no, por lo que contienen.
  function columnas(filas) {
    var cab = filas[0].map(norm), idx = { fecha: -1, importe: -1, concepto: -1, cargo: -1, abono: -1 };
    cab.forEach(function (c, i) {
      if (idx.fecha < 0 && /^(fecha|f\.? ?operacion|f\.? ?valor|date|data)/.test(c)) idx.fecha = i;
      else if (idx.importe < 0 && /^(importe|cantidad|amount|import|monto)/.test(c)) idx.importe = i;
      else if (idx.concepto < 0 && /(concepto|descripcion|movimiento|detalle|description|concepte|observaciones)/.test(c)) idx.concepto = i;
      else if (idx.cargo < 0 && /(cargo|debito|debit|pago|salida)/.test(c)) idx.cargo = i;
      else if (idx.abono < 0 && /(abono|credito|credit|ingreso|entrada)/.test(c)) idx.abono = i;
    });
    var datos = filas.slice(1, 40);
    var cuantos = filas[0].length;
    if (idx.fecha < 0) for (var i = 0; i < cuantos; i++) if (datos.filter(function (f) { return fecha(f[i]); }).length >= datos.length * 0.8 && datos.length) { idx.fecha = i; break; }
    if (idx.importe < 0 && idx.cargo < 0) for (var j = 0; j < cuantos; j++) if (j !== idx.fecha && datos.filter(function (f) { return importe(f[j]) !== null && /\d[,.]\d{2}\s*\D*$/.test(f[j] || ''); }).length >= datos.length * 0.8 && datos.length) { idx.importe = j; break; }
    if (idx.concepto < 0) {
      var mejor = -1, largo = 0;
      for (var k = 0; k < cuantos; k++) if (k !== idx.fecha && k !== idx.importe && k !== idx.cargo && k !== idx.abono) { var l = datos.reduce(function (a, f) { return a + (f[k] || '').length; }, 0); if (l > largo) { largo = l; mejor = k; } }
      idx.concepto = mejor;
    }
    return idx;
  }

  function leer(texto) {
    var lineas = texto.replace(/^﻿/, '').split(/\r?\n/).filter(function (l) { return l.trim(); });
    if (lineas.length < 2) return { movimientos: [], error: 'vacio' };
    var sep = separador(lineas), filas = lineas.map(function (l) { return partir(l, sep); });
    // la cabecera real puede venir tras unas líneas de presentación del banco: la primera con al menos 3 campos y texto
    var inicio = 0;
    while (inicio < filas.length - 1 && (filas[inicio].length < 3 || filas[inicio].some(function (c) { return fecha(c); }))) { if (filas[inicio].some(function (c) { return fecha(c); })) break; inicio++; }
    filas = filas.slice(inicio);
    var idx = columnas(filas);
    var primeraEsDato = filas[0].some(function (c) { return fecha(c); });
    var cuerpo = primeraEsDato ? filas : filas.slice(1);
    if (primeraEsDato) { idx = columnas([filas[0].map(function () { return ''; })].concat(filas)); }
    if (idx.fecha < 0 || (idx.importe < 0 && idx.cargo < 0 && idx.abono < 0)) return { movimientos: [], error: 'columnas' };
    var movs = [];
    cuerpo.forEach(function (f) {
      var d = fecha(f[idx.fecha]);
      var imp = idx.importe >= 0 ? importe(f[idx.importe]) : null;
      if (imp === null && (idx.cargo >= 0 || idx.abono >= 0)) {
        var cargo = idx.cargo >= 0 ? importe(f[idx.cargo]) : null, abono = idx.abono >= 0 ? importe(f[idx.abono]) : null;
        imp = cargo ? -Math.abs(cargo) : (abono ? Math.abs(abono) : null);
      }
      if (d && imp !== null && imp !== 0) movs.push({ f: d, i: imp, c: (idx.concepto >= 0 ? f[idx.concepto] : '') || '' });
    });
    return { movimientos: movs, error: movs.length ? null : 'vacio' };
  }

  // Un pago está «cubierto» si hay una factura del mismo total cerca en el tiempo o un tiquet ya anotado con el mismo importe ese día.
  function pendientes(movs, datos) {
    var usadas = {};
    return movs.filter(function (m) { return m.i < 0; }).filter(function (m) {
      var imp = -m.i;
      var j = (datos.justificantes || []).some(function (x) { return x.i === m.i && x.f === m.f; });
      if (j) return false;
      for (var k = 0; k < datos.facturas.length; k++) {
        var fa = datos.facturas[k];
        if (usadas[k] || Math.abs(fa.t - imp) > 1) continue;
        var d = dias(m.f, fa.f);
        if (d >= -VENTANA_ANTES && d <= VENTANA_DESPUES) { usadas[k] = true; return false; }
      }
      return true;
    });
  }

  function formulario(m) {
    var li = document.createElement('li'); li.className = 'portal-persona';
    var datos = document.createElement('div'); datos.className = 'portal-persona-datos';
    var fuerte = document.createElement('strong'); fuerte.textContent = (-m.i / 100).toFixed(2).replace('.', ',') + ' €';
    var detalle = document.createElement('span'); detalle.className = 'muted'; detalle.textContent = m.f.split('-').reverse().join('/') + ' · ' + (m.c || '—');
    datos.appendChild(fuerte); datos.appendChild(detalle); li.appendChild(datos);
    if (raiz.getAttribute('data-puede-anotar') === '1') {
      var f = document.createElement('form'); f.method = 'post'; f.action = raiz.getAttribute('data-url-tiquet'); f.className = 'portal-persona-form';
      [['fecha', m.f], ['importe', (-m.i / 100).toFixed(2)], ['concepto', (m.c || 'Pago').slice(0, 140)]].forEach(function (p) { var h = document.createElement('input'); h.type = 'hidden'; h.name = p[0]; h.value = p[1]; f.appendChild(h); });
      var b = document.createElement('button'); b.type = 'submit'; b.className = 'btn btn-ghost'; b.textContent = t('anotar'); f.appendChild(b); li.appendChild(f);
    }
    var a = document.createElement('a'); a.className = 'btn btn-ghost'; a.href = raiz.getAttribute('data-url-facturas'); a.textContent = t('subir'); li.appendChild(a);
    return li;
  }

  entrada.addEventListener('change', function () {
    lista.textContent = ''; estado.textContent = '';
    var archivo = entrada.files && entrada.files[0];
    if (!archivo) return;
    var lector = new FileReader();
    lector.onload = function () {
      var r = leer(String(lector.result || ''));
      if (r.error === 'columnas') { estado.textContent = t('no-columnas'); return; }
      if (r.error) { estado.textContent = t('vacio'); return; }
      fetch(raiz.getAttribute('data-url-datos'), { credentials: 'same-origin' }).then(function (x) { return x.json(); }).then(function (datos) {
        var faltan = pendientes(r.movimientos, datos);
        estado.textContent = faltan.length ? t('resumen', { n: r.movimientos.length, k: faltan.length }) : t('todo-bien');
        faltan.sort(function (a, b) { return a.f < b.f ? 1 : -1; }).slice(0, 200).forEach(function (m) { lista.appendChild(formulario(m)); });
      }).catch(function () { estado.textContent = t('vacio'); });
    };
    lector.readAsText(archivo, 'utf-8');
  });
  window.__extracto = { leer: leer, pendientes: pendientes, importe: importe, fecha: fecha };           // para las pruebas del navegador
})();

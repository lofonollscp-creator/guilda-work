/* Formulario de apunte fiscal: ayudas mientras se escribe. Lo que la persona escribe a mano manda siempre; el servidor vuelve a validar todo al guardar.
   - base, tipo, cuota y total se completan entre sí (mismo redondeo que el servidor: al céntimo, mitad hacia arriba)
   - al escribir el NIF se reconoce una contraparte ya usada (nombre, tipo de NIF, país y lo habitual con ella)
   - avisos en vivo: dígito de control del NIF, cuota ≠ base × tipo, total ≠ base + cuota, número duplicado
   - la fecha de recepción sigue a la de expedición */
(function () {
  var f = document.querySelector('form[data-fiscal-apunte]');
  if (!f) return;
  var el = f.elements, libro = f.getAttribute('data-libro') || 'E', edicion = f.hasAttribute('data-edicion');
  var base = el.base, tipo = el.tipo_iva, cuota = el.cuota, total = el.total;
  if (!base || !tipo || !cuota || !total) return;
  var manual = { cuota: !!cuota.value, total: !!total.value };

  function mostrar(sel, valores) {                      // valores === null oculta el aviso
    var n = f.querySelector(sel);
    if (!n) return;
    if (!valores) { n.textContent = ''; return; }
    var t = n.getAttribute('data-texto') || '';
    Object.keys(valores).forEach(function (k) { t = t.split('{' + k + '}').join(valores[k]); });
    n.textContent = t;
  }
  function leer(v) {
    v = (v || '').replace(/\s/g, '').replace('€', '');
    if (!v) return null;
    if (v.indexOf(',') >= 0) v = v.replace(/\./g, '').replace(',', '.');
    var n = Number(v);
    return isFinite(n) ? Math.round(n * 100) : null;
  }
  function euros(centimos) { return (centimos / 100).toFixed(2).replace('.', ','); }
  function escribir(campo, centimos) { campo.value = centimos === null ? '' : euros(centimos); }
  function iva(centimos, pct) {
    var s = centimos < 0 ? -1 : 1;
    return s * Math.floor((Math.abs(centimos) * pct + 5000) / 10000);   // pct en centésimas
  }
  function porcentaje() { return leer(tipo.value); }                    // «21» -> 2100 centésimas

  /* --- importes que se completan entre sí --- */
  function desdeBase() {
    var b = leer(base.value), t = porcentaje();
    if (b === null || t === null) return;
    if (!manual.cuota) escribir(cuota, iva(b, t));
    var c = leer(cuota.value);
    if (!manual.total && c !== null) escribir(total, b + c);
  }
  function desdeTotal() {
    var tot = leer(total.value), t = porcentaje();
    if (tot === null || t === null) return;
    var b = Math.round(tot * 10000 / (10000 + t));
    [0, 1, -1].some(function (d) { if (b + d + iva(b + d, t) === tot) { b += d; return true; } return false; });   // prueba el entorno hasta que base + cuota = total
    escribir(base, b);
    manual.cuota = false;
    escribir(cuota, iva(b, t));
  }

  /* --- avisos en vivo --- */
  function exige() {                                    // solo las emitidas sujetas y no exentas y no rectificativas tienen la cuota «exacta» que valida la AEAT
    var cal = el.calificacion ? el.calificacion.value : '', ex = el.exenta ? el.exenta.value : '', tf = el.tipo_factura ? el.tipo_factura.value : 'F1';
    return libro === 'E' && cal === 'S1' && !ex && tf.charAt(0) !== 'R';
  }
  function revisarImportes() {
    var b = leer(base.value), t = porcentaje(), c = leer(cuota.value), tot = leer(total.value);
    mostrar('[data-cuota-aviso]', null); mostrar('[data-total-aviso]', null);
    if (!exige() || b === null || t === null) return;
    var esperada = iva(b, t);
    if (c !== null && c !== esperada) mostrar('[data-cuota-aviso]', { v: euros(esperada) });
    var clave = el.clave ? el.clave.value : '01';
    if (tot !== null && c !== null && ['03', '05', '09'].indexOf(clave) < 0 && tot !== b + c) mostrar('[data-total-aviso]', { v: euros(b + c) });
  }

  /* --- NIF español: dígito de control (DNI, NIE y CIF). Solo avisa; los demás formatos no se juzgan --- */
  function nifValido(v) {
    v = v.toUpperCase();
    var L = 'TRWAGMYFPDXBNJZSQVHLCKE', m;
    if (/^[0-9]{8}[A-Z]$/.test(v)) return L.charAt(parseInt(v.slice(0, 8), 10) % 23) === v.charAt(8);
    if (/^[XYZ][0-9]{7}[A-Z]$/.test(v)) return L.charAt(parseInt('XYZ'.indexOf(v.charAt(0)) + v.slice(1, 8), 10) % 23) === v.charAt(8);
    if (/^[ABCDEFGHJNPQRSUVW][0-9]{7}[0-9A-J]$/.test(v)) {
      var suma = 0, i, d;
      for (i = 0; i < 7; i++) { d = parseInt(v.charAt(i + 1), 10); if (i % 2 === 0) { d *= 2; suma += Math.floor(d / 10) + d % 10; } else suma += d; }
      var control = (10 - suma % 10) % 10, ch = v.charAt(8), letra = 'JABCDEFGHI'.charAt(control), primera = v.charAt(0);
      if ('PQRSNW'.indexOf(primera) >= 0) return ch === letra;
      if ('ABEH'.indexOf(primera) >= 0) return ch === String(control);
      return ch === String(control) || ch === letra;
    }
    return null;
  }
  function revisarNif() {
    var v = (el.contraparte_nif.value || '').replace(/[\s.-]/g, ''), tipoNif = el.contraparte_nif_tipo ? el.contraparte_nif_tipo.value : '';
    mostrar('[data-nif-aviso]', (tipoNif === '' && v.length === 9 && nifValido(v) === false) ? {} : null);
  }

  /* --- fechas --- */
  var recepcionPuesta = null;
  if (el.fecha_expedicion && el.fecha_recepcion) {
    el.fecha_expedicion.addEventListener('input', function () {
      if (!el.fecha_recepcion.value || el.fecha_recepcion.value === recepcionPuesta) { el.fecha_recepcion.value = el.fecha_expedicion.value; recepcionPuesta = el.fecha_expedicion.value; }
    });
  }
  var botonOperacion = f.querySelector('[data-mostrar-operacion]'), campoOperacion = f.querySelector('[data-fecha-operacion]');
  if (botonOperacion && campoOperacion) {
    botonOperacion.addEventListener('click', function () { campoOperacion.hidden = false; botonOperacion.hidden = true; if (el.fecha_operacion) el.fecha_operacion.focus(); });
  }

  /* --- número duplicado --- */
  var urlNumero = f.getAttribute('data-comprobar-url'), ultimaClave = '';
  function comprobarNumero() {
    var num = (el.numero.value || '').trim();
    if (!urlNumero || !num) { mostrar('[data-duplicado-aviso]', null); return; }
    var clave = [el.serie ? el.serie.value : '', num, el.contraparte_nif.value].join('|');
    if (clave === ultimaClave) return;
    ultimaClave = clave;
    var q = new URLSearchParams({ libro: libro, serie: el.serie ? el.serie.value : '', numero: num, nif: el.contraparte_nif.value });
    if (f.getAttribute('data-excluir')) q.set('excluir', f.getAttribute('data-excluir'));
    fetch(urlNumero + '?' + q.toString(), { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        mostrar('[data-duplicado-aviso]', d && d.existe ? { f: d.existe.fecha_expedicion } : null);
        mostrar('[data-duplicado-otros]', d && d.otros ? { n: d.otros } : null);
      })
      .catch(function () {});
  }

  /* --- contraparte conocida --- */
  var urlContraparte = f.getAttribute('data-contraparte-url'), nif = el.contraparte_nif, espera = null, ultimo = '', tocado = false, puestos = {}, sucio = {};
  var habituales = { tipo_iva: tipo, clave: el.clave, calificacion: el.calificacion, exenta: el.exenta, tipo_factura: el.tipo_factura };
  Object.keys(habituales).forEach(function (k) {
    var c = habituales[k];
    if (c) c.addEventListener('input', function (ev) { if (ev.isTrusted) sucio[k] = true; });
    if (c) c.addEventListener('change', function (ev) { if (ev.isTrusted) sucio[k] = true; });
  });
  function poner(clave, campo, valor) {
    if (!campo || !valor) return;
    if (!campo.value || campo.value === puestos[clave]) { campo.value = valor; puestos[clave] = valor; }
  }
  function buscar() {
    var v = nif.value.replace(/[\s.-]/g, '').toUpperCase();
    if (!urlContraparte || !tocado || v.length < 5 || v === ultimo) return;
    ultimo = v;
    fetch(urlContraparte + '?libro=' + encodeURIComponent(libro) + '&nif=' + encodeURIComponent(v), { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        var aviso = f.querySelector('[data-contraparte-aviso]');
        if (!d || !d.encontrada) { if (aviso) aviso.textContent = ''; return; }
        var e = d.encontrada;
        poner('nombre', el.contraparte_nombre, e.nombre); poner('nif_tipo', el.contraparte_nif_tipo, e.nif_tipo); poner('pais', el.contraparte_pais, e.pais);
        if (aviso) aviso.textContent = aviso.getAttribute('data-texto') + ' ' + e.nombre;
        if (e.habitual && !edicion) {                              // lo habitual con ella en este libro, salvo lo que la persona ya haya cambiado
          Object.keys(e.habitual).forEach(function (k) { if (habituales[k] && !sucio[k] && e.habitual[k] !== undefined && e.habitual[k] !== null) habituales[k].value = e.habitual[k]; });
          if (!sucio.tipo_iva) tipo.dispatchEvent(new Event('input', { bubbles: true }));
          revisarImportes();
        }
        comprobarNumero();
        revisarNif();
      })
      .catch(function () {});
  }

  base.addEventListener('input', function () { manual.total = false; desdeBase(); revisarImportes(); });                    // la base manda: el total la sigue
  tipo.addEventListener('input', function () { if (manual.total) desdeTotal(); else desdeBase(); revisarImportes(); });
  cuota.addEventListener('input', function () { manual.cuota = !!cuota.value; if (!manual.total) desdeBase(); revisarImportes(); });
  total.addEventListener('input', function () { manual.total = !!total.value; if (manual.total) desdeTotal(); revisarImportes(); });
  ['calificacion', 'exenta', 'tipo_factura', 'clave'].forEach(function (k) { if (el[k]) el[k].addEventListener('change', revisarImportes); });
  nif.addEventListener('input', function (ev) { if (ev.isTrusted) tocado = true; clearTimeout(espera); espera = setTimeout(function () { buscar(); revisarNif(); comprobarNumero(); }, 350); });
  nif.addEventListener('blur', function () { buscar(); revisarNif(); comprobarNumero(); });
  if (el.contraparte_nif_tipo) el.contraparte_nif_tipo.addEventListener('change', revisarNif);
  [el.numero, el.serie].forEach(function (c) { if (c) c.addEventListener('change', comprobarNumero); });
  revisarNif();
})();

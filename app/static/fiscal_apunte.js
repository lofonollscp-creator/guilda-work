/* Formulario de apunte fiscal: base, tipo, cuota y total se completan entre sí. Lo que la persona escribe a mano manda; lo calculado se sigue recalculando.
   Mismo redondeo que el servidor: al céntimo, mitad hacia arriba. */
(function () {
  var f = document.querySelector('form[data-fiscal-apunte]');
  if (!f) return;
  var base = f.elements.base, tipo = f.elements.tipo_iva, cuota = f.elements.cuota, total = f.elements.total;
  if (!base || !tipo || !cuota || !total) return;
  var manual = { cuota: !!cuota.value, total: !!total.value };

  function leer(v) {
    v = (v || '').replace(/\s/g, '').replace('€', '');
    if (!v) return null;
    if (v.indexOf(',') >= 0) v = v.replace(/\./g, '').replace(',', '.');
    var n = Number(v);
    return isFinite(n) ? Math.round(n * 100) : null;
  }
  function escribir(campo, centimos) {
    campo.value = centimos === null ? '' : (centimos / 100).toFixed(2).replace('.', ',');
  }
  function iva(centimos, pct) {
    var s = centimos < 0 ? -1 : 1;
    return s * Math.floor((Math.abs(centimos) * pct + 5000) / 10000);   // pct en centésimas
  }
  function porcentaje() {
    var t = leer(tipo.value);
    return t === null ? null : t;                                        // «21» -> 2100 centésimas
  }
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
  base.addEventListener('input', function () { manual.total = false; desdeBase(); });                       // la base manda: el total la sigue
  tipo.addEventListener('input', function () { if (manual.total) desdeTotal(); else desdeBase(); });
  cuota.addEventListener('input', function () { manual.cuota = !!cuota.value; if (!manual.total) desdeBase(); });
  total.addEventListener('input', function () { manual.total = !!total.value; if (manual.total) desdeTotal(); });
})();

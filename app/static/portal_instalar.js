// Invitación a instalar el portal como aplicación: en Chrome/Edge/Android con el botón del sistema; en iPhone y iPad con las instrucciones (Safari no tiene botón). Se ofrece a partir de la segunda visita,
// se puede descartar (no vuelve a salir en 30 días) y nunca sale si ya está instalada.
(function () {
  var caja = document.querySelector('[data-instalar]');
  if (!caja) return;
  var texto = caja.querySelector('[data-instalar-texto]'), boton = caja.querySelector('[data-instalar-boton]'), cerrar = caja.querySelector('[data-instalar-cerrar]');
  var CLAVE_NO = 'gw-instalar-no', CLAVE_VISITAS = 'gw-portal-visitas';
  function leer(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function guardar(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* sin almacenamiento no pasa nada */ } }
  var instalada = (window.matchMedia && matchMedia('(display-mode: standalone)').matches) || navigator.standalone === true;
  var visitas = parseInt(leer(CLAVE_VISITAS) || '0', 10) + 1;
  guardar(CLAVE_VISITAS, String(visitas));
  var no = parseInt(leer(CLAVE_NO) || '0', 10);
  if (instalada || visitas < 2 || (no && Date.now() - no < 30 * 24 * 3600 * 1000)) return;
  var propuesta = null;
  function mostrar(t, conBoton) { texto.textContent = t; boton.hidden = !conBoton; caja.hidden = false; }
  window.addEventListener('beforeinstallprompt', function (e) { e.preventDefault(); propuesta = e; mostrar(caja.getAttribute('data-txt-instalar'), true); });
  var ua = navigator.userAgent || '';
  if (/iPhone|iPad|iPod/.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua)) mostrar(caja.getAttribute('data-txt-ios'), false);
  boton.addEventListener('click', function () {
    if (!propuesta) return;
    propuesta.prompt();
    propuesta.userChoice.then(function () { propuesta = null; caja.hidden = true; guardar(CLAVE_NO, String(Date.now())); });
  });
  cerrar.addEventListener('click', function () { caja.hidden = true; guardar(CLAVE_NO, String(Date.now())); });
  window.addEventListener('appinstalled', function () { caja.hidden = true; });
})();

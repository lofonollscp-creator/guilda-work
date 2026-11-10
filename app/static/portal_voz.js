// Dictar por voz en el portal: graba con el micrófono, manda el audio a transcribir y pone el texto en el cuadro del mensaje para que la persona lo revise antes de enviarlo. El botón solo aparece si el navegador sabe grabar.
(function () {
  var boton = document.querySelector('button[data-voz]');
  if (!boton || !window.MediaRecorder || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
  var campo = document.getElementById(boton.getAttribute('data-voz'));
  var estado = document.querySelector('[data-voz-estado]');
  if (!campo) return;
  var MAX_SEGUNDOS = 120;
  boton.hidden = false;
  var grabador = null, trozos = [], temporizador = null, flujo = null;

  function decir(t) { if (estado) estado.textContent = t || ''; }
  function parar() { if (grabador && grabador.state !== 'inactive') grabador.stop(); }
  function liberar() { if (flujo) flujo.getTracks().forEach(function (p) { p.stop(); }); flujo = null; clearTimeout(temporizador); }

  function enviar(blob) {
    var datos = new FormData();
    datos.append('audio', blob, 'nota');
    var url = boton.getAttribute('data-url') + (boton.getAttribute('data-idioma') ? '?idioma=' + encodeURIComponent(boton.getAttribute('data-idioma')) : '');
    decir(boton.getAttribute('data-txt-pasando') || '…');
    return fetch(url, { method: 'POST', credentials: 'same-origin', body: datos }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); }).then(function (r) {
      if (r.ok && r.j.texto) {
        campo.value = (campo.value ? campo.value.replace(/\s+$/, '') + ' ' : '') + r.j.texto;
        campo.dispatchEvent(new Event('input', { bubbles: true }));
        decir('');
        campo.focus();
      } else decir(r.j.error || '');
    }).catch(function () { decir(boton.getAttribute('data-txt-error') || ''); });
  }

  boton.addEventListener('click', function () {
    if (grabador && grabador.state === 'recording') { parar(); return; }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (f) {
      flujo = f; trozos = [];
      grabador = new MediaRecorder(f);
      grabador.addEventListener('dataavailable', function (e) { if (e.data && e.data.size) trozos.push(e.data); });
      grabador.addEventListener('stop', function () {
        var tipo = grabador.mimeType || 'audio/webm';
        liberar();
        boton.setAttribute('aria-pressed', 'false');
        boton.textContent = boton.getAttribute('data-txt-dictar') || boton.textContent;
        if (trozos.length) enviar(new Blob(trozos, { type: tipo }));
      });
      grabador.start();
      boton.setAttribute('aria-pressed', 'true');
      boton.setAttribute('data-txt-dictar', boton.textContent);
      boton.textContent = boton.getAttribute('data-txt-parar') || '■';
      decir(boton.getAttribute('data-txt-grabando') || '');
      temporizador = setTimeout(parar, MAX_SEGUNDOS * 1000);
    }).catch(function () { decir(boton.getAttribute('data-txt-permiso') || ''); });
  });
})();

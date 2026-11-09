// Passkeys del portal (WebAuthn): añadir una desde «Mi cuenta» y entrar con ella desde la pantalla de acceso. Si el navegador no las admite, los botones no aparecen y todo sigue funcionando con el enlace del correo.
(function () {
  if (!window.PublicKeyCredential || !navigator.credentials) return;
  function aBuffer(s) {
    s = s.replace(/-/g, '+').replace(/_/g, '/'); while (s.length % 4) s += '=';
    var b = atob(s), a = new Uint8Array(b.length);
    for (var i = 0; i < b.length; i++) a[i] = b.charCodeAt(i);
    return a.buffer;
  }
  function aBase64(buf) {
    var a = new Uint8Array(buf), s = '';
    for (var i = 0; i < a.length; i++) s += String.fromCharCode(a[i]);
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function post(url, cuerpo) {
    return fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo || {}) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); });
  }
  function decir(zona, texto, alerta) { if (!zona) return; zona.textContent = texto; zona.setAttribute('role', alerta ? 'alert' : 'status'); zona.hidden = !texto; }
  function txt(el, clave) { return el.getAttribute('data-txt-' + clave) || ''; }

  var alta = document.querySelector('[data-passkey-alta]');
  if (alta) {
    alta.hidden = false;
    var zonaAlta = document.getElementById('passkey-mensaje');
    alta.addEventListener('click', function () {
      var nombre = (document.getElementById('passkey-nombre') || {}).value || '';
      alta.disabled = true;
      post(alta.getAttribute('data-url-opciones')).then(function (r) {
        if (!r.ok) throw new Error(r.j.error || txt(alta, 'fallo'));
        var o = r.j;
        o.challenge = aBuffer(o.challenge); o.user.id = aBuffer(o.user.id);
        o.excludeCredentials = (o.excludeCredentials || []).map(function (c) { c.id = aBuffer(c.id); return c; });
        return navigator.credentials.create({ publicKey: o });
      }).then(function (cred) {
        var resp = cred.response;
        return post(alta.getAttribute('data-url-verificar'), { nombre: nombre, credencial: {
          id: cred.id, rawId: aBase64(cred.rawId), type: cred.type, clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
          response: { clientDataJSON: aBase64(resp.clientDataJSON), attestationObject: aBase64(resp.attestationObject), transports: resp.getTransports ? resp.getTransports() : [] } } });
      }).then(function (r) {
        if (!r.ok) throw new Error(r.j.error || txt(alta, 'fallo'));
        location.href = alta.getAttribute('data-url-despues');
      }).catch(function (e) {
        alta.disabled = false;
        decir(zonaAlta, (e && e.name === 'NotAllowedError') ? txt(alta, 'cancelado') : ((e && e.message) || txt(alta, 'fallo')), true);
      });
    });
  }

  var entrar = document.querySelector('[data-passkey-entrar]');
  if (entrar) {
    entrar.hidden = false;
    var zonaEntrar = document.getElementById('passkey-entrar-mensaje');
    entrar.addEventListener('click', function () {
      entrar.disabled = true; decir(zonaEntrar, '', false);
      post(entrar.getAttribute('data-url-opciones')).then(function (r) {
        var o = r.j;
        o.challenge = aBuffer(o.challenge);
        return navigator.credentials.get({ publicKey: o });
      }).then(function (cred) {
        var resp = cred.response, recordar = document.querySelector('input[name=recordar]');
        return post(entrar.getAttribute('data-url-verificar'), { siguiente: entrar.getAttribute('data-siguiente') || '', recordar: !!(recordar && recordar.checked), credencial: {
          id: cred.id, rawId: aBase64(cred.rawId), type: cred.type, clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
          response: { clientDataJSON: aBase64(resp.clientDataJSON), authenticatorData: aBase64(resp.authenticatorData), signature: aBase64(resp.signature), userHandle: resp.userHandle ? aBase64(resp.userHandle) : null } } });
      }).then(function (r) {
        if (!r.ok) throw new Error(r.j.error || txt(entrar, 'fallo'));
        location.href = r.j.url;
      }).catch(function (e) {
        entrar.disabled = false;
        decir(zonaEntrar, (e && e.name === 'NotAllowedError') ? txt(entrar, 'cancelado') : ((e && e.message) || txt(entrar, 'fallo')), true);
      });
    });
  }
})();

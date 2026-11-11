// Passkeys del equipo con Kratos (W14). El script oficial de Kratos (`webauthn.js`, servido por el propio origen a través de /.ory/) define `oryPasskeyLogin()` y `oryPasskeySettingsRegistration()`, que leen sus datos de campos
// del formulario por nombre y lo envían ellos. Aquí solo se conectan los botones (sin manejadores en línea) y se muestran únicamente si el navegador admite WebAuthn y el script ha cargado.
(function () {
  "use strict";
  var entrar = document.querySelector("[data-passkey-login]");
  var registrar = document.querySelectorAll("[data-passkey-registrar]");
  var error = document.querySelector("[data-passkey-error]");
  function listo() { return !!window.PublicKeyCredential && typeof window.oryPasskeyLogin === "function"; }
  function preparar() {
    if (!listo()) return;
    if (entrar) entrar.hidden = false;
    Array.prototype.forEach.call(registrar, function (b) { b.hidden = false; });
  }
  function fallo() { if (error) error.hidden = false; }
  if (entrar) {
    entrar.addEventListener("click", function () {
      if (error) error.hidden = true;
      try { window.oryPasskeyLogin(); } catch (e) { fallo(); }
    });
  }
  Array.prototype.forEach.call(registrar, function (b) {
    b.addEventListener("click", function () {
      try { window.oryPasskeySettingsRegistration(); } catch (e) { /* el navegador enseña su propio aviso */ }
    });
  });
  window.addEventListener("oryWebAuthnInitialized", preparar);
  window.addEventListener("load", preparar);
  preparar();
})();

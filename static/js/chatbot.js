(function () {
  const cfg = window.ECAM_BOT || {};
  const $ = (s) => document.querySelector(s);
  const panel = $('#ecb-panel'), log = $('#ecb-log'), form = $('#ecb-form'),
        input = $('#ecb-input'), toggle = $('#ecb-toggle');
  let mode = 'chat';

  function bulle(texte, qui) {
    const d = document.createElement('div');
    d.className = 'ecb-msg ecb-' + qui;
    d.textContent = texte;                       // textContent : pas d'injection HTML
    log.appendChild(d); log.scrollTop = log.scrollHeight;
    return d;
  }
  function liens(l) {
    if (!l || !l.length) return;
    const w = document.createElement('div'); w.className = 'ecb-liens';
    l.forEach((x) => { const a = document.createElement('a'); a.href = x.url; a.textContent = x.label; w.appendChild(a); });
    log.appendChild(w); log.scrollTop = log.scrollHeight;
  }
  async function post(url, corps) {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF': cfg.csrf }, body: JSON.stringify(corps) });
    let j = {}; try { j = await r.json(); } catch (e) {}
    if (!r.ok) throw new Error(j.erreur || 'Une erreur est survenue (' + r.status + ').');
    return j;
  }
  async function demander(corps, affiche) {
    if (affiche) bulle(affiche, 'moi');
    const attente = bulle('…', 'bot');
    try { const j = await post('/api/chat', corps); attente.textContent = j.reponse; liens(j.liens); }
    catch (e) { attente.textContent = e.message; }
  }
  function modeDirecteur() {
    if (!cfg.connecte) {
      bulle('Pour écrire au directeur d’études, connectez-vous d’abord.', 'bot');
      liens([{ label: 'Se connecter', url: cfg.urlConnexion }]);
      return;
    }
    mode = 'directeur';
    bulle('Écrivez votre message : il sera transmis au directeur d’études.', 'bot');
    input.placeholder = 'Message pour le directeur d’études…'; input.focus();
  }

  toggle.addEventListener('click', () => {
    const ouvert = panel.hidden;
    panel.hidden = !ouvert; toggle.setAttribute('aria-expanded', String(ouvert));
    if (ouvert) input.focus();
  });
  document.querySelectorAll('.ecb-chip').forEach((b) => b.addEventListener('click', () => {
    if (b.dataset.topic === 'directeur') return modeDirecteur();
    demander({ topic: b.dataset.topic }, b.textContent);
  }));
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const t = input.value.trim(); if (!t) return;
    input.value = '';
    if (mode === 'directeur') {
      bulle(t, 'moi');
      try { await post('/api/transmettre', { destinataire: 'directeur_etudes', sujet: 'Message depuis l’assistant', message: t }); bulle('Message transmis au directeur d’études.', 'bot'); }
      catch (err) { bulle(err.message, 'bot'); }
      mode = 'chat'; input.placeholder = 'Votre question…';
    } else { demander({ message: t }, t); }
  });
})();

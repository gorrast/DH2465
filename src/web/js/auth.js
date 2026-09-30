'use strict';
(function () {
  const auth = { session: null, client: null };
  const isAuthPage = document.body.dataset.page === 'auth';
  const root = () => document.getElementById('auth-screen');
  const message = (text, kind) => {
    const node = document.getElementById('auth-message');
    if (node) { node.textContent = text || ''; node.className = 'auth-message' + (kind ? ' ' + kind : ''); }
  };
  function showAuth() {
    const screen = root();
    if (!screen) return;
    screen.hidden = false;
    screen.innerHTML = '';
    const form = document.createElement('form');
    form.className = 'auth-panel';
    form.innerHTML = '<div class="auth-mark" aria-hidden="true"><span></span><span></span><span></span></div>' +
      '<p class="auth-kicker">StressLess</p><h1 id="auth-title">Understand what shaped your night.</h1>' +
      '<p class="auth-lede">Connect your account to keep your health story private and ready wherever you are.</p>' +
      '<div class="auth-tabs" role="tablist"><button type="button" class="auth-tab active" data-mode="login">Sign in</button><button type="button" class="auth-tab" data-mode="register">Create account</button></div>' +
      '<label class="auth-label" for="auth-email">Email</label><input id="auth-email" class="auth-input" type="email" autocomplete="email" required>' +
      '<label class="auth-label" for="auth-password">Password</label><input id="auth-password" class="auth-input" type="password" minlength="6" autocomplete="current-password" required>' +
      '<button class="auth-submit" type="submit">Sign in</button><p id="auth-message" class="auth-message" role="status"></p>' +
      '<p class="auth-privacy">Your account is secured by Supabase. StressLess never receives your password.</p>';
    screen.appendChild(form);
    let mode = 'login';
    const submit = form.querySelector('.auth-submit');
    form.querySelectorAll('.auth-tab').forEach(tab => tab.addEventListener('click', () => {
      mode = tab.dataset.mode;
      form.querySelectorAll('.auth-tab').forEach(item => item.classList.toggle('active', item === tab));
      submit.textContent = mode === 'login' ? 'Sign in' : 'Create account';
      form.querySelector('#auth-password').setAttribute('autocomplete', mode === 'login' ? 'current-password' : 'new-password');
      message('');
    }));
    form.addEventListener('submit', async event => {
      event.preventDefault();
      submit.disabled = true;
      message('');
      const email = form.querySelector('#auth-email').value.trim();
      const password = form.querySelector('#auth-password').value;
      const result = mode === 'login'
        ? await auth.client.auth.signInWithPassword({ email, password })
        : await auth.client.auth.signUp({ email, password, options: { emailRedirectTo: new URL('/auth.html', location.origin).href } });
      submit.disabled = false;
      if (result.error) { message(result.error.message, 'error'); return; }
      if (mode === 'register' && !result.data.session) message('Check your email to confirm your account, then sign in.', 'success');
    });
  }
  function showSetup() {
    const screen = root();
    if (!screen) return;
    screen.hidden = false;
    screen.innerHTML = '<div class="auth-panel"><p class="auth-kicker">StressLess</p><h1>Connect Supabase to continue.</h1><p class="auth-lede">Set SUPABASE_URL and SUPABASE_ANON_KEY in the environment before starting the server.</p><p class="auth-privacy">The dashboard is locked until authentication is configured.</p></div>';
  }
  async function init() {
    const response = await fetch('/api/config');
    const config = await response.json();
    if (!config.supabase_url || !config.supabase_anon_key || !window.supabase) { showSetup(); return; }
    auth.client = window.supabase.createClient(config.supabase_url, config.supabase_anon_key);
    const current = await auth.client.auth.getSession();
    auth.session = current.data.session;
    if (isAuthPage && auth.session) { location.replace('/'); return; }
    if (!isAuthPage && !auth.session) { location.replace('/auth.html'); return; }
    if (isAuthPage) showAuth();
    auth.client.auth.onAuthStateChange((event, session) => {
      auth.session = session;
      if (session) {
        if (isAuthPage) location.replace('/');
        else document.dispatchEvent(new Event('stressless-authenticated'));
      } else if (!isAuthPage) location.replace('/auth.html');
    });
  }
  auth.signOut = async () => { if (auth.client) await auth.client.auth.signOut(); };
  auth.ready = init().catch(error => { showSetup(); message(error.message, 'error'); });
  window.StressLessAuth = auth;
})();

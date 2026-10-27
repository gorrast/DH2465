'use client';

import Link from 'next/link';
import { useApp } from '../shell/AppContext';
import { Icon } from '../ui/Icon';
import { ViewHead } from './common';

export function AccountView() {
  const { userEmail, theme, toggleTheme, signOut } = useApp();
  return <>
    <ViewHead eyebrow="My Account" title="Make yourself at home" />
    <div className="stack">
      <section className="card stack" aria-labelledby="account-details">
        <h2 id="account-details">Your account</h2>
        <div><span className="small muted">Signed in as</span><p>{userEmail || 'Email unavailable'}</p></div>
        <div className="row">
          <Link className="btn" href="/reset-password">Change password</Link>
          <button className="btn" type="button" onClick={signOut}><Icon name="logout" size={16} />Sign out</button>
        </div>
      </section>
      <section className="card stack" aria-labelledby="account-appearance">
        <h2 id="account-appearance">Appearance</h2>
        <p className="secondary">Choose the theme that feels comfortable. Your choice is saved on this device.</p>
        <button className="btn" type="button" onClick={toggleTheme}><Icon name={theme === 'dark' ? 'sun' : 'moon'} size={16} />Switch to {theme === 'dark' ? 'light' : 'dark'} theme</button>
      </section>
      <section className="card stack" aria-labelledby="account-data">
        <h2 id="account-data">Your data</h2>
        <p className="secondary">Manage your sources and understand how StressLess uses your information.</p>
        <div className="row"><Link className="btn" href="/connect">Connect Your Data</Link><Link className="btn" href="/data">Data and Privacy</Link></div>
      </section>
    </div>
  </>;
}
